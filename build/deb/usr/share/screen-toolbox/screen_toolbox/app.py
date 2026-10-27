"""Aplicação principal: ações, linha de comando, fluxo de print e de gravação."""

import os
import platform
from pathlib import Path

from gi.repository import Adw, Gdk, Gio, GLib, Gtk

from . import APP_ID, APP_NAME, VERSION, log
from .capture.region import monitor_crop
from .capture.screenshot import take_screenshot
from .config import config
from .editor.window import CaptureWindow
from .main_window import IDLE, RECORDING, STARTING, STOPPING, MainWindow, fmt_time
from .name_dialog import ask_filename

logger = log.get(__name__)

STATE_NAMES = {IDLE: "parado", STARTING: "iniciando", RECORDING: "gravando", STOPPING: "finalizando"}


def _code_stamp():
    """Data de modificação mais recente dos arquivos .py do app."""
    root = Path(__file__).resolve().parent
    return max((p.stat().st_mtime for p in root.rglob("*.py")), default=0)


class ScreenToolboxApp(Adw.Application):
    def __init__(self, dev=False):
        # no modo dev usa outro ID, para não ser redirecionado para uma instância instalada aberta
        app_id = f"{APP_ID}.Devel" if dev else APP_ID
        super().__init__(application_id=app_id, flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.dev = dev
        self.main_window = None
        self.capturing = False
        self.record_state = IDLE
        self.cast = None
        self.recorder = None
        self.input_monitor = None
        self.key_overlay = None
        self._timer = 0
        self._clipboard_hold = None
        self._background_hold = False
        self.tray = None
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
        self.set_background(config.get("run_in_background"))
        self.set_tray(config.get("show_tray"))

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

        from .portal import get_portal
        from .record.input_events import readable_devices

        if not Gst.is_initialized():
            Gst.init(None)
        logger.info("%s %s (app id %s)%s", APP_NAME, VERSION, self.get_application_id(),
                    " [modo dev]" if self.dev else "")
        logger.info("Python %s | GTK %d.%d.%d | libadwaita %d.%d.%d | %s",
                    platform.python_version(),
                    Gtk.get_major_version(), Gtk.get_minor_version(), Gtk.get_micro_version(),
                    Adw.get_major_version(), Adw.get_minor_version(), Adw.get_micro_version(),
                    Gst.version_string())
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
        logger.debug("Configuração: %s", {k: v for k, v in config.items() if k != "restore_token"})
        orphans = sorted(Path(config.get("video_dir")).glob(".screen-toolbox-*.part.*"))
        if orphans:
            logger.warning("Gravações não nomeadas de sessões anteriores (renomeie para recuperar): %s",
                           ", ".join(str(p) for p in orphans))

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
        else:
            self.activate()
        return 0

    def _should_restart(self):
        return (self._code_stamp != _code_stamp() and self.record_state == IDLE
                and not self.capturing and self._clipboard_hold is None)

    def do_activate(self):
        self._ensure_main_window().present()

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
            notification = Gio.Notification.new(APP_NAME)
            notification.set_body("Continua rodando em segundo plano. Para encerrar, use “Sair” no menu (Ctrl+Q).")
            self.send_notification("background", notification)

    def request_quit(self):
        if self.record_state != IDLE:
            logger.warning("Sair bloqueado: gravação em estado '%s'", STATE_NAMES[self.record_state])
            self._present_main_window()
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
        logger.debug("Notificação do sistema: %s", text)
        notification = Gio.Notification.new(APP_NAME)
        notification.set_body(text)
        if button and action:
            notification.add_button_with_target(button, action, target)
            notification.set_default_action_and_target(action, target)
        self.send_notification(None, notification)

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
                    self.notify_user("Sem permissão para capturar a tela. Permita o Screen Toolbox em "
                                     "Configurações → Apps → Screen Toolbox → Capturas de tela.")
                    self.capturing = False
                    self.release()
                    return
                logger.info("Permissão de captura concedida")
                win.set_visible(False)
                GLib.timeout_add(400, lambda: take_screenshot(on_shot) and False)

            GLib.timeout_add(600, lambda: take_screenshot(on_permission_shot) and False)

        def on_shot(surface, error):
            if surface is None:
                if error and not permission_attempted:
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
        else:
            logger.warning("Alternar gravação ignorado no estado '%s'", STATE_NAMES[self.record_state])

    def start_recording(self):
        from .record.screencast import ScreenCastSession

        if self.record_state != IDLE:
            return
        self._set_record_state(STARTING)
        self.hold()
        self._update_record_ui()
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

    def _on_cast_ready(self, fd, node_id, size):
        from .record.input_events import InputMonitor, KeystrokeModel, input_access_ok
        from .record.keymap import KeyLabeler
        from .record.overlay import KeyOverlay
        from .record.pipeline import Recorder

        logger.info("Tela compartilhada: nó PipeWire %s, tamanho %s", node_id, size)
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
        try:
            self.recorder = Recorder(fd, node_id, options, overlay, self._on_record_finished)
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
        logger.info("Gravação pronta (%.1f MB); pedindo o nome do arquivo", path.stat().st_size / 1e6)
        self.hold()  # mantém o app vivo até o usuário nomear ou descartar
        self._ask_video_name(path)

    def _present_main_window(self):
        win = self._ensure_main_window()
        win.present()
        return win

    def _ask_video_name(self, temp_path):
        """O nome é obrigatório; cancelar oferece descartar a gravação."""
        win = self._present_main_window()

        def on_named(target):
            if target is None:
                self._confirm_discard(temp_path)
                return
            try:
                os.replace(temp_path, target)
            except OSError as e:
                logger.error("Não foi possível renomear %s para %s: %s", temp_path, target, e)
                self.notify_user(f"Erro ao salvar o vídeo: {e.strerror}")
                self._ask_video_name(temp_path)
                return
            logger.info("Vídeo salvo: %s", target)
            self.notify_user(f"Vídeo salvo: {target.name}", "Abrir", "app.open-file", GLib.Variant("s", str(target)))
            self.release()

        ask_filename(win, "Nome do vídeo", config.get("video_dir"), temp_path.suffix, on_named)

    def _confirm_discard(self, temp_path):
        dialog = Adw.AlertDialog(heading="Descartar gravação?",
                                 body="Sem um nome, o vídeo não será salvo.")
        dialog.add_response("discard", "Descartar")
        dialog.add_response("back", "Voltar")
        dialog.set_response_appearance("discard", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("back")
        dialog.set_close_response("back")

        def on_response(_d, response):
            if response == "discard":
                try:
                    temp_path.unlink()
                    logger.info("Gravação descartada: %s", temp_path)
                except OSError as e:
                    logger.error("Não foi possível apagar %s: %s", temp_path, e)
                self.notify_user("Gravação descartada")
                self.release()
            else:
                self._ask_video_name(temp_path)

        dialog.connect("response", on_response)
        dialog.present(self._present_main_window())

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
            }[self.record_state]
            self.tray.update_record_state(self.record_state == RECORDING, label, enabled)

    def set_tray(self, enabled):
        """Ícone na barra superior (StatusNotifierItem)."""
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

    def show_about(self):
        about = Adw.AboutDialog(
            application_name=APP_NAME,
            application_icon=APP_ID,
            version=VERSION,
            comments="Prints com anotações e gravação de tela com teclas e cliques.",
            license_type=Gtk.License.GPL_3_0,
        )
        about.present(self._ensure_main_window())
