"""Aplicação principal: ações, linha de comando, fluxo de print e de gravação."""

import os
import platform
import threading
from pathlib import Path

from gi.repository import Adw, Gdk, Gio, GLib, Gtk

from . import APP_ID, APP_NAME, IS_WINDOWS, VERSION, log, naming
from .capture.region import monitor_crop
from .config import config
from .editor.window import CaptureWindow
from .main_window import IDLE, NAMING, RECORDING, STARTING, STOPPING, MainWindow, fmt_time
from .name_dialog import FilenamePrompt, ask_filename

if IS_WINDOWS:
    from .win32.screenshot import take_screenshot
else:
    from .capture.screenshot import take_screenshot

logger = log.get(__name__)

STATE_NAMES = {IDLE: "parado", STARTING: "iniciando", RECORDING: "gravando", STOPPING: "finalizando",
               NAMING: "aguardando nome"}


def _code_stamp():
    """Data de modificação mais recente dos arquivos .py do app."""
    root = Path(__file__).resolve().parent
    return max((p.stat().st_mtime for p in root.rglob("*.py")), default=0)


def _session_bus_available(timeout=5):
    """A instância única do GApplication usa o D-Bus de sessão. No Windows o GLib sobe um
    (gdbus.exe) sob demanda; se isso falhar, o app roda sem instância única em vez de
    não abrir."""
    result = []

    def probe():
        try:
            result.append(Gio.bus_get_sync(Gio.BusType.SESSION, None) is not None)
        except GLib.Error as e:
            logger.warning("D-Bus de sessão indisponível: %s", e.message)
            result.append(False)

    thread = threading.Thread(target=probe, name="dbus-probe", daemon=True)
    thread.start()
    thread.join(timeout)
    return bool(result and result[0])


