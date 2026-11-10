"""Tela de permissões: configuração inicial (primeira execução) e situação atual (menu)."""

from gi.repository import Adw, Gdk, Gtk

from . import APP_NAME, log, permissions
from .capture.screenshot import take_screenshot
from .config import config
from .permissions import DENIED, GRANTED, NEEDS_RELOGIN, NOT_ASKED, UNKNOWN

logger = log.get(__name__)

OK_ICON, WARNING_ICON, INFO_ICON = "emblem-ok-symbolic", "dialog-warning-symbolic", "dialog-information-symbolic"


class PermissionsDialog(Adw.Dialog):
    def __init__(self, first_run=False, on_closed=None):
        super().__init__(title="Configuração inicial" if first_run else "Permissões",
                         content_width=520, content_height=560)
        self._busy = False

        page = Adw.PreferencesPage()
        intro = (f"Boas-vindas ao {APP_NAME}! Libere abaixo o que o app precisa para funcionar. "
                 "Dá para rever isto depois em Menu → Permissões (Ctrl+H)."
                 if first_run else "Situação das permissões do sistema usadas pelo app.")
        group = Adw.PreferencesGroup(description=intro)

        self.screenshot_row, self.screenshot_icon, self.screenshot_btn = self._row(
            "Captura de tela", self._on_screenshot_clicked)
        self.input_row, self.input_icon, self.input_btn = self._row(
            "Teclas e cliques no vídeo (opcional)", self._on_input_clicked)
        self.copy_btn = Gtk.Button(icon_name="edit-copy-symbolic", valign=Gtk.Align.CENTER, visible=False,
                                   css_classes=["flat"], tooltip_text="Copiar o comando")
        self.copy_btn.connect("clicked", self._on_copy_clicked)
        self.input_row.add_suffix(self.copy_btn)
        self.cast_row, self.cast_icon, self.cast_btn = self._row("Gravação de tela", self._on_forget_clicked)
        self.cast_btn.set_label("Esquecer")
        self.cast_btn.set_tooltip_text("Perguntar qual tela gravar na próxima gravação")
        for row in (self.screenshot_row, self.input_row, self.cast_row):
            group.add(row)
        page.add(group)

        actions = Adw.PreferencesGroup()
        box = Gtk.Box(spacing=12, halign=Gtk.Align.CENTER)
        refresh = Gtk.Button(label="Verificar de novo", css_classes=["pill"])
        refresh.connect("clicked", lambda *_: self.refresh())
        box.append(refresh)
        if first_run:
            done = Gtk.Button(label="Concluir", css_classes=["pill", "suggested-action"])
            done.connect("clicked", lambda *_: self.close())
            box.append(done)
        actions.add(box)
        page.add(actions)

        self.toasts = Adw.ToastOverlay(child=page)
        view = Adw.ToolbarView(content=self.toasts)
        view.add_top_bar(Adw.HeaderBar())
        self.set_child(view)

        if on_closed:
            self.connect("closed", lambda *_: on_closed())
        # o usuário pode ter mexido nas permissões por fora: reconsulta ao voltar para a tela
        self.connect("map", lambda *_: self.refresh())
        self.refresh()

    @staticmethod
    def _row(title, on_clicked):
        row = Adw.ActionRow(title=title, subtitle_lines=0)
        icon = Gtk.Image()
        row.add_prefix(icon)
        button = Gtk.Button(valign=Gtk.Align.CENTER, visible=False)
        button.connect("clicked", on_clicked)
        row.add_suffix(button)
        return row, icon, button

    @staticmethod
    def _set_icon(icon, name):
        icon.set_from_icon_name(name)
        for css, icon_name in (("success", OK_ICON), ("warning", WARNING_ICON)):
            if name == icon_name:
                icon.add_css_class(css)
            else:
                icon.remove_css_class(css)

    def _toast(self, text):
        self.toasts.add_toast(Adw.Toast(title=text, timeout=4))

    # --- estado ----------------------------------------------------------
    def refresh(self):
        self._refresh_screenshot()
        self._refresh_input()
        self._refresh_cast()

    def _refresh_screenshot(self):
        self.screenshot_status = status = permissions.screenshot_status()
        subtitle, label = {
            GRANTED: ("Permitida: os prints saem sem perguntar.", None),
            NOT_ASKED: ("Ainda não solicitada. O sistema vai perguntar se o app pode tirar prints.", "Permitir"),
            DENIED: ("Negada: o sistema está recusando os prints do app.", "Pedir de novo"),
            UNKNOWN: ("Não foi possível consultar. Use “Testar” para tentar um print.", "Testar"),
        }[status]
        self.screenshot_row.set_subtitle(subtitle)
        self._set_icon(self.screenshot_icon, OK_ICON if status == GRANTED else
                       INFO_ICON if status == UNKNOWN else WARNING_ICON)
        self.screenshot_btn.set_visible(label is not None)
        self.screenshot_btn.set_label(label or "")
        self.screenshot_btn.set_sensitive(not self._busy)
        if status in (NOT_ASKED, DENIED):
            self.screenshot_btn.add_css_class("suggested-action")
        else:
            self.screenshot_btn.remove_css_class("suggested-action")

    def _refresh_input(self, show_command=False):
        self.input_status = status = permissions.input_status()
        subtitle = {
            GRANTED: "Permitida: o app lê teclado e mouse somente durante a gravação.",
            NEEDS_RELOGIN: "Seu usuário já está no grupo “input”. Saia e entre na sessão para valer.",
            DENIED: "Sem acesso. É preciso adicionar seu usuário ao grupo “input” (pede a senha) "
                    "e depois sair e entrar na sessão.",
        }[status]
        if show_command and status == DENIED:
            subtitle = f"Rode no terminal e depois saia e entre na sessão:\n{permissions.input_group_command()}"
        self.input_row.set_subtitle(subtitle)
        self._set_icon(self.input_icon, OK_ICON if status == GRANTED else WARNING_ICON)
        self.input_btn.set_label("Permitir")
        self.input_btn.set_visible(status == DENIED)
        self.input_btn.set_sensitive(not self._busy)
        self.copy_btn.set_visible(show_command and status == DENIED)

    def _refresh_cast(self):
        available, remembered = permissions.screencast_status()
        if not available:
            subtitle = "O portal de gravação de tela não está disponível neste sistema."
        elif remembered:
            subtitle = "Tela lembrada: a gravação começa sem perguntar."
        else:
            subtitle = "O sistema pergunta qual tela compartilhar ao iniciar a gravação."
        self.cast_row.set_subtitle(subtitle)
        self._set_icon(self.cast_icon, OK_ICON if available else WARNING_ICON)
        self.cast_btn.set_visible(available and remembered)

    def _set_busy(self, busy):
        self._busy = busy
        self.screenshot_btn.set_sensitive(not busy)
        self.input_btn.set_sensitive(not busy)

    # --- ações -----------------------------------------------------------
    def _on_screenshot_clicked(self, _button):
        if self.screenshot_status == DENIED and not permissions.reset_screenshot():
            self._toast("Não foi possível redefinir a permissão")
            return
        self._set_busy(True)
        logger.info("Pedindo a permissão de print (tela de permissões)")

        def on_shot(surface, error):
            # o pedido precisa do app em foco; a imagem em si não interessa
            self._set_busy(False)
            self.refresh()
            if surface is not None:
                self._toast("Captura de tela permitida")
            else:
                logger.warning("Permissão de print não concedida: %s", error or "cancelado")
                self._toast("A captura de tela não foi permitida")

        take_screenshot(on_shot)

    def _on_input_clicked(self, _button):
        self._set_busy(True)

        def done(error):
            self._set_busy(False)
            if error is None:
                self._refresh_input()
                self._toast("Pronto. Saia e entre na sessão para valer")
            elif error == "":
                self._refresh_input()
            else:
                logger.warning("Não foi possível adicionar ao grupo input: %s", error)
                self._refresh_input(show_command=True)
                self._toast(error)

        permissions.add_to_input_group(done)

    def _on_copy_clicked(self, _button):
        Gdk.Display.get_default().get_clipboard().set(permissions.input_group_command())
        self._toast("Comando copiado")

    def _on_forget_clicked(self, _button):
        config.set("restore_token", "")
        self._refresh_cast()
        self._toast("A tela será perguntada novamente")
