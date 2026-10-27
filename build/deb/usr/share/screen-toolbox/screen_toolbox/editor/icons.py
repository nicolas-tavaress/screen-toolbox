"""Ícones das ferramentas desenhados com Cairo na cor do tema (claro/escuro)."""

import math

from gi.repository import Gtk


def _stroke(cr, w=1.6):
    cr.set_line_width(w)
    cr.stroke()


def _select(cr):
    cr.move_to(3, 1.5); cr.line_to(3, 13.5); cr.line_to(6.2, 10.6); cr.line_to(8.4, 15)
    cr.line_to(10.3, 14.1); cr.line_to(8.1, 9.8); cr.line_to(12.5, 9.6); cr.close_path(); cr.fill()


def _pen(cr):
    cr.move_to(2.5, 13.5); cr.line_to(3.2, 10.4); cr.line_to(11, 2.6); cr.line_to(13.4, 5)
    cr.line_to(5.6, 12.8); cr.close_path(); cr.move_to(9.6, 4); cr.line_to(12, 6.4); _stroke(cr)


def _highlighter(cr):
    cr.move_to(5, 10.5); cr.line_to(10.5, 2.5); cr.line_to(13.5, 4.6); cr.line_to(8, 12.6); cr.close_path()
    _stroke(cr)
    cr.rectangle(1, 13.8, 14, 1.8); cr.fill()


def _line(cr):
    cr.move_to(2.5, 13.5); cr.line_to(13.5, 2.5); _stroke(cr, 1.8)


def _arrow(cr):
    cr.move_to(2.5, 13.5); cr.line_to(11.5, 4.5); _stroke(cr, 1.8)
    cr.move_to(14.2, 1.8); cr.line_to(13.2, 8.4); cr.line_to(7.6, 2.8); cr.close_path(); cr.fill()


def _rect(cr):
    cr.rectangle(2, 3.5, 12, 9); _stroke(cr)


def _ellipse(cr):
    cr.save(); cr.translate(8, 8); cr.scale(6, 5); cr.arc(0, 0, 1, 0, 2 * math.pi); cr.restore(); _stroke(cr)


def _text(cr):
    cr.rectangle(2.5, 2, 11, 1.6); cr.rectangle(2.5, 2, 1.5, 3); cr.rectangle(12, 2, 1.5, 3)
    cr.rectangle(7.2, 2, 1.6, 12); cr.rectangle(5.5, 12.5, 5, 1.5); cr.fill()


def _number(cr):
    cr.arc(8, 8, 6.3, 0, 2 * math.pi); _stroke(cr, 1.4)
    cr.move_to(6, 6.2); cr.line_to(8.2, 4.6); cr.line_to(8.2, 11.5); _stroke(cr, 1.5)


def _blur(cr):
    for i in range(3):
        for j in range(3):
            fade = 1 - (i + j) * 0.15
            cr.arc(4 + 4 * i, 4 + 4 * j, 1.6 - (i + j) * 0.2, 0, 2 * math.pi)
            cr.save(); cr.clip(); cr.paint_with_alpha(fade); cr.restore()


def _pixelate(cr):
    for i in range(3):
        for j in range(3):
            cr.rectangle(1 + 4.8 * i, 1 + 4.8 * j, 4.4, 4.4)
            cr.save(); cr.clip(); cr.paint_with_alpha(1.0 if (i + j) % 2 == 0 else 0.35); cr.restore()


def _crop(cr):
    cr.move_to(4, 1); cr.line_to(4, 12); cr.line_to(15, 12)
    cr.move_to(1, 4); cr.line_to(12, 4); cr.line_to(12, 15); _stroke(cr)


DRAWERS = {
    "select": _select, "pen": _pen, "highlighter": _highlighter, "line": _line, "arrow": _arrow,
    "rect": _rect, "ellipse": _ellipse, "text": _text, "number": _number, "blur": _blur,
    "pixelate": _pixelate, "crop": _crop,
}


def tool_icon(tool_id, size=16):
    area = Gtk.DrawingArea(content_width=size, content_height=size)
    drawer = DRAWERS[tool_id]

    def draw(widget, cr, w, h):
        color = widget.get_color()
        cr.set_source_rgba(color.red, color.green, color.blue, color.alpha)
        cr.translate((w - size) / 2, (h - size) / 2)
        cr.scale(size / 16, size / 16)
        cr.set_line_cap(1)  # round
        cr.set_line_join(1)
        drawer(cr)

    area.set_draw_func(draw)
    return area
