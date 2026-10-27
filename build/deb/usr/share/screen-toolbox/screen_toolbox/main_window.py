"""Janela principal: atalhos para print e gravação, com opções rápidas."""

from gi.repository import Adw, Gio, Gtk

from . import APP_NAME
from .config import config

IDLE, STARTING, RECORDING, STOPPING = range(4)


def fmt_time(seconds):
    seconds = int(seconds)
    return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}" if seconds >= 3600 \
        else f"{seconds // 60:02d}:{seconds % 60:02d}"


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, application):
        super().__init__(application=application, title=APP_NAME, default_width=440, default_height=600)

        header = Adw.HeaderBar()
        menu = Gio.Menu()
        menu.append("Preferências", "app.preferences")
        menu.append("Sobre o Screen Toolbox", "app.about")
        menu.append("Sair", "app.quit")
        header.pack_end(Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu, tooltip_text="Menu"))

        self.toasts = Adw.ToastOverlay()
        page = Adw.PreferencesPage()

        # --- print ---
        shot_group = Adw.PreferencesGroup(title="Captura de tela")
        region_btn = self._big_button("Capturar área", "selection-mode-symbolic", "app.screenshot", "suggested-action")
        region_btn.set_tooltip_text("Selecionar uma área da tela (Ctrl+1)")
        region_btn.set_margin_bottom(6)
        shot_group.add(region_btn)
        page.add(shot_group)

        # --- gravação ---
        rec_group = Adw.PreferencesGroup(title="Gravação de tela")
        self.record_btn = self._big_button("Gravar tela", "media-record-symbolic", "app.record", "destructive-action")
        self.record_btn.set_tooltip_text("Gravar a tela inteira; clique de novo para parar (Ctrl+2)")
        self.record_label = self.record_btn.get_child().get_last_child()
        rec_group.add(self.record_btn)

        self.status = Gtk.Label(css_classes=["dim-label", "caption"], margin_top=6, margin_bottom=6)
        rec_group.add(self.status)

        audio_group = Adw.PreferencesGroup(title="Áudio")
        audio_group.add(self._switch("record_mic", "Microfone", "Grava a entrada de áudio padrão"))
        audio_group.add(self._switch("record_system_audio", "Áudio do sistema", "Grava o som que sai dos alto-falantes"))

        overlay_group = Adw.PreferencesGroup(title="Mostrar no vídeo")
        overlay_group.add(self._switch("show_keys", "Teclas pressionadas", "Ex.: Ctrl + C, texto digitado"))
        overlay_group.add(self._switch("show_clicks", "Cliques e rolagem do mouse"))

        page.add(rec_group)
        page.add(audio_group)
        page.add(overlay_group)
        self.toasts.set_child(page)

        self.banner = Adw.Banner(
            title="Sem acesso ao teclado/mouse: teclas não aparecerão nos vídeos",
            button_label="Como resolver",
        )
        self.banner.connect("button-clicked", self._show_input_help)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        content.append(self.banner)
        content.append(self.toasts)
        self.toasts.set_vexpand(True)

        view = Adw.ToolbarView()
        view.add_top_bar(header)
        view.set_content(content)
        self.set_content(view)
        self.connect("close-request", self._on_close_request)

        self._refresh_banner()
        self.update_record_state(IDLE, 0)

    def _on_close_request(self, _win):
        if not config.get("run_in_background"):
            return False
        # só esconde: o app segue em segundo plano e a janela volta instantaneamente
        self.set_visible(False)
        self.get_application().enter_background()
        return True

    def _big_button(self, label, icon, action, css=None):
        btn = Gtk.Button(action_name=action, css_classes=["pill"])
        if css:
            btn.add_css_class(css)
        box = Gtk.Box(spacing=8, halign=Gtk.Align.CENTER)
        box.append(Gtk.Image(icon_name=icon))
        box.append(Gtk.Label(label=label))
        btn.set_child(box)
        return btn

    def _switch(self, key, title, subtitle=None):
        row = Adw.SwitchRow(title=title)
        if subtitle:
            row.set_subtitle(subtitle)
        row.set_active(bool(config.get(key)))
        row.connect("notify::active", lambda r, _p: (config.set(key, r.get_active()), self._refresh_banner()))
        return row

    def _refresh_banner(self):
        from .record.input_events import input_access_ok

        wants = config.get("show_keys") or config.get("show_clicks")
        self.banner.set_revealed(bool(wants) and not input_access_ok())

    def _show_input_help(self, *_):
        dialog = Adw.AlertDialog(
            heading="Permitir leitura de teclado e mouse",
            body=(
                "No Wayland, a única forma de ver as teclas durante a gravação é ler os "
                "dispositivos de entrada do sistema. Adicione seu usuário ao grupo “input” "
                "e reinicie a sessão:\n\n"
                "sudo usermod -aG input $USER\n\n"
                "A leitura só acontece enquanto uma gravação estiver ativa."
            ),
        )
        dialog.add_response("ok", "Entendi")
        dialog.present(self)

    def toast(self, text, button=None, action=None, target=None):
        toast = Adw.Toast(title=text, timeout=5)
        if button and action:
            toast.set_button_label(button)
            toast.set_action_name(action)
            if target is not None:
                toast.set_action_target_value(target)
        self.toasts.add_toast(toast)

    def update_record_state(self, state, elapsed):
        if state == IDLE:
            self.record_label.set_label("Gravar tela")
            self.record_btn.set_sensitive(True)
            self.status.set_label("Pronto para gravar")
        elif state == STARTING:
            self.record_label.set_label("Escolha a tela…")
            self.record_btn.set_sensitive(False)
            self.status.set_label("Aguardando a seleção da tela")
        elif state == RECORDING:
            self.record_label.set_label(f"Parar gravação  •  {fmt_time(elapsed)}")
            self.record_btn.set_sensitive(True)
            self.status.set_label("Gravando… (também dá para parar pelo indicador do sistema)")
        elif state == STOPPING:
            self.record_label.set_label("Finalizando…")
            self.record_btn.set_sensitive(False)
            self.status.set_label("Salvando o vídeo")
