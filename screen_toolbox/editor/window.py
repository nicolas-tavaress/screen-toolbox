"""Captura com edição no lugar (estilo Flameshot).

Uma janela em tela cheia por monitor, sobre o print congelado. O usuário seleciona a
área e edita ali mesmo; a barra de ferramentas acompanha a seleção. Copiar (Enter /
Ctrl+C) ou Salvar (Ctrl+S, pede o nome) encerram a captura; Esc cancela.
"""

from pathlib import Path

from gi.repository import Adw, Gdk, GLib, Gtk

from .. import log
from ..config import config
from ..name_dialog import ask_filename
from .canvas import Canvas
from .icons import tool_icon
from .tools import TOOLS

logger = log.get(__name__)

PALETTE = ["#e01b24", "#ff7800", "#f6d32d", "#33d17a", "#3584e4", "#9141ac", "#000000", "#ffffff"]
TOOLBAR_GAP = 8  # px entre a seleção e a barra

CSS = b"""
.capture-toolbar {
  background-color: alpha(@window_bg_color, 0.96);
  border-radius: 12px;
  padding: 6px;
  box-shadow: 0 2px 10px alpha(black, 0.45);
}
"""


def _rgba_tuple(rgba):
    return (rgba.red, rgba.green, rgba.blue, rgba.alpha)


def _parse_rgba(spec):
    rgba = Gdk.RGBA()
    rgba.parse(spec)
    return rgba


def _to_hex(rgba):
    return "#{:02x}{:02x}{:02x}".format(*(round(c * 255) for c in (rgba.red, rgba.green, rgba.blue)))


_css_loaded = False


def _load_css():
    global _css_loaded
    if _css_loaded:
        return
    provider = Gtk.CssProvider()
    provider.load_from_data(CSS)
    Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider,
                                              Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    _css_loaded = True


