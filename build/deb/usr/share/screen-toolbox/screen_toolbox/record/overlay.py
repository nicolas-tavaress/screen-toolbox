"""Desenho dos badges de teclas/cliques sobre cada frame do vídeo (cairooverlay)."""

import math

from gi.repository import Pango, PangoCairo


class KeyOverlay:
    def __init__(self, model, position="bottom-center", scale=1.0):
        self.model = model
        self.position = position
        self.scale = scale
        self.width = 0
        self.height = 0
        self.frames_drawn = 0  # quadros que receberam ao menos uma etiqueta

    def on_caps_changed(self, _overlay, caps):
        s = caps.get_structure(0)
        _ok, self.width = s.get_int("width")
        _ok, self.height = s.get_int("height")

    def on_draw(self, _overlay, cr, _timestamp, _duration):
        badges = self.model.visible()
        if not badges or not self.height:
            return
        self.frames_drawn += 1
        W, H = self.width, self.height
        size = max(14, H / 26 * self.scale)
        pad_x, pad_y = size * 0.7, size * 0.38
        gap = size * 0.35
        margin = size * 1.2
        radius = size * 0.4

        font = Pango.FontDescription.from_string("Sans Bold")
        font.set_absolute_size(size * Pango.SCALE)

        layouts = []
        for text, alpha in badges:
            layout = PangoCairo.create_layout(cr)
            layout.set_font_description(font)
            layout.set_text(text, -1)
            w, h = layout.get_pixel_size()
            layouts.append((layout, w + 2 * pad_x, h + 2 * pad_y, alpha))

        vertical, horizontal = self.position.split("-")
        bottom = vertical == "bottom"
        # o mais recente fica mais perto da borda
        y = H - margin if bottom else margin
        for layout, bw, bh, alpha in reversed(layouts):
            if bottom:
                y -= bh
            if horizontal == "left":
                x = margin
            elif horizontal == "right":
                x = W - margin - bw
            else:
                x = (W - bw) / 2

            _rounded_rect(cr, x, y, bw, bh, radius)
            cr.set_source_rgba(0.08, 0.08, 0.1, 0.78 * alpha)
            cr.fill_preserve()
            cr.set_source_rgba(1, 1, 1, 0.25 * alpha)
            cr.set_line_width(max(1, size / 14))
            cr.stroke()

            cr.move_to(x + pad_x, y + pad_y)
            cr.set_source_rgba(1, 1, 1, alpha)
            PangoCairo.show_layout(cr, layout)

            if bottom:
                y -= gap
            else:
                y += bh + gap


def _rounded_rect(cr, x, y, w, h, r):
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    cr.close_path()
