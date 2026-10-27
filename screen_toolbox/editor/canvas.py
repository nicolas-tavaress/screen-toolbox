"""Tela de captura e edição (estilo Flameshot).

Ocupa o monitor inteiro sobre o print congelado. Primeiro o usuário arrasta para
selecionar a área; depois desenha direto sobre ela, e a seleção continua ajustável
(alças nas bordas/cantos) e móvel (ferramenta "Mover"), sem perder as anotações.
"""

import io
import math

import cairo
from gi.repository import Gdk, GObject, Gtk

from .. import log
from .tools import FREEHAND, TWO_POINT, EffectCache, Shape, render_shape

logger = log.get(__name__)

ACCENT = (0.21, 0.52, 0.89)
HANDLE = 9  # px (tela): área sensível das alças da seleção
MIN_SELECTION = 4  # px (tela): arrastes menores são tratados como clique

EDGE_CURSORS = {
    "n": "n-resize", "s": "s-resize", "e": "e-resize", "w": "w-resize",
    "nw": "nw-resize", "ne": "ne-resize", "sw": "sw-resize", "se": "se-resize",
}


class History:
    """Undo/redo por snapshots do estado (objetos + seleção)."""

    def __init__(self):
        self.undo_stack = []
        self.redo_stack = []

    def push(self, state):
        self.undo_stack.append(state)
        self.redo_stack.clear()
        if len(self.undo_stack) > 200:
            self.undo_stack.pop(0)

    def undo(self, current):
        if not self.undo_stack:
            return None
        self.redo_stack.append(current)
        return self.undo_stack.pop()

    def redo(self, current):
        if not self.redo_stack:
            return None
        self.undo_stack.append(current)
        return self.redo_stack.pop()