class CaptureWindow(Adw.ApplicationWindow):
    """on_done(resultado) com resultado em 'copied' | 'saved' | 'cancelled'."""

    def __init__(self, application, surface, monitor, on_done):
        super().__init__(application=application, title="Captura de tela")
        _load_css()
        self.on_done = on_done
        self.finished = False
        self.tool_buttons = {}
        self._toolbar_rect = None
        self._toolbar_side = "below"

        self.canvas = Canvas(surface)
        self.canvas.connect("changed", self._on_canvas_changed)
        self.canvas.connect("selection-dragging", self._on_selection_dragging)
        self.canvas.text_request_handler = self._ask_text
        color = _parse_rgba(config.get("editor_color"))
        self.canvas.color = _rgba_tuple(color)
        self.canvas.width = config.get("editor_width")

        self.toolbar = self._build_toolbar(color)
        self.toolbar.set_visible(False)

        overlay = Gtk.Overlay()
        overlay.set_child(self.canvas)
        overlay.add_overlay(self.toolbar)
        self.set_content(overlay)

        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._on_key)
        self.add_controller(keys)
        self.connect("close-request", self._on_close_request)

        self.tool_buttons["select"].set_active(True)
        self._update_history_buttons()
        if monitor is not None:
            self.fullscreen_on_monitor(monitor)
        else:
            self.fullscreen()

    # --- barra de ferramentas -------------------------------------------
    def _build_toolbar(self, color):
        bar = Gtk.Box(spacing=8, css_classes=["capture-toolbar"],
                      halign=Gtk.Align.START, valign=Gtk.Align.START)

        tools_box = Gtk.Box(css_classes=["linked"])
        group = None
        for tool_id, label, key in TOOLS:
            btn = Gtk.ToggleButton(child=tool_icon(tool_id), tooltip_text=f"{label} ({key.upper()})")
            if group is None:
                group = btn
            else:
                btn.set_group(group)
            btn.connect("toggled", self._on_tool_toggled, tool_id)
            tools_box.append(btn)
            self.tool_buttons[tool_id] = btn
        bar.append(tools_box)
        bar.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))

        for spec in PALETTE:
            bar.append(self._color_swatch(spec))
        self.color_btn = Gtk.ColorDialogButton(dialog=Gtk.ColorDialog(with_alpha=False), rgba=color,
                                               valign=Gtk.Align.CENTER, tooltip_text="Outra cor")
        self.color_btn.connect("notify::rgba", self._on_color_changed)
        bar.append(self.color_btn)

        self.width_spin = Gtk.SpinButton.new_with_range(1, 30, 1)
        self.width_spin.set_value(self.canvas.width)
        self.width_spin.set_valign(Gtk.Align.CENTER)
        self.width_spin.set_tooltip_text("Espessura / tamanho do texto / intensidade do efeito ( [ e ] )")
        self.width_spin.connect("value-changed", self._on_width_changed)
        bar.append(self.width_spin)
        bar.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))

        self.undo_btn = Gtk.Button(icon_name="edit-undo-symbolic", tooltip_text="Desfazer (Ctrl+Z)")
        self.undo_btn.connect("clicked", lambda *_: self.canvas.undo())
        self.redo_btn = Gtk.Button(icon_name="edit-redo-symbolic", tooltip_text="Refazer (Ctrl+Shift+Z)")
        self.redo_btn.connect("clicked", lambda *_: self.canvas.redo())
        bar.append(self.undo_btn)
        bar.append(self.redo_btn)
        bar.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))

        copy_btn = Gtk.Button(icon_name="edit-copy-symbolic", tooltip_text="Copiar e fechar (Enter / Ctrl+C)")
        copy_btn.connect("clicked", lambda *_: self.copy_and_close())
        save_btn = Gtk.Button(icon_name="document-save-symbolic", tooltip_text="Salvar (Ctrl+S)",
                              css_classes=["suggested-action"])
        save_btn.connect("clicked", lambda *_: self.save())
        close_btn = Gtk.Button(icon_name="window-close-symbolic", tooltip_text="Cancelar (Esc)")
        close_btn.connect("clicked", lambda *_: self.cancel())
        bar.append(copy_btn)
        bar.append(save_btn)
        bar.append(close_btn)
        return bar

    def _color_swatch(self, spec):
        btn = Gtk.Button(tooltip_text=spec, valign=Gtk.Align.CENTER, css_classes=["flat"])
        swatch = Gtk.DrawingArea(content_width=16, content_height=16)
        rgba = _parse_rgba(spec)

        def draw(_a, cr, w, h):
            cr.arc(w / 2, h / 2, min(w, h) / 2 - 1, 0, 6.2832)
            cr.set_source_rgba(rgba.red, rgba.green, rgba.blue, 1)
            cr.fill_preserve()
            cr.set_source_rgba(0.5, 0.5, 0.5, 0.8)
            cr.set_line_width(1)
            cr.stroke()

        swatch.set_draw_func(draw)
        btn.set_child(swatch)
        btn.connect("clicked", lambda *_: self.color_btn.set_rgba(rgba))
        return btn

    def _place_toolbar(self):
        """Posiciona a barra abaixo da seleção (ou acima / dentro, se não couber).

        Só reposiciona quando a seleção muda, e mantém o lado escolhido
        enquanto ainda couber, para a barra não pular a cada anotação.
        """
        rect = self.canvas.selection_widget_rect()
        if rect is None:
            self.toolbar.set_visible(False)
            self._toolbar_rect = None
            return
        rect = tuple(rect)
        if rect == self._toolbar_rect and self.toolbar.get_visible():
            return
        self._toolbar_rect = rect
        x, y, w, h = rect
        W, H = self.canvas.get_width(), self.canvas.get_height()
        # measure() devolve 0 com a barra oculta e inclui as margens, que
        # usamos justamente para posicionar
        tb = self.toolbar
        tb.set_visible(True)
        _min, tw, _b, _b2 = tb.measure(Gtk.Orientation.HORIZONTAL, -1)
        tw -= tb.get_margin_start() + tb.get_margin_end()
        _min, th, _b, _b2 = tb.measure(Gtk.Orientation.VERTICAL, -1)
        th -= tb.get_margin_top() + tb.get_margin_bottom()

        positions = {
            "below": y + h + TOOLBAR_GAP,
            "above": y - TOOLBAR_GAP - th,
        }
        fits = {
            "below": positions["below"] + th <= H,
            "above": positions["above"] >= 0,
        }
        side = self._toolbar_side
        if not fits.get(side, False):
            side = next((s for s in ("below", "above") if fits[s]), "inside")
        self._toolbar_side = side
        if side == "inside":
            ty = max(0, y + h - th - TOOLBAR_GAP)
        else:
            ty = positions[side]
        tx = min(max(x + w - tw, 0), max(0, W - tw))  # alinhada à direita da seleção
        tb.set_margin_start(int(tx))
        tb.set_margin_top(int(ty))

    # --- eventos ---------------------------------------------------------
    def _on_selection_dragging(self, _canvas, dragging):
        if dragging:
            self.toolbar.set_visible(False)
        else:
            self._place_toolbar()

    def _on_canvas_changed(self, _canvas):
        self._update_history_buttons()
        if self.canvas.has_selection():
            self._place_toolbar()
        else:
            self.toolbar.set_visible(False)

    def _update_history_buttons(self):
        self.undo_btn.set_sensitive(self.canvas.can_undo())
        self.redo_btn.set_sensitive(self.canvas.can_redo())

    def _on_key(self, _ctrl, keyval, _code, state):
        ctrl = bool(state & Gdk.ModifierType.CONTROL_MASK)
        shift = bool(state & Gdk.ModifierType.SHIFT_MASK)
        key = Gdk.keyval_to_lower(keyval)
        if keyval == Gdk.KEY_Escape:
            if not self.canvas.clear_selection():
                self.cancel()
            return True
        if not self.canvas.has_selection():
            return False
        if ctrl:
            if key == Gdk.KEY_z and shift or key == Gdk.KEY_y:
                self.canvas.redo()
            elif key == Gdk.KEY_z:
                self.canvas.undo()
            elif key == Gdk.KEY_c:
                self.copy_and_close()
            elif key == Gdk.KEY_s:
                self.save()
            else:
                return False
            return True
        if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            self.copy_and_close()
            return True
        if keyval in (Gdk.KEY_Delete, Gdk.KEY_BackSpace):
            return self.canvas.delete_selected()
        if keyval == Gdk.KEY_bracketleft:
            self.width_spin.spin(Gtk.SpinType.STEP_BACKWARD, 1)
            return True
        if keyval == Gdk.KEY_bracketright:
            self.width_spin.spin(Gtk.SpinType.STEP_FORWARD, 1)
            return True
        name = Gdk.keyval_name(key) or ""
        for tool_id, _label, shortcut in TOOLS:
            if name == shortcut:
                self.tool_buttons[tool_id].set_active(True)
                return True
        return False

    def _on_tool_toggled(self, btn, tool_id):
        if btn.get_active():
            logger.debug("Ferramenta: %s", tool_id)
            self.canvas.set_tool(tool_id)

    def _on_color_changed(self, btn, _pspec):
        rgba = btn.get_rgba()
        self.canvas.set_color(_rgba_tuple(rgba))
        config.set("editor_color", _to_hex(rgba))

    def _on_width_changed(self, spin):
        width = spin.get_value_as_int()
        self.canvas.set_width(width)
        config.set("editor_width", width)

    def _ask_text(self, wx, wy, ix, iy):
        popover = Gtk.Popover()
        popover.set_parent(self.canvas)
        rect = Gdk.Rectangle()
        rect.x, rect.y, rect.width, rect.height = int(wx), int(wy), 1, 1
        popover.set_pointing_to(rect)
        entry = Gtk.Entry(placeholder_text="Digite o texto e Enter", width_chars=28)
        popover.set_child(entry)

        def commit(*_):
            logger.debug("Texto adicionado (%d caracteres)", len(entry.get_text()))
            self.canvas.add_text(ix, iy, entry.get_text())
            popover.popdown()

        entry.connect("activate", commit)
        popover.connect("closed", lambda p: GLib.idle_add(p.unparent))
        popover.popup()
        entry.grab_focus()

    # --- ações finais ----------------------------------------------------
    def _copy(self):
        data = self.canvas.export_png_bytes()
        self.get_clipboard().set_content(Gdk.ContentProvider.new_for_bytes("image/png", GLib.Bytes.new(data)))
        logger.info("Imagem copiada para a área de transferência (%.0f KB)", len(data) / 1024)
        # No Wayland a área de transferência pertence ao app: mantém o app vivo após fechar
        self.get_application().keep_clipboard_alive()

    def copy_and_close(self):
        if not self.canvas.has_selection():
            return
        self._copy()
        self._finish("copied")

    def save(self):
        if not self.canvas.has_selection():
            return

        def on_named(target):
            if target is None:
                return  # continua editando
            try:
                target = Path(target)
                target.parent.mkdir(parents=True, exist_ok=True)
                data = self.canvas.export_png_bytes()
                target.write_bytes(data)
            except OSError as e:
                logger.error("Erro ao salvar %s: %s", target, e)
                self.get_application().notify_user(f"Erro ao salvar: {e.strerror}")
                return
            logger.info("Captura salva em %s (%.0f KB, %d anotações)", target, len(data) / 1024,
                        len(self.canvas.shapes))
            if config.get("copy_on_save"):
                self._copy()
            self.get_application().notify_user(f"Print salvo: {target.name}", "Abrir", "app.open-file",
                                               GLib.Variant("s", str(target)))
            self._finish("saved")

        ask_filename(self, "Salvar captura", config.get("screenshot_dir"), ".png", on_named)

    def cancel(self):
        self._finish("cancelled")

    def cancel_silently(self):
        """Fecha sem avisar (a seleção foi iniciada em outro monitor)."""
        if not self.finished:
            self.finished = True
            self.close()

    def _on_close_request(self, _win):
        if not self.finished:
            self.finished = True
            self.on_done("cancelled")
        return False

    def _finish(self, result):
        if self.finished:
            return
        self.finished = True
        self.close()
        self.on_done(result)
