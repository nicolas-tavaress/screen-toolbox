"""Janela de preferências."""

import shlex
import shutil
import sys
from pathlib import Path

from gi.repository import Adw, Gdk, Gio, GLib, Gtk

from .config import config

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


class PreferencesDialog(Adw.PreferencesDialog):
    def __init__(self, application):
        super().__init__(title="Preferências")
        self.application = application

        # --- Geral ---
        general = Adw.PreferencesPage(title="Geral", icon_name="preferences-system-symbolic")
        shots = Adw.PreferencesGroup(title="Prints")
        shots.add(self._folder_row("screenshot_dir", "Pasta dos prints"))
        shots.add(self._switch("copy_on_save", "Copiar ao salvar", "Também coloca a imagem na área de transferência"))
        shots.add(self._spin("screenshot_delay", "Atraso antes do print (s)", 0, 10, 1))
        general.add(shots)
        app_group = Adw.PreferencesGroup(title="Aplicativo")
        background = self._switch("run_in_background", "Continuar em segundo plano ao fechar",
                                  "Fechar a janela não encerra o app; use “Sair” no menu para encerrar")
        background.connect("notify::active", lambda r, _p: application.set_background(r.get_active()))
        app_group.add(background)
        tray = self._switch("show_tray", "Ícone na barra superior",
                            "Acesso rápido a print, gravação e sair (no GNOME requer a extensão AppIndicator)")
        tray.connect("notify::active", lambda r, _p: application.set_tray(r.get_active()))
        app_group.add(tray)
        general.add(app_group)
        self.add(general)

        # --- Vídeo ---
        video = Adw.PreferencesPage(title="Vídeo", icon_name="camera-video-symbolic")
        files = Adw.PreferencesGroup(title="Arquivo")
        files.add(self._folder_row("video_dir", "Pasta dos vídeos"))
        files.add(self._combo("video_format", "Formato", FORMATS))
        files.add(self._spin("fps", "Quadros por segundo", 10, 60, 5))
        video.add(files)

        capture = Adw.PreferencesGroup(title="Captura")
        capture.add(self._switch("record_cursor", "Mostrar o cursor"))
        capture.add(self._switch("minimize_on_record", "Minimizar ao gravar"))
        remember = self._switch("remember_source", "Lembrar a tela escolhida",
                                "Não pergunta qual tela gravar nas próximas vezes")
        forget = Gtk.Button(label="Esquecer", valign=Gtk.Align.CENTER, tooltip_text="Perguntar novamente na próxima gravação")
        forget.connect("clicked", lambda *_: (config.set("restore_token", ""), self._toast("A tela será perguntada novamente")))
        remember.add_suffix(forget)
        capture.add(remember)
        video.add(capture)
        audio = Adw.PreferencesGroup(title="Áudio", description="Ambos desligados por padrão")
        audio.add(self._switch("record_mic", "Microfone"))
        audio.add(self._switch("record_system_audio", "Áudio do sistema"))
        video.add(audio)
        self.add(video)

        # --- Teclas ---
        keys = Adw.PreferencesPage(title="Teclas", icon_name="input-keyboard-symbolic")
        show = Adw.PreferencesGroup(title="Exibição no vídeo")
        show.add(self._switch("show_keys", "Mostrar teclas"))
        show.add(self._switch("show_clicks", "Mostrar cliques e rolagem"))
        show.add(self._combo("overlay_position", "Posição", POSITIONS))
        show.add(self._spin("overlay_scale", "Tamanho", 0.5, 3.0, 0.25, digits=2))
        show.add(self._spin("overlay_duration", "Tempo na tela (s)", 0.5, 6.0, 0.5, digits=1))
        keys.add(show)
        self.add(keys)

        # --- Atalhos ---
        shortcuts = Adw.PreferencesPage(title="Atalhos", icon_name="preferences-desktop-keyboard-shortcuts-symbolic")
        group = Adw.PreferencesGroup(
            title="Atalhos globais",
            description=(
                "Crie atalhos personalizados nas configurações de teclado do seu sistema "
                "(GNOME, KDE, Hyprland, Sway…) usando estes comandos:"
            ),
        )
        cmd = launch_command()
        for title, arg in (("Capturar área", "--screenshot"),
                           ("Iniciar/parar gravação", "--record"), ("Parar gravação", "--stop")):
            group.add(self._command_row(title, f"{cmd} {arg}"))
        shortcuts.add(group)
        self.add(shortcuts)

    # --- linhas ----------------------------------------------------------
    def _toast(self, text):
        self.add_toast(Adw.Toast(title=text, timeout=3))

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