class Canvas(Gtk.DrawingArea):
    __gsignals__ = {
        # objetos/seleção mudaram (para undo, barra de ferramentas...)
        "changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
        # arrasto da seleção começou/terminou (a barra some durante o arrasto)
        "selection-dragging": (GObject.SignalFlags.RUN_FIRST, None, (bool,)),
        # primeira seleção feita (para fechar os seletores dos outros monitores)
        "selection-started": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self, surface):
        super().__init__(hexpand=True, vexpand=True, focusable=True)
        self.base = surface
        self.effects = EffectCache(surface)
        self.shapes = []
        self.crop = None  # seleção (x, y, w, h) em coordenadas da imagem
        self.history = History()
        self.tool = "select"
        self.color = (0.88, 0.11, 0.14, 1.0)
        self.width = 4
        self.current = None
        self.selected = None
        self._mode = None  # new-selection | resize:<borda> | move-selection | move-shape | draw
        self._drag_origin = None
        self._snapshot_before = None
        self._last = None
        self._started = False

        self.set_draw_func(self._draw)
        self.set_cursor(Gdk.Cursor.new_from_name("crosshair"))

        drag = Gtk.GestureDrag(button=Gdk.BUTTON_PRIMARY)
        drag.connect("drag-begin", self._on_drag_begin)
        drag.connect("drag-update", self._on_drag_update)
        drag.connect("drag-end", self._on_drag_end)
        self.add_controller(drag)

        motion = Gtk.EventControllerMotion()
        motion.connect("motion", self._on_motion)
        self.add_controller(motion)

    # --- estado / histórico ---------------------------------------------
    def _snapshot(self):
        return ([s.copy() for s in self.shapes], self.crop)

    def _restore(self, state):
        self.shapes, self.crop = [s.copy() for s in state[0]], state[1]
        self.selected = None
        self.queue_draw()
        self.emit("changed")

    def _commit(self):
        """Grava o estado atual antes de uma alteração."""
        self.history.push(self._snapshot())

    def undo(self):
        state = self.history.undo(self._snapshot())
        if state:
            logger.debug("Desfazer (restam %d)", len(self.history.undo_stack))
            self._restore(state)

    def redo(self):
        state = self.history.redo(self._snapshot())
        if state:
            logger.debug("Refazer (restam %d)", len(self.history.redo_stack))
            self._restore(state)

    def can_undo(self):
        return bool(self.history.undo_stack)

    def can_redo(self):
        return bool(self.history.redo_stack)

    def has_selection(self):
        return self.crop is not None

    def set_tool(self, tool):
        self.tool = tool
        self.selected = None
        self.queue_draw()

    def set_color(self, rgba):
        self.color = rgba
        if self.selected is not None:
            self._commit()
            self.selected.color = rgba
            self.queue_draw()
            self.emit("changed")

    def set_width(self, width):
        self.width = width
        if self.selected is not None and self.selected.kind != "number":
            self._commit()
            self.selected.width = width
            self.queue_draw()
            self.emit("changed")

    def delete_selected(self):
        if self.selected is None:
            return False
        self._commit()
        logger.debug("Objeto removido: %s", self.selected.kind)
        self.shapes.remove(self.selected)
        self.selected = None
        self.queue_draw()
        self.emit("changed")
        return True

    def clear_selection(self):
        if self.selected is None:
            return False
        self.selected = None
        self.queue_draw()
        return True

    def add_text(self, x, y, text):
        if not text.strip():
            return
        self._commit()
        self.shapes.append(Shape("text", self.color, self.width, [(x, y)], text))
        self.queue_draw()
        self.emit("changed")

    def next_number(self):
        nums = [int(s.text) for s in self.shapes if s.kind == "number" and s.text.isdigit()]
        return max(nums, default=0) + 1

    # --- coordenadas -----------------------------------------------------
    def scale(self):
        """Pixels da imagem por pixel da tela (a imagem ocupa o monitor inteiro)."""
        return self.base.get_width() / max(1, self.get_width())

    def to_image(self, x, y):
        k = self.scale()
        return x * k, y * k

    def to_widget(self, x, y):
        k = self.scale()
        return x / k, y / k

    def selection_widget_rect(self):
        """Seleção em coordenadas da tela (x, y, w, h) ou None."""
        if self._mode == "new-selection" and self.current is not None:
            x, y, w, h = self.current.rect()
        elif self.crop is not None:
            x, y, w, h = self.crop
        else:
            return None
        k = self.scale()
        return x / k, y / k, w / k, h / k

    def _clamp_crop(self, x0, y0, x1, y1):
        iw, ih = self.base.get_width(), self.base.get_height()
        x0, x1 = sorted((min(max(x0, 0), iw), min(max(x1, 0), iw)))
        y0, y1 = sorted((min(max(y0, 0), ih), min(max(y1, 0), ih)))
        return x0, y0, x1 - x0, y1 - y0

    def _edge_at(self, wx, wy):
        """Borda/canto da seleção sob o ponteiro (ex.: 'nw', 'e') ou None."""
        rect = self.selection_widget_rect()
        if rect is None:
            return None
        x, y, w, h = rect
        inside_x = x - HANDLE <= wx <= x + w + HANDLE
        inside_y = y - HANDLE <= wy <= y + h + HANDLE
        edge = ""
        if inside_x and abs(wy - y) <= HANDLE:
            edge += "n"
        elif inside_x and abs(wy - (y + h)) <= HANDLE:
            edge += "s"
        if inside_y and abs(wx - x) <= HANDLE:
            edge += "w"
        elif inside_y and abs(wx - (x + w)) <= HANDLE:
            edge += "e"
        return edge or None

    def _inside_selection(self, wx, wy):
        rect = self.selection_widget_rect()
        if rect is None:
            return False
        x, y, w, h = rect
        return x < wx < x + w and y < wy < y + h

    # --- mouse -----------------------------------------------------------
    def _on_motion(self, _ctrl, x, y):
        if self.crop is None:
            name = "crosshair"
        elif (edge := self._edge_at(x, y)) is not None:
            name = EDGE_CURSORS[edge]
        elif self.tool == "select":
            ix, iy = self.to_image(x, y)
            over_shape = any(s.hit(ix, iy) for s in self.shapes)
            name = "move" if over_shape or self._inside_selection(x, y) else "default"
        elif self.tool == "text":
            name = "text"
        else:
            name = "crosshair"
        self.set_cursor(Gdk.Cursor.new_from_name(name))

    def _on_drag_begin(self, _gesture, x, y):
        self.grab_focus()
        ix, iy = self.to_image(x, y)
        self._drag_origin = (ix, iy)
        self._last = (ix, iy)
        self._snapshot_before = self._snapshot()
        tool = self.tool

        if self.crop is None:
            self._mode = "new-selection"
            self.current = Shape("crop", self.color, 1, [(ix, iy), (ix, iy)])
            if not self._started:
                self._started = True
                self.emit("selection-started")
            self.emit("selection-dragging", True)
        elif (edge := self._edge_at(x, y)) is not None:
            self._mode = f"resize:{edge}"
            self.emit("selection-dragging", True)
        elif tool == "select":
            self.selected = next((s for s in reversed(self.shapes) if s.hit(ix, iy)), None)
            if self.selected is not None:
                self._mode = "move-shape"
            elif self._inside_selection(x, y):
                self._mode = "move-selection"
                self.emit("selection-dragging", True)
            else:
                self._mode = None
        elif tool == "text":
            self._mode = None
            self.emit_text_request(x, y, ix, iy)
        elif tool == "number":
            self._mode = None
            self._commit()
            self.shapes.append(Shape("number", self.color, self.width, [(ix, iy)], str(self.next_number())))
            self.emit("changed")
        elif tool in FREEHAND:
            self._mode = "draw"
            self.current = Shape(tool, self.color, self.width, [(ix, iy)])
        elif tool in TWO_POINT:
            self._mode = "draw"
            self.current = Shape(tool, self.color, self.width, [(ix, iy), (ix, iy)])
        self.queue_draw()

    def _on_drag_update(self, gesture, dx, dy):
        if self._mode is None:
            return
        _ok, sx, sy = gesture.get_start_point()
        ix, iy = self.to_image(sx + dx, sy + dy)
        shift = gesture.get_current_event_state() & Gdk.ModifierType.SHIFT_MASK

        if self._mode == "new-selection":
            self.current.points[-1] = (ix, iy)
        elif self._mode.startswith("resize:"):
            edge = self._mode.split(":")[1]
            x, y, w, h = self._snapshot_before[1]
            x0, y0, x1, y1 = x, y, x + w, y + h
            ox, oy = self._drag_origin
            if "w" in edge:
                x0 += ix - ox
            if "e" in edge:
                x1 += ix - ox
            if "n" in edge:
                y0 += iy - oy
            if "s" in edge:
                y1 += iy - oy
            self.crop = self._clamp_crop(x0, y0, x1, y1)
        elif self._mode == "move-selection":
            x, y, w, h = self._snapshot_before[1]
            ox, oy = self._drag_origin
            iw, ih = self.base.get_width(), self.base.get_height()
            nx = min(max(x + ix - ox, 0), iw - w)
            ny = min(max(y + iy - oy, 0), ih - h)
            self.crop = (nx, ny, w, h)
        elif self._mode == "move-shape":
            lx, ly = self._last
            self.selected.translate(ix - lx, iy - ly)
        elif self._mode == "draw":
            if self.current.kind in FREEHAND:
                self.current.points.append((ix, iy))
            else:
                if shift:
                    ix, iy = self._constrain(self.current.points[0], (ix, iy), self.current.kind)
                self.current.points[-1] = (ix, iy)
        self._last = (ix, iy)
        self.queue_draw()

    def _on_drag_end(self, _gesture, _dx, _dy):
        mode, self._mode = self._mode, None
        if mode == "new-selection":
            shape, self.current = self.current, None
            (x0, y0), (x1, y1) = shape.points
            k = self.scale()
            if abs(x1 - x0) / k >= MIN_SELECTION and abs(y1 - y0) / k >= MIN_SELECTION:
                self.history.push(self._snapshot_before)
                self.crop = self._clamp_crop(x0, y0, x1, y1)
                logger.info("Área selecionada: %dx%d em (%d, %d)",
                            self.crop[2], self.crop[3], self.crop[0], self.crop[1])
                self.emit("changed")
            self.emit("selection-dragging", False)
        elif mode and (mode.startswith("resize:") or mode == "move-selection"):
            if self.crop != self._snapshot_before[1]:
                self.history.push(self._snapshot_before)
                logger.debug("Seleção ajustada: %dx%d em (%d, %d)",
                             self.crop[2], self.crop[3], self.crop[0], self.crop[1])
                self.emit("changed")
            self.emit("selection-dragging", False)
        elif mode == "move-shape":
            if self._snapshot_before[0] != self.shapes:
                logger.debug("Objeto movido: %s", self.selected.kind)
                self.history.push(self._snapshot_before)
                self.emit("changed")
        elif mode == "draw":
            shape, self.current = self.current, None
            if shape.kind in FREEHAND or max(shape.rect()[2:]) >= 3:
                self.history.push(self._snapshot_before)
                logger.debug("Objeto adicionado: %s", shape.kind)
                self.shapes.append(shape)
                self.emit("changed")
        self._snapshot_before = None
        self.queue_draw()

    @staticmethod
    def _constrain(start, end, kind):
        """Shift: quadrado/círculo para formas; ângulos de 45° para linhas."""
        (x0, y0), (x1, y1) = start, end
        dx, dy = x1 - x0, y1 - y0
        if kind in ("line", "arrow"):
            angle = round(math.atan2(dy, dx) / (math.pi / 4)) * (math.pi / 4)
            length = math.hypot(dx, dy)
            return x0 + length * math.cos(angle), y0 + length * math.sin(angle)
        side = max(abs(dx), abs(dy))
        return x0 + math.copysign(side, dx), y0 + math.copysign(side, dy)

    # a janela conecta isso para mostrar o campo de texto
    text_request_handler = None

    def emit_text_request(self, wx, wy, ix, iy):
        if self.text_request_handler:
            self.text_request_handler(wx, wy, ix, iy)

    # --- desenho / exportação -------------------------------------------
    def _render(self, cr, include_current=True):
        cr.set_source_surface(self.base, 0, 0)
        cr.paint()
        for shape in self.shapes:
            render_shape(cr, shape, self.effects)
        if include_current and self.current is not None and self.current.kind != "crop":
            render_shape(cr, self.current, self.effects)

    def _draw(self, _area, cr, width, height):
        k = self.scale()
        cr.save()
        cr.scale(1 / k, 1 / k)
        self._render(cr)
        cr.restore()

        rect = self.selection_widget_rect()
        cr.set_fill_rule(cairo.FILL_RULE_EVEN_ODD)
        cr.rectangle(0, 0, width, height)
        if rect:
            cr.rectangle(*rect)
        cr.set_source_rgba(0, 0, 0, 0.5)
        cr.fill()

        if rect is None:
            self._label(cr, "Arraste para selecionar a área  •  Esc cancela", None, 24, 15, width)
            return

        x, y, w, h = rect
        cr.set_source_rgb(*ACCENT)
        cr.set_line_width(2)
        cr.rectangle(x, y, w, h)
        cr.stroke()
        # alças nos cantos e no meio das bordas
        for hx in (x, x + w / 2, x + w):
            for hy in (y, y + h / 2, y + h):
                if (hx, hy) != (x + w / 2, y + h / 2):
                    cr.arc(hx, hy, 4.5, 0, 2 * math.pi)
                    cr.new_sub_path()
        cr.set_source_rgb(1, 1, 1)
        cr.fill_preserve()
        cr.set_source_rgb(*ACCENT)
        cr.set_line_width(1.5)
        cr.stroke()

        sw, sh = round(w * k), round(h * k)
        self._label(cr, f"{sw} × {sh}", x, y - 30 if y > 34 else y + 6, 12)

        if self.selected is not None:
            bx, by, bw, bh = self.selected.bbox()
            wx, wy = self.to_widget(bx, by)
            cr.set_source_rgb(*ACCENT)
            cr.set_line_width(1.5)
            cr.set_dash([4, 3])
            cr.rectangle(wx - 4, wy - 4, bw / k + 8, bh / k + 8)
            cr.stroke()
            cr.set_dash([])

    @staticmethod
    def _label(cr, text, x, y, size, center_width=None):
        cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        cr.set_font_size(size)
        ext = cr.text_extents(text)
        pad = 7
        w, h = ext.width + 2 * pad, size + 2 * pad
        if center_width is not None:
            x = (center_width - w) / 2
        r = 6
        cr.new_sub_path()
        cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
        cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
        cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
        cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
        cr.close_path()
        cr.set_source_rgba(0, 0, 0, 0.75)
        cr.fill()
        cr.set_source_rgb(1, 1, 1)
        cr.move_to(x + pad - ext.x_bearing, y + pad + size * 0.8)
        cr.show_text(text)

    def export_surface(self):
        """Imagem final: a área selecionada com as anotações."""
        iw, ih = self.base.get_width(), self.base.get_height()
        full = cairo.ImageSurface(cairo.FORMAT_ARGB32, iw, ih)
        self._render(cairo.Context(full), include_current=False)
        if not self.crop:
            return full
        x, y, w, h = (int(round(v)) for v in self.crop)
        out = cairo.ImageSurface(cairo.FORMAT_ARGB32, max(1, w), max(1, h))
        cr = cairo.Context(out)
        cr.set_source_surface(full, -x, -y)
        cr.paint()
        return out

    def export_png_bytes(self):
        buf = io.BytesIO()
        self.export_surface().write_to_png(buf)
        return buf.getvalue()