class ScreenToolboxApp(Adw.Application):
    def __init__(self, dev=False):
        # no modo dev usa outro ID, para não ser redirecionado para uma instância instalada aberta
        app_id = f"{APP_ID}.Devel" if dev else APP_ID
        flags = Gio.ApplicationFlags.HANDLES_COMMAND_LINE
        if IS_WINDOWS and not _session_bus_available():
            logger.warning("Sem D-Bus de sessão: rodando sem instância única "
                           "(atalhos do menu Iniciar abrirão uma nova instância)")
            flags |= Gio.ApplicationFlags.NON_UNIQUE
        super().__init__(application_id=app_id, flags=flags)
        self.dev = dev
        self.main_window = None
        self.capturing = False
        self.record_state = IDLE
        self.cast = None
        self.recorder = None
        self._pending_video = None  # vídeo gravado ainda sem nome
        self._name_prompt = None  # diálogo aberto para esse vídeo (nome ou descarte)
        self.input_monitor = None
        self.key_overlay = None
        self._timer = 0
        self._clipboard_hold = None
        self._background_hold = False
        self.tray = None
        self._permissions_dialog = None
        # para detectar reinstalação enquanto o app roda em segundo plano
        self._code_stamp = _code_stamp()
        self.restart_argv = None

        GLib.set_application_name(APP_NAME)
        self.add_main_option("screenshot", ord("s"), GLib.OptionFlags.NONE, GLib.OptionArg.NONE,
                             "Capturar uma área da tela (seleção de região)", None)
        self.add_main_option("record", ord("r"), GLib.OptionFlags.NONE, GLib.OptionArg.NONE,
                             "Iniciar/parar gravação de tela", None)
        self.add_main_option("stop", 0, GLib.OptionFlags.NONE, GLib.OptionArg.NONE,
                             "Parar a gravação em andamento", None)
        self.add_main_option("background", 0, GLib.OptionFlags.NONE, GLib.OptionArg.NONE,
                             "Iniciar em segundo plano, sem abrir a janela", None)

    # --- ciclo de vida ---------------------------------------------------
    def do_startup(self):
        Adw.Application.do_startup(self)
        self._log_environment()
        # ícone do app quando rodando direto do código-fonte (sem instalar)
        source_data = Path(__file__).resolve().parent.parent / "data"
        if (source_data / f"{APP_ID}.svg").exists():
            Gtk.IconTheme.get_for_display(Gdk.Display.get_default()).add_search_path(str(source_data))
        Gtk.Window.set_default_icon_name(APP_ID)

        actions = {
            "screenshot": lambda *_: self.capture(),
            "record": lambda *_: self.toggle_recording(),
            "preferences": lambda *_: self.show_preferences(),
            "permissions": lambda *_: self.show_permissions(),
            "about": lambda *_: self.show_about(),
            "quit": lambda *_: self.request_quit(),
        }
        for name, cb in actions.items():
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", self._logged_action(name, cb))
            self.add_action(action)

        open_action = Gio.SimpleAction.new("open-file", GLib.VariantType("s"))
        open_action.connect("activate", lambda _a, p: self.open_file(p.unpack()))
        self.add_action(open_action)

        self.set_accels_for_action("app.screenshot", ["<Ctrl>1"])
        self.set_accels_for_action("app.record", ["<Ctrl>2"])
        self.set_accels_for_action("app.preferences", ["<Ctrl>comma"])
        self.set_accels_for_action("app.quit", ["<Ctrl>q"])
        if not IS_WINDOWS:  # a tela de permissões só existe no Linux
            self.set_accels_for_action("app.permissions", ["<Ctrl>h"])
        self.set_background(config.get("run_in_background"))
        # no Windows o ícone fica sempre ativo: ele também registra os atalhos globais
        # e mostra as notificações
        self.set_tray(IS_WINDOWS or config.get("show_tray"))

    def do_shutdown(self):
        logger.info("Encerrando o app")
        self.set_tray(False)
        if self.record_state != IDLE:
            logger.warning("App encerrado com gravação em estado '%s'", STATE_NAMES[self.record_state])
        Adw.Application.do_shutdown(self)

    @staticmethod
    def _logged_action(name, callback):
        def handler(*args):
            logger.info("Ação: %s", name)
            callback(*args)
        return handler

    def _log_environment(self):
        from gi.repository import Gst

        if not Gst.is_initialized():
            Gst.init(None)
        logger.info("%s %s (app id %s)%s", APP_NAME, VERSION, self.get_application_id(),
                    " [modo dev]" if self.dev else "")
        logger.info("Python %s | GTK %d.%d.%d | libadwaita %d.%d.%d | %s",
                    platform.python_version(),
                    Gtk.get_major_version(), Gtk.get_minor_version(), Gtk.get_micro_version(),
                    Adw.get_major_version(), Adw.get_minor_version(), Adw.get_micro_version(),
                    Gst.version_string())
        if IS_WINDOWS:
            logger.info("Sistema: %s | Backend GDK: %s", platform.platform(),
                        type(Gdk.Display.get_default()).__name__)
        else:
            logger.info("Sessão: %s | Desktop: %s | Backend GDK: %s",
                        os.environ.get("XDG_SESSION_TYPE", "?"), os.environ.get("XDG_CURRENT_DESKTOP", "?"),
                        type(Gdk.Display.get_default()).__name__)
        display = Gdk.Display.get_default()
        monitors = display.get_monitors()
        for i in range(monitors.get_n_items()):
            m = monitors.get_item(i)
            g = m.get_geometry()
            scale = m.get_scale() if hasattr(m, "get_scale") else m.get_scale_factor()
            logger.info("Monitor %d: %s %dx%d+%d+%d escala %.2f", i, m.get_connector(), g.width, g.height,
                        g.x, g.y, scale)
        if not IS_WINDOWS:
            self._log_linux_environment()
        logger.debug("Configuração: %s", {k: v for k, v in config.items() if k != "restore_token"})
        orphans = sorted(Path(config.get("video_dir")).glob(".screen-toolbox-*.part.*"))
        if orphans:
            logger.warning("Gravações não nomeadas de sessões anteriores (renomeie para recuperar): %s",
                           ", ".join(str(p) for p in orphans))

    @staticmethod
    def _log_linux_environment():
        from .portal import get_portal
        from .record.input_events import readable_devices

        portal = get_portal()
        logger.info("Portais: Screenshot v%s | ScreenCast v%s (fontes=%s, cursor=%s)",
                    portal.get_property("org.freedesktop.portal.Screenshot", "version", "ausente"),
                    portal.get_property("org.freedesktop.portal.ScreenCast", "version", "ausente"),
                    portal.get_property("org.freedesktop.portal.ScreenCast", "AvailableSourceTypes", "?"),
                    portal.get_property("org.freedesktop.portal.ScreenCast", "AvailableCursorModes", "?"))
        devices = readable_devices()
        if devices:
            logger.info("Dispositivos de entrada legíveis: %d", len(devices))
        else:
            logger.warning("Nenhum /dev/input/event* legível: teclas/cliques não aparecerão nos vídeos "
                           "(adicione o usuário ao grupo 'input')")

    def do_command_line(self, command_line):
        opts = command_line.get_options_dict().end().unpack()
        logger.info("Linha de comando: %s (instância %s)",
                    " ".join(f"--{name}" for name, value in opts.items() if value) or "(sem opções)",
                    "remota" if command_line.get_is_remote() else "local")
        if command_line.get_is_remote() and self._should_restart():
            # O código foi atualizado (ex.: `make install`) enquanto esta instância seguia em
            # segundo plano: reinicia com o código novo e repassa o pedido.
            logger.warning("Código do app foi atualizado; reiniciando a instância em segundo plano")
            self.restart_argv = [f"--{name}" for name, value in opts.items() if value and name != "dev"]
            self.quit()
            return 0
        if opts.get("stop"):
            if self.record_state == RECORDING:
                self.stop_recording()
            else:
                logger.warning("--stop ignorado: nenhuma gravação em andamento (estado: %s)",
                               STATE_NAMES[self.record_state])
        elif opts.get("record"):
            self.toggle_recording()
        elif opts.get("screenshot"):
            self.capture()
        elif opts.get("background"):
            logger.info("Iniciado em segundo plano")
        else:
            self.activate()
        return 0

    def _should_restart(self):
        # no Windows o app roda empacotado (sem `make install` sobre o código em uso)
        return (not IS_WINDOWS and self._code_stamp != _code_stamp() and self.record_state == IDLE
                and not self.capturing and self._clipboard_hold is None)

    def do_activate(self):
        self._ensure_main_window().present()
        # primeira execução: configuração inicial das permissões (no Windows não há o que liberar)
        if not IS_WINDOWS and not config.get("setup_done"):
            config.set("setup_done", True)
            self.show_permissions(first_run=True)

    # --- segundo plano ---------------------------------------------------
    def set_background(self, enabled):
        """Com o modo ativo, o app fica sempre rodando (mesmo sem janelas), para que atalhos,
        menu e dock respondam na hora. Só encerra por "Sair"."""
        if enabled and not self._background_hold:
            self._background_hold = True
            self.hold()
            logger.debug("Modo segundo plano ativo")
        elif not enabled and self._background_hold:
            self._background_hold = False
            self.release()
            logger.debug("Modo segundo plano desativado")

    def enter_background(self):
        logger.info("Janela fechada; app continua em segundo plano")
        if not config.get("background_notice_shown"):
            config.set("background_notice_shown", True)
            text = "Continua rodando em segundo plano. Para encerrar, use “Sair” no menu (Ctrl+Q)."
            if IS_WINDOWS:
                text = "Continua rodando na bandeja. Para encerrar, use “Sair” no menu do ícone."
            self._system_notification(text, notification_id="background")

    def request_quit(self):
        if self.record_state != IDLE:
            logger.warning("Sair bloqueado: gravação em estado '%s'", STATE_NAMES[self.record_state])
            self._present_main_window()
            if self.record_state == NAMING:
                self._raise_name_prompt()
                self.notify_user("Salve ou descarte o vídeo antes de sair.")
            else:
                self.notify_user("Pare a gravação antes de sair.")
            return
        logger.info("Saindo do app (pedido do usuário)")
        self.quit()

    def _ensure_main_window(self):
        if self.main_window is None:
            logger.debug("Criando janela principal")
            self.main_window = MainWindow(self)
            self.main_window.connect("destroy", self._on_main_destroy)
        return self.main_window

    def _on_main_destroy(self, *_):
        logger.debug("Janela principal fechada")
        self.main_window = None

    def notify_user(self, text, button=None, action=None, target=None):
        """Toast na janela principal (se visível) ou notificação do sistema."""
        win = self.main_window
        if win is not None and win.get_visible():
            logger.debug("Toast: %s", text)
            win.toast(text, button, action, target)
            return
        self._system_notification(text, button, action, target)

    def _system_notification(self, text, button=None, action=None, target=None, notification_id=None):
        logger.debug("Notificação do sistema: %s", text)
        if IS_WINDOWS:
            # o GLib não tem backend de notificações no Windows: usa o balão da bandeja
            if self.tray is not None:
                self.tray.notify(text, action, target)
            return
        notification = Gio.Notification.new(APP_NAME)
        notification.set_body(text)
        if button and action:
            notification.add_button_with_target(button, action, target)
            notification.set_default_action_and_target(action, target)
        self.send_notification(notification_id, notification)

    def open_file(self, path):
        """Abre com o app padrão; sem app padrão o sistema oferece "Abrir com…".
        Se ainda assim falhar, abre a pasta com o arquivo selecionado."""
        logger.info("Abrindo %s", path)
        file = Gio.File.new_for_path(path)
        parent = self.main_window if self.main_window is not None and self.main_window.get_visible() else None
        launcher = Gtk.FileLauncher.new(file)

        def opened(launcher, res):
            try:
                launcher.launch_finish(res)
            except GLib.Error as e:
                logger.warning("Não foi possível abrir %s (%s); abrindo a pasta", path, e.message)
                launcher.open_containing_folder(parent, None, folder_opened)

        def folder_opened(launcher, res):
            try:
                launcher.open_containing_folder_finish(res)
            except GLib.Error as e:
                logger.error("Falha ao abrir a pasta de %s: %s", path, e.message)
                self.notify_user(f"Não foi possível abrir: {e.message}")

        launcher.launch(parent, None, opened)

    # --- print -----------------------------------------------------------
    def capture(self):
        """Print sempre por seleção de área (um seletor em cada monitor)."""
        if self.capturing:
            logger.warning("Captura ignorada: já existe uma captura em andamento")
            return
        self.capturing = True
        self.hold()

        win = self.main_window
        display = Gdk.Display.get_default()
        monitor_list = display.get_monitors()
        monitors = [monitor_list.get_item(i) for i in range(monitor_list.get_n_items())]
        was_visible = win is not None and win.get_visible()
        if was_visible:
            win.set_visible(False)
        logger.info("Iniciando captura; janela principal %s", "ocultada" if was_visible else "não visível")

        def restore():
            if was_visible and self.main_window is not None:
                self.main_window.set_visible(True)

        windows = []

        def on_done(result):
            for window in windows:
                window.cancel_silently()
            logger.info("Captura encerrada: %s", {"copied": "copiada", "saved": "salva",
                                                  "cancelled": "cancelada"}.get(result, result))
            restore()
            self.capturing = False
            self.release()

        def on_selection_started(started):
            # seleção iniciada num monitor: fecha as telas de captura dos outros
            for window in windows:
                if window.canvas is not started:
                    window.cancel_silently()

        permission_attempted = []

        def request_permission():
            """No GNOME, um app identificado (aberto pelo menu) precisa de permissão para
            prints sem diálogo, e o pedido só aparece se o app estiver em foco. Mostra a
            janela, pede a permissão e, se concedida, refaz o print com a janela oculta."""
            permission_attempted.append(True)
            logger.warning("Portal recusou o print; pedindo permissão com a janela em foco")
            win = self._present_main_window()

            def on_permission_shot(surface, error):
                if surface is None:
                    logger.error("Permissão de captura não concedida: %s", error or "cancelado")
                    self.notify_user("Sem permissão para capturar a tela.", "Permissões", "app.permissions")
                    self.capturing = False
                    self.release()
                    return
                logger.info("Permissão de captura concedida")
                win.set_visible(False)
                GLib.timeout_add(400, lambda: take_screenshot(on_shot) and False)

            GLib.timeout_add(600, lambda: take_screenshot(on_permission_shot) and False)

        def on_shot(surface, error):
            if surface is None:
                if error and not permission_attempted and not IS_WINDOWS:
                    request_permission()
                    return
                restore()
                if error:
                    logger.error("Falha ao capturar a tela: %s", error)
                    self.notify_user(f"Falha ao capturar a tela: {error}")
                else:
                    logger.info("Captura cancelada no portal")
                self.capturing = False
                self.release()
                return
            # uma tela de captura/edição por monitor: o usuário seleciona em qualquer uma
            for monitor in monitors or [None]:
                crop = monitor_crop(surface, display, monitor)
                logger.debug("Tela de captura no monitor %s (%dx%d)",
                             monitor.get_connector() if monitor else "?", crop.get_width(), crop.get_height())
                window = CaptureWindow(self, crop, monitor, on_done)
                window.canvas.connect("selection-started", on_selection_started)
                windows.append(window)
            for window in windows:
                window.present()

        # dá tempo de a janela sumir antes da captura
        delay_ms = max(400 if was_visible else 50, int(config.get("screenshot_delay") * 1000))
        logger.debug("Capturando em %d ms", delay_ms)
        GLib.timeout_add(delay_ms, lambda: take_screenshot(on_shot) and False)

    def keep_clipboard_alive(self):
        """No Wayland a área de transferência some quando o app fecha; segura o app
        até que outro programa copie algo (ou por 30 minutos)."""
        if self._clipboard_hold is not None:
            return
        clipboard = Gdk.Display.get_default().get_clipboard()
        self.hold()
        logger.info("Mantendo o app ativo para preservar a área de transferência")

        def release(from_timeout=False):
            if self._clipboard_hold is None:
                return False
            handler, timeout = self._clipboard_hold
            self._clipboard_hold = None
            clipboard.disconnect(handler)
            if not from_timeout:
                GLib.source_remove(timeout)
            logger.info("Área de transferência liberada (%s)", "tempo esgotado" if from_timeout else "outro app copiou")
            self.release()
            return False

        def on_changed(cb):
            if not cb.is_local():
                release()

        handler = clipboard.connect("changed", on_changed)
        timeout = GLib.timeout_add_seconds(30 * 60, release, True)
        self._clipboard_hold = (handler, timeout)

    # --- gravação --------------------------------------------------------
    def _set_record_state(self, state):
        if state != self.record_state:
            logger.debug("Gravação: %s -> %s", STATE_NAMES[self.record_state], STATE_NAMES[state])
        self.record_state = state

    def toggle_recording(self):
        if self.record_state == IDLE:
            self.start_recording()
        elif self.record_state == RECORDING:
            self.stop_recording()
        elif self.record_state == NAMING:
            logger.info("Nova gravação bloqueada: o vídeo anterior ainda não tem nome")
            self._raise_name_prompt()
            self.notify_user("Dê um nome ou descarte a gravação anterior antes de gravar outra.")
        else:
            logger.warning("Alternar gravação ignorado no estado '%s'", STATE_NAMES[self.record_state])

    def start_recording(self):
        if self.record_state != IDLE:
            return
        self._set_record_state(STARTING)
        self.hold()
        self._update_record_ui()
        if IS_WINDOWS:
            from .win32.screencast import WinScreenSource

            self.cast = WinScreenSource(config.get("record_monitor"))
            self.cast.start(self._on_cast_ready, self._on_cast_error, self._on_cast_closed,
                            show_cursor=config.get("record_cursor"))
            return

        from .record.screencast import ScreenCastSession

        self.cast = ScreenCastSession()
        remember = config.get("remember_source")
        token = config.get("restore_token") if remember else ""
        logger.info("Solicitando captura de tela ao portal (lembrar tela: %s, token salvo: %s)",
                    remember, "sim" if token else "não")
        self.cast.start(
            self._on_cast_ready, self._on_cast_error, self._on_cast_closed,
            show_cursor=config.get("record_cursor"),
            restore_token=token,
            persist=remember,
        )

    def _on_cast_error(self, message):
        if message:
            logger.error("Portal de gravação falhou: %s", message)
            self.notify_user(f"Não foi possível gravar: {message}")
        else:
            logger.info("Seleção de tela cancelada pelo usuário")
        self._cleanup_recording()

    def _on_cast_closed(self):
        logger.info("Sessão de captura encerrada pelo sistema (estado: %s)", STATE_NAMES[self.record_state])
        if self.record_state == RECORDING:
            self.stop_recording()
        elif self.record_state == STARTING:
            self._cleanup_recording()

    def _record_fps(self):
        """Taxa de quadros da config, sem passar da taxa de atualização da tela gravada."""
        from .record import framerate

        display = Gdk.Display.get_default()
        if IS_WINDOWS:
            from .win32.screenshot import monitors

            refresh = framerate.refresh_of_index(display, monitors(), self.cast.monitor_index)
        else:
            refresh = framerate.refresh_at(display, getattr(self.cast, "position", None))
        wanted = int(config.get("fps"))
        fps = framerate.clamp(wanted, refresh)
        logger.info("Taxa de quadros: %d fps (pedido %d, tela a %.2f Hz)", fps, wanted, refresh)
        if fps < wanted and refresh > 0:
            self.notify_user(f"A tela é de {round(refresh)} Hz: gravando a {fps} fps em vez de {wanted}.")
        return fps

    def _on_cast_ready(self, video_source, details):
        from .record.input_events import KeystrokeModel
        from .record.overlay import KeyOverlay
        from .record.pipeline import Recorder

        if IS_WINDOWS:
            from .win32.input_hook import InputMonitor, input_access_ok
            from .win32.keylabel import WinKeyLabeler as KeyLabeler
        else:
            from .record.input_events import InputMonitor, input_access_ok
            from .record.keymap import KeyLabeler

        logger.info("Tela compartilhada: %s", details)
        if config.get("remember_source") and self.cast.restore_token:
            config.set("restore_token", self.cast.restore_token)
        elif self.cast.not_monitor:
            config.set("restore_token", "")

        overlay = None
        if config.get("show_keys") or config.get("show_clicks"):
            if input_access_ok():
                model = KeystrokeModel(KeyLabeler(), config.get("show_keys"), config.get("show_clicks"),
                                       config.get("overlay_duration"))
                overlay = KeyOverlay(model, config.get("overlay_position"), config.get("overlay_scale"))
                self.key_overlay = overlay
                self.input_monitor = InputMonitor(model.handle)
            else:
                logger.warning("Sem acesso a /dev/input: gravando sem teclas/cliques")
                self.notify_user("Sem acesso ao teclado/mouse: teclas e cliques não aparecerão no vídeo.")
        else:
            logger.info("Exibição de teclas e cliques desligada")

        options = {k: config.get(k) for k in ("video_dir", "video_format", "fps", "record_mic", "record_system_audio")}
        options["fps"] = self._record_fps()
        try:
            self.recorder = Recorder(video_source, options, overlay, self._on_record_finished)
            self.recorder.start()
        except Exception as e:  # noqa: BLE001
            logger.exception("Não foi possível iniciar a gravação")
            self.recorder = None
            self.notify_user(f"Não foi possível iniciar a gravação: {e}")
            self._cleanup_recording()
            return

        if self.input_monitor is not None:
            self.input_monitor.start()
        self._set_record_state(RECORDING)
        logger.info("Gravando em %s", self.recorder.path)
        self._timer = GLib.timeout_add(500, self._tick)
        self._update_record_ui()
        if config.get("minimize_on_record") and self.main_window is not None:
            self.main_window.minimize()

    def stop_recording(self):
        if self.record_state != RECORDING or self.recorder is None:
            return
        logger.info("Parando gravação após %.1f s", self.recorder.elapsed())
        self._set_record_state(STOPPING)
        self._update_record_ui()
        self.recorder.stop()

    def _on_record_finished(self, path, error):
        duration = self.recorder.elapsed() if self.recorder is not None else 0
        self.recorder = None
        self._cleanup_recording()
        if error:
            logger.error("Gravação encerrada com erro: %s", error)
            self.notify_user(f"Gravação encerrada com erro: {error}")
        path = Path(path)
        if not (path.exists() and path.stat().st_size > 0):
            logger.warning("Nenhum vídeo foi gerado em %s", path)
            self._present_main_window()
            return
        logger.info("Gravação pronta (%.1f MB, %.1f s)", path.stat().st_size / 1e6, duration)
        initial = ""
        if config.get("video_auto_name"):
            target = naming.auto_path("video", config.get("video_dir"), path.suffix, duration)
            if self._save_video(path, target):
                return
            initial = target.stem  # não deu para renomear: pede o nome para não perder o vídeo
        self.hold()  # mantém o app vivo até o usuário nomear ou descartar
        self._pending_video = path
        self._set_record_state(NAMING)  # bloqueia nova gravação até nomear ou descartar
        self._update_record_ui()
        self._ask_video_name(path, initial)

    def _save_video(self, temp_path, target):
        """Move o vídeo temporário para o nome final. Devolve False se não conseguir."""
        try:
            os.replace(temp_path, target)
        except OSError as e:
            logger.error("Não foi possível renomear %s para %s: %s", temp_path, target, e)
            self.notify_user(f"Erro ao salvar o vídeo: {e.strerror}")
            return False
        logger.info("Vídeo salvo: %s", target)
        self.notify_user(f"Vídeo salvo: {target.name}", "Abrir", "app.open-file", GLib.Variant("s", str(target)))
        return True

    def _finish_naming(self):
        self._pending_video = None
        self._name_prompt = None
        self._set_record_state(IDLE)
        self._update_record_ui()
        self.release()

    def _raise_name_prompt(self):
        """Traz o diálogo pendente para frente recriando-o (janela nova aparece no topo)."""
        prompt = self._name_prompt
        if prompt is None or self._pending_video is None:
            return
        prompt.close_silently()
        if prompt.kind == "discard":
            self._confirm_discard(self._pending_video)
        else:
            self._ask_video_name(self._pending_video, prompt.text())

    def _present_main_window(self):
        win = self._ensure_main_window()
        win.present()
        return win

    def _ask_video_name(self, temp_path, initial=""):
        """O nome é obrigatório; cancelar oferece descartar a gravação.

        O diálogo abre numa janela própria (sem pai), para aparecer sobre os outros apps."""

        def on_named(target):
            self._name_prompt = None
            if target is None:
                self._confirm_discard(temp_path)
                return
            if not self._save_video(temp_path, target):
                self._ask_video_name(temp_path, target.stem)
                return
            self._finish_naming()

        self._name_prompt = ask_filename(None, "Nome do vídeo", config.get("video_dir"), temp_path.suffix,
                                         on_named, initial=initial)

    def _confirm_discard(self, temp_path):
        dialog = Adw.AlertDialog(heading="Descartar gravação?",
                                 body="Sem um nome, o vídeo não será salvo.")
        dialog.add_response("discard", "Descartar")
        dialog.add_response("back", "Voltar")
        dialog.set_response_appearance("discard", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("back")
        dialog.set_close_response("back")

        def on_response(_d, response):
            if state["silent"]:
                return
            self._name_prompt = None
            if response == "discard":
                try:
                    temp_path.unlink()
                    logger.info("Gravação descartada: %s", temp_path)
                except OSError as e:
                    logger.error("Não foi possível apagar %s: %s", temp_path, e)
                self.notify_user("Gravação descartada")
                self._finish_naming()
            else:
                self._ask_video_name(temp_path)

        state = {"silent": False}
        dialog.connect("response", on_response)
        dialog.present(None)  # janela própria, sobre os outros apps
        self._name_prompt = FilenamePrompt(dialog, None, state, kind="discard")

    def _cleanup_recording(self):
        if self.key_overlay is not None:
            model = self.key_overlay.model
            logger.info("Teclas/cliques: %d eventos lidos, %d etiquetas criadas, %d quadros com etiquetas",
                        model.events, model.badges_created, self.key_overlay.frames_drawn)
            if model.events and not self.key_overlay.frames_drawn:
                logger.warning("Eventos foram lidos mas nenhuma etiqueta foi desenhada no vídeo")
            self.key_overlay = None
        if self.input_monitor is not None:
            self.input_monitor.stop()
            self.input_monitor = None
        if self.cast is not None:
            self.cast.close()
            self.cast = None
        if self._timer:
            GLib.source_remove(self._timer)
            self._timer = 0
        was_active = self.record_state != IDLE
        self._set_record_state(IDLE)
        self._update_record_ui()
        if was_active:
            self.release()

    def _tick(self):
        self._update_record_ui()
        return True

    def _update_record_ui(self):
        elapsed = self.recorder.elapsed() if self.recorder else 0
        if self.main_window is not None:
            self.main_window.update_record_state(self.record_state, elapsed)
        if self.tray is not None:
            label, enabled = {
                IDLE: ("Gravar tela inteira", True),
                STARTING: ("Escolha a tela…", False),
                RECORDING: (f"Parar gravação  •  {fmt_time(elapsed)}", True),
                STOPPING: ("Finalizando…", False),
                NAMING: ("Nomear vídeo anterior…", True),
            }[self.record_state]
            self.tray.update_record_state(self.record_state == RECORDING, label, enabled)

    def set_tray(self, enabled):
        """Ícone na barra superior (StatusNotifierItem) ou na bandeja do Windows."""
        if IS_WINDOWS:
            from .win32.shell import Tray
        else:
            from .tray import Tray

        if enabled and self.tray is None:
            self.tray = Tray(self)
            self.tray.start()
            self._update_record_ui()
        elif not enabled and self.tray is not None:
            self.tray.stop()
            self.tray = None

    # --- diálogos --------------------------------------------------------
    def show_preferences(self):
        from .preferences import PreferencesDialog

        PreferencesDialog(self).present(self._ensure_main_window())

    def show_permissions(self, first_run=False):
        from .permissions_dialog import PermissionsDialog

        # o atalho (Ctrl+H) também chega na tela de captura e com a tela já aberta
        if IS_WINDOWS or self.capturing or self._permissions_dialog is not None:
            return
        win = self._present_main_window()

        def on_closed():
            self._permissions_dialog = None
            win.refresh_banner()

        self._permissions_dialog = PermissionsDialog(first_run, on_closed=on_closed)
        self._permissions_dialog.present(win)

    def show_about(self):
        about = Adw.AboutDialog(
            application_name=APP_NAME,
            application_icon=APP_ID,
            version=VERSION,
            comments="Prints com anotações e gravação de tela com teclas e cliques.",
            license_type=Gtk.License.GPL_3_0,
        )
        about.present(self._ensure_main_window())
