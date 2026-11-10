"""Janela de preferências."""

import shlex
import shutil
import sys
import unicodedata
from pathlib import Path

from gi.repository import Adw, Gdk, Gio, GLib, Gtk

from . import IS_WINDOWS, naming
from .config import DEFAULTS, config
from .record import framerate

POSITIONS = [
    ("bottom-center", "Embaixo, centro"), ("bottom-left", "Embaixo, esquerda"), ("bottom-right", "Embaixo, direita"),
    ("top-center", "Em cima, centro"), ("top-left", "Em cima, esquerda"), ("top-right", "Em cima, direita"),
]
FORMATS = [("auto", "Automático"), ("mp4", "MP4 (H.264)"), ("webm", "WebM (VP9)")]


def launch_command():
    """Comando para usar em atalhos de teclado do sistema."""
    exe = shutil.which("screen-toolbox")
    if exe:
        return "screen-toolbox"
    script = Path(__file__).resolve().parent.parent / "bin" / "screen-toolbox"
    if script.exists():
        return shlex.quote(str(script))
    return f"{shlex.quote(sys.executable)} -m screen_toolbox"


# (id, título, ícone)
TABS = [
    ("prints", "Prints", "camera-photo-symbolic"),
    ("record", "Gravação", "camera-video-symbolic"),
    ("keys", "Teclas e cliques", "input-keyboard-symbolic"),
    ("app", "Aplicativo", "preferences-system-symbolic"),
]


def normalize(text):
    """Minúsculas e sem acentos, para a busca não depender de como a pessoa digita."""
    decomposed = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()


def matches(query, text):
    """Todas as palavras da busca precisam aparecer em `text` (já normalizado), em qualquer ordem."""
    return all(word in text for word in normalize(query).split())


class PreferencesDialog(Adw.Dialog):
    """Todas as opções ficam numa página só: a aba e a busca apenas escolhem o que aparece."""

    def __init__(self, application):
        super().__init__(title="Preferências", content_width=640, content_height=680)
        self.application = application
        self._groups = []  # (aba, grupo, título original)
        self._rows = []  # (grupo, linha, texto de busca normalizado)
        self._tab_titles = {name: title for name, title, _icon in TABS}

        # Abas na barra de baixo. O ViewSwitcherBar exige um ViewStack, que aqui serve só de
        # modelo (páginas vazias): o conteúdo de verdade é a página única filtrada.
        self._tab_stack = Adw.ViewStack()
        for name, title, icon in TABS:
            self._tab_stack.add_titled_with_icon(Gtk.Box(), name, title, icon)
        self._tab_stack.connect("notify::visible-child-name", lambda *_: self._on_tab_changed())
        self.tabs = Adw.ViewSwitcherBar(stack=self._tab_stack, reveal=True)
        header = Adw.HeaderBar()

        self.search = Gtk.SearchEntry(placeholder_text="Buscar nas preferências…", hexpand=True)
        self.search.connect("search-changed", lambda *_: self._apply_filter())
        self.search.connect("stop-search", lambda *_: self.search.set_text(""))
        search_bar = Adw.Clamp(child=self.search, maximum_size=480, margin_start=12, margin_end=12, margin_bottom=6)

        self.page = Adw.PreferencesPage()
        self._build()
        empty = Adw.StatusPage(icon_name="edit-find-symbolic", title="Nenhuma opção encontrada",
                               description="Tente outras palavras.")
        self.stack = Gtk.Stack()
        self.stack.add_named(self.page, "page")
        self.stack.add_named(empty, "empty")
        self.toasts = Adw.ToastOverlay(child=self.stack)

        view = Adw.ToolbarView(content=self.toasts)
        view.add_top_bar(header)
        view.add_top_bar(search_bar)
        view.add_bottom_bar(self.tabs)
        self.set_child(view)

        shortcuts = Gtk.ShortcutController(scope=Gtk.ShortcutScope.MANAGED)
        shortcuts.add_shortcut(Gtk.Shortcut.new(Gtk.ShortcutTrigger.parse_string("<Control>f"),
                                                Gtk.CallbackAction.new(lambda *_: self.search.grab_focus() or True)))
        self.add_controller(shortcuts)
        self.set_focus(self.search)
        self._apply_filter()

    # --- montagem --------------------------------------------------------
    def _build(self):
        application = self.application

        # --- Prints ---
        files = self._group("prints", "Arquivo")
        self._add(files, self._folder_row("screenshot_dir", "Pasta dos prints"),
                  "diretório local salvar onde captura screenshot imagem")
        self._add(files, self._auto_name_row("screenshot", ".png"),
                  "arquivo padrão contador data hora renomear perguntar captura screenshot")
        capture = self._group("prints", "Ao capturar")
        self._add(capture, self._switch("copy_on_save", "Copiar ao salvar",
                                        "Também coloca a imagem na área de transferência"), "clipboard colar")
        self._add(capture, self._spin("screenshot_delay", "Atraso antes do print (s)", 0, 10, 1),
                  "timer temporizador espera segundos demora")

        # --- Gravação ---
        files = self._group("record", "Arquivo")
        self._add(files, self._folder_row("video_dir", "Pasta dos vídeos"),
                  "diretório local salvar onde video screencast")
        self._add(files, self._auto_name_row("video", ".mp4"),
                  "arquivo padrão contador data hora duração renomear perguntar video")
        self._add(files, self._combo("video_format", "Formato", FORMATS), "mp4 webm h264 vp9 codec extensão")
        video = self._group("record", "Vídeo")
        self._fps = self._fps_row()
        self._add(video, self._fps, "fps taxa framerate hz 30 60 90 120 fluidez")
        self._add(video, self._switch("record_cursor", "Mostrar o cursor"), "mouse ponteiro seta")
        if IS_WINDOWS:
            self._add(video, self._monitor_row(), "monitor display qual tela")
        else:
            remember = self._switch("remember_source", "Lembrar a tela escolhida",
                                    "Não pergunta qual tela gravar nas próximas vezes")
            forget = Gtk.Button(label="Esquecer", valign=Gtk.Align.CENTER,
                                tooltip_text="Perguntar novamente na próxima gravação")
            forget.connect("clicked", lambda *_: (config.set("restore_token", ""),
                                                  self._toast("A tela será perguntada novamente")))
            remember.add_suffix(forget)
            self._add(video, remember, "monitor display esquecer perguntar compartilhar")
        audio = self._group("record", "Áudio", "Ambos desligados por padrão")
        self._add(audio, self._switch("record_mic", "Microfone"), "mic voz som entrada narração")
        self._add(audio, self._switch("record_system_audio", "Áudio do sistema"),
                  "som alto-falante saída música desktop")

        # --- Teclas e cliques ---
        show = self._group("keys", "Mostrar no vídeo")
        self._add(show, self._switch("show_keys", "Mostrar teclas"), "teclado atalhos digitado keys")
        self._add(show, self._switch("show_clicks", "Mostrar cliques e rolagem"), "mouse scroll botão clicks")
        look = self._group("keys", "Aparência")
        self._add(look, self._combo("overlay_position", "Posição", POSITIONS), "canto lugar onde embaixo em cima")
        self._add(look, self._spin("overlay_scale", "Tamanho", 0.5, 3.0, 0.25, digits=2), "escala zoom grande pequeno")
        self._add(look, self._spin("overlay_duration", "Tempo na tela (s)", 0.5, 6.0, 0.5, digits=1),
                  "duração segundos sumir desaparecer")

        # --- Aplicativo ---
        behavior = self._group("app", "Comportamento")
        background = self._switch("run_in_background", "Continuar em segundo plano ao fechar",
                                  "Fechar a janela não encerra o app; use “Sair” no menu para encerrar")
        background.connect("notify::active", lambda r, _p: application.set_background(r.get_active()))
        self._add(behavior, background, "background fundo encerrar minimizar")
        if not IS_WINDOWS:  # no Windows o ícone na bandeja fica sempre ativo
            tray = self._switch("show_tray", "Ícone na barra superior",
                                "Acesso rápido a print, gravação e sair (no GNOME requer a extensão AppIndicator)")
            tray.connect("notify::active", lambda r, _p: application.set_tray(r.get_active()))
            self._add(behavior, tray, "bandeja tray indicador systray painel")
        self._add(behavior, self._switch("minimize_on_record", "Minimizar ao gravar",
                                         "Esconde a janela do app quando a gravação começa"), "esconder janela")
        if IS_WINDOWS:
            self._windows_shortcuts()
        else:
            self._command_shortcuts()
            permissions = self._group("app", "Permissões")
            self._add(permissions, self._permissions_row(), "acesso input portal liberar setup configuração inicial")

    def _group(self, tab, title, description=None):
        group = Adw.PreferencesGroup(title=title)
        if description:
            group.set_description(description)
        self.page.add(group)
        self._groups.append((tab, group, title))
        return group

    def _add(self, group, row, keywords=""):
        """Põe a linha no grupo e a registra na busca; `keywords` são sinônimos que não aparecem."""
        group.add(row)
        tab, title = next((t, name) for t, g, name in self._groups if g is group)
        subtitle = row.get_subtitle() if isinstance(row, (Adw.ActionRow, Adw.ExpanderRow)) else ""
        self._rows.append((group, row, normalize(" ".join(
            (row.get_title(), subtitle or "", title, self._tab_titles[tab], keywords)))))

    def _windows_shortcuts(self):
        from .win32.shell import HOTKEY_LABELS

        group = self._group("app", "Atalhos globais", "Funcionam em qualquer programa enquanto o Screen Toolbox "
                                                      "estiver aberto (inclusive na bandeja).")
        for title, keys in HOTKEY_LABELS:
            row = Adw.ActionRow(title=title)
            row.add_suffix(Gtk.ShortcutLabel(accelerator=keys.replace("Ctrl+", "<Ctrl>").replace("Alt+", "<Alt>"),
                                             valign=Gtk.Align.CENTER))
            self._add(group, row, "teclado hotkey " + keys)

    def _command_shortcuts(self):
        group = self._group("app", "Atalhos globais",
                            "Crie atalhos personalizados nas configurações de teclado do seu sistema "
                            "(GNOME, KDE, Hyprland, Sway…) usando estes comandos:")
        cmd = launch_command()
        for title, arg in (("Capturar área", "--screenshot"),
                           ("Iniciar/parar gravação", "--record"), ("Parar gravação", "--stop")):
            self._add(group, self._command_row(title, f"{cmd} {arg}"), "teclado hotkey comando print")

    def _permissions_row(self):
        row = Adw.ActionRow(title="Permissões do sistema", activatable=True,
                            subtitle="Captura de tela, teclas e cliques, gravação")
        row.add_suffix(Gtk.ShortcutLabel(accelerator="<Control>h", valign=Gtk.Align.CENTER))
        row.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))

        def open_permissions(*_):
            self.close()
            self.application.activate_action("permissions")

        row.connect("activated", open_permissions)
        return row

    # --- abas e busca ----------------------------------------------------
    def _on_tab_changed(self):
        if not self.search.get_text().strip():
            self._apply_filter()
            self.page.scroll_to_top()

    def _apply_filter(self):
        query = self.search.get_text().strip()
        tab = self._tab_stack.get_visible_child_name()
        self.tabs.set_sensitive(not query)
        shown = set()
        for group, row, text in self._rows:
            visible = matches(query, text)
            row.set_visible(visible)
            if visible:
                shown.add(group)
        for group_tab, group, title in self._groups:
            if query:
                group.set_title(f"{self._tab_titles[group_tab]} › {title}")
                group.set_visible(group in shown)
            else:
                group.set_title(title)
                group.set_visible(group_tab == tab)
        self.stack.set_visible_child_name("page" if shown or not query else "empty")

    # --- linhas ----------------------------------------------------------
    def _toast(self, text):
        self.toasts.add_toast(Adw.Toast(title=text, timeout=3))

    def _switch(self, key, title, subtitle=None):
        row = Adw.SwitchRow(title=title)
        if subtitle:
            row.set_subtitle(subtitle)
        row.set_active(bool(config.get(key)))
        row.connect("notify::active", lambda r, _p: config.set(key, r.get_active()))
        return row

    def _spin(self, key, title, lo, hi, step, digits=0):
        row = Adw.SpinRow.new_with_range(lo, hi, step)
        row.set_title(title)
        row.set_digits(digits)
        row.set_value(config.get(key))
        cast = float if digits else int
        row.connect("notify::value", lambda r, _p: config.set(key, cast(r.get_value())))
        return row

    def _combo(self, key, title, options):
        row = Adw.ComboRow(title=title, model=Gtk.StringList.new([label for _v, label in options]))
        values = [v for v, _l in options]
        current = config.get(key)
        row.set_selected(values.index(current) if current in values else 0)
        row.connect("notify::selected", lambda r, _p: config.set(key, values[r.get_selected()]))
        return row

    def _auto_name_row(self, kind, extension):
        """Liga/desliga o nome automático e edita o padrão, com botões de campo e prévia."""
        enable_key, pattern_key = f"{kind}_auto_name", f"{kind}_name_pattern"
        row = Adw.ExpanderRow(title="Nome automático", show_enable_switch=True)
        row.set_enable_expansion(bool(config.get(enable_key)))
        entry = Adw.EntryRow(title="Padrão do nome", text=config.get(pattern_key))
        reset = Gtk.Button(icon_name="edit-undo-symbolic", valign=Gtk.Align.CENTER,
                           tooltip_text="Restaurar padrão")
        reset.add_css_class("flat")
        entry.add_suffix(reset)

        def refresh(*_):
            example = naming.preview(kind, entry.get_text(), extension)
            if example:
                entry.remove_css_class("error")
                config.set(pattern_key, entry.get_text())
            else:
                entry.add_css_class("error")
                example = naming.preview(kind, config.get(pattern_key), extension)
            row.set_subtitle(example if row.get_enable_expansion() else "Pergunta o nome ao salvar")

        def on_enabled(*_):
            config.set(enable_key, row.get_enable_expansion())
            refresh()

        def insert(_button, field):
            position = entry.get_position()
            end = entry.insert_text(field, position)  # o PyGObject devolve a nova posição
            entry.grab_focus_without_selecting()
            entry.set_position(end)

        fields = Adw.WrapBox(child_spacing=6, line_spacing=6, margin_top=10, margin_bottom=10,
                             margin_start=12, margin_end=12)
        for name, text in naming.fields_for(kind):
            button = Gtk.Button(label=f"{{{name}}}", tooltip_text=text)
            button.add_css_class("pill")
            button.connect("clicked", insert, f"{{{name}}}")
            fields.append(button)

        entry.connect("changed", refresh)
        reset.connect("clicked", lambda *_: entry.set_text(DEFAULTS[pattern_key]))
        row.connect("notify::enable-expansion", on_enabled)
        row.add_row(entry)
        row.add_row(Adw.PreferencesRow(child=fields, activatable=False, focusable=False))
        refresh()
        return row

    def _screen_refresh(self):
        """Taxa (Hz) que limita os quadros por segundo: a da tela configurada no Windows; no Linux
        a tela só é escolhida ao gravar, então vale a maior entre os monitores (o limite exato é
        aplicado em app._record_fps)."""
        display = Gdk.Display.get_default()
        if IS_WINDOWS:
            from .win32.screenshot import monitors

            return framerate.refresh_of_index(display, monitors(), config.get("record_monitor"))
        return framerate.max_refresh(display)

    def _fps_row(self):
        row = Adw.ComboRow(title="Quadros por segundo")
        state = {"values": [], "loading": False}

        def load(*_):
            refresh = self._screen_refresh()
            state["values"] = framerate.allowed(refresh)
            current = framerate.clamp(int(config.get("fps")), refresh)
            config.set("fps", current)
            state["loading"] = True
            row.set_model(Gtk.StringList.new([str(v) for v in state["values"]]))
            row.set_selected(state["values"].index(current))
            state["loading"] = False
            limit = f"até {round(refresh)} Hz" if refresh > 0 else "taxa desconhecida"
            row.set_subtitle(f"Limitado pela taxa de atualização da tela ({limit})")

        def on_selected(*_):
            if not state["loading"] and row.get_selected() < len(state["values"]):
                config.set("fps", state["values"][row.get_selected()])

        row.connect("notify::selected", on_selected)
        row.reload = load
        load()
        return row

    def _monitor_row(self):
        from .win32.screenshot import monitors

        options = []
        for i, m in enumerate(monitors()):
            name = "Principal" if m["primary"] else f"Monitor {i + 1}"
            options.append((i, f"{name} ({m['width']}×{m['height']})"))
        row = self._combo("record_monitor", "Tela a gravar", options or [(0, "Principal")])
        row.connect("notify::selected", lambda *_: self._fps.reload())  # o limite de fps é por tela
        return row

    def _folder_row(self, key, title):
        row = Adw.ActionRow(title=title, subtitle=config.get(key))
        button = Gtk.Button(icon_name="folder-open-symbolic", valign=Gtk.Align.CENTER, tooltip_text="Escolher pasta")
        button.add_css_class("flat")

        def pick(*_):
            dialog = Gtk.FileDialog(title=title)
            folder = Path(config.get(key))
            if folder.is_dir():
                dialog.set_initial_folder(Gio.File.new_for_path(str(folder)))

            def done(dlg, res):
                try:
                    file = dlg.select_folder_finish(res)
                except GLib.Error:
                    return
                config.set(key, file.get_path())
                row.set_subtitle(file.get_path())

            dialog.select_folder(self.get_root() if isinstance(self.get_root(), Gtk.Window) else None, None, done)

        button.connect("clicked", pick)
        row.add_suffix(button)
        row.set_activatable_widget(button)
        return row

    def _command_row(self, title, command):
        row = Adw.ActionRow(title=title, subtitle=command, subtitle_selectable=True)
        button = Gtk.Button(icon_name="edit-copy-symbolic", valign=Gtk.Align.CENTER, tooltip_text="Copiar comando")
        button.add_css_class("flat")

        def copy(*_):
            Gdk.Display.get_default().get_clipboard().set(command)
            self._toast("Comando copiado")

        button.connect("clicked", copy)
        row.add_suffix(button)
        return row
