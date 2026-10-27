"""Objetos de anotação (vetoriais) e sua renderização com Cairo."""

import math
from dataclasses import dataclass, field, replace

import cairo
from gi.repository import Pango, PangoCairo

# (id, rótulo, atalho)
TOOLS = [
    ("select", "Mover objetos e a área selecionada", "v"),
    ("pen", "Caneta", "p"),
    ("highlighter", "Marca-texto", "h"),
    ("line", "Linha", "l"),
    ("arrow", "Seta", "a"),
    ("rect", "Retângulo", "r"),
    ("ellipse", "Elipse", "e"),
    ("text", "Texto", "t"),
    ("number", "Marcador numerado", "n"),
    ("blur", "Desfocar", "b"),
    ("pixelate", "Pixelar", "x"),
]

FREEHAND = {"pen", "highlighter"}
TWO_POINT = {"line", "arrow", "rect", "ellipse", "blur", "pixelate"}
SINGLE_POINT = {"text", "number"}


@dataclass
class Shape:
    kind: str
    color: tuple  # (r, g, b, a)
    width: float
    points: list = field(default_factory=list)
    text: str = ""

    def copy(self):
        return replace(self, points=list(self.points))

    def translate(self, dx, dy):
        self.points = [(x + dx, y + dy) for x, y in self.points]

    def rect(self):
        (x0, y0), (x1, y1) = self.points[0], self.points[-1]
        return min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0)

    def font_size(self):
        return 12 + self.width * 3

    def number_radius(self):
        return 11 + self.width * 2

    def bbox(self):
        """Caixa envolvente aproximada (x, y, w, h) para seleção."""
        if self.kind == "text":
            w, h = text_size(self.text, self.font_size())
            x, y = self.points[0]
            return x, y, w, h
        if self.kind == "number":
            r = self.number_radius()
            x, y = self.points[0]
            return x - r, y - r, 2 * r, 2 * r
        xs = [p[0] for p in self.points]
        ys = [p[1] for p in self.points]
        pad = self.width * (2 if self.kind == "highlighter" else 1) + (self.width * 4 if self.kind == "arrow" else 0)
        return min(xs) - pad, min(ys) - pad, max(xs) - min(xs) + 2 * pad, max(ys) - min(ys) + 2 * pad

    def hit(self, x, y, tolerance=6):
        bx, by, bw, bh = self.bbox()
        return bx - tolerance <= x <= bx + bw + tolerance and by - tolerance <= y <= by + bh + tolerance


def _font(size):
    desc = Pango.FontDescription.from_string("Sans Bold")
    desc.set_absolute_size(size * Pango.SCALE)
    return desc


def _text_layout(cr, text, size):
    layout = PangoCairo.create_layout(cr)
    layout.set_font_description(_font(size))
    layout.set_text(text, -1)
    return layout


_measure_surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 1, 1)


def text_size(text, size):
    layout = _text_layout(cairo.Context(_measure_surface), text or " ", size)
    w, h = layout.get_pixel_size()
    return w, h


def _contrast(color):
    r, g, b = color[:3]
    return (0, 0, 0) if 0.299 * r + 0.587 * g + 0.114 * b > 0.6 else (1, 1, 1)


class EffectCache:
    """Guarda as superfícies de desfoque/pixelização para não recalcular a cada frame."""

    def __init__(self, base):
        self.base = base
        self._cache = {}

    def get(self, shape):
        x, y, w, h = (int(round(v)) for v in shape.rect())
        key = (shape.kind, x, y, w, h, shape.width)
        surf = self._cache.get(key)
        if surf is None:
            if len(self._cache) > 64:
                self._cache.clear()
            surf = self._make(shape.kind, x, y, w, h, shape.width)
            self._cache[key] = surf
        return surf, x, y

    def _make(self, kind, x, y, w, h, strength):
        w, h = max(1, w), max(1, h)
        if kind == "pixelate":
            factor = max(4, int(strength * 3))
            return _resample(self.base, x, y, w, h, factor, cairo.FILTER_NEAREST)
        # Desfoque: reduz e amplia com filtro bilinear em várias passadas. Precisa ser forte
        # o bastante para tornar texto ilegível (o uso típico é esconder dados sensíveis).
        factor = max(12, int(strength * 4), int(min(w, h) / 3))
        out = _resample(self.base, x, y, w, h, factor, cairo.FILTER_BILINEAR)
        for _ in range(2):
            out = _resample(out, 0, 0, w, h, factor, cairo.FILTER_BILINEAR)
        return out


def _resample(src, x, y, w, h, factor, up_filter):
    sw, sh = max(1, math.ceil(w / factor)), max(1, math.ceil(h / factor))
    small = cairo.ImageSurface(cairo.FORMAT_ARGB32, sw, sh)
    cr = cairo.Context(small)
    cr.scale(sw / w, sh / h)
    cr.set_source_surface(src, -x, -y)
    cr.get_source().set_filter(cairo.FILTER_GOOD)
    cr.get_source().set_extend(cairo.EXTEND_PAD)
    cr.paint()

    out = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
    cr = cairo.Context(out)
    cr.scale(w / sw, h / sh)
    cr.set_source_surface(small, 0, 0)
    cr.get_source().set_filter(up_filter)
    cr.get_source().set_extend(cairo.EXTEND_PAD)
    cr.paint()
    return out


def render_shape(cr, shape, effects):
    kind = shape.kind
    cr.save()
    cr.set_line_cap(cairo.LINE_CAP_ROUND)
    cr.set_line_join(cairo.LINE_JOIN_ROUND)
    cr.set_line_width(shape.width)
    cr.set_source_rgba(*shape.color)

    if kind in FREEHAND:
        if kind == "highlighter":
            r, g, b, _a = shape.color
            cr.set_source_rgba(r, g, b, 0.4)
            cr.set_line_width(shape.width * 4)
            cr.set_line_cap(cairo.LINE_CAP_SQUARE)
        pts = shape.points
        if len(pts) == 1:
            pts = pts + [(pts[0][0] + 0.1, pts[0][1])]
        cr.move_to(*pts[0])
        for p in pts[1:]:
            cr.line_to(*p)
        cr.stroke()

    elif kind == "line":
        cr.move_to(*shape.points[0])
        cr.line_to(*shape.points[-1])
        cr.stroke()

    elif kind == "arrow":
        (x0, y0), (x1, y1) = shape.points[0], shape.points[-1]
        angle = math.atan2(y1 - y0, x1 - x0)
        head = max(12, shape.width * 4)
        length = math.hypot(x1 - x0, y1 - y0)
        # a haste termina antes da ponta para não "vazar" pela cabeça da seta
        shaft = max(0, length - head * 0.8)
        cr.move_to(x0, y0)
        cr.line_to(x0 + shaft * math.cos(angle), y0 + shaft * math.sin(angle))
        cr.stroke()
        spread = math.radians(28)
        cr.move_to(x1, y1)
        cr.line_to(x1 - head * math.cos(angle - spread), y1 - head * math.sin(angle - spread))
        cr.line_to(x1 - head * math.cos(angle + spread), y1 - head * math.sin(angle + spread))
        cr.close_path()
        cr.fill()

    elif kind == "rect":
        x, y, w, h = shape.rect()
        cr.rectangle(x, y, w, h)
        cr.stroke()

    elif kind == "ellipse":
        x, y, w, h = shape.rect()
        if w > 0 and h > 0:
            cr.save()
            cr.translate(x + w / 2, y + h / 2)
            cr.scale(w / 2, h / 2)
            cr.arc(0, 0, 1, 0, 2 * math.pi)
            cr.restore()
            cr.stroke()

    elif kind == "text":
        x, y = shape.points[0]
        layout = _text_layout(cr, shape.text, shape.font_size())
        cr.move_to(x, y)
        PangoCairo.layout_path(cr, layout)
        cr.set_source_rgba(*_contrast(shape.color), 0.85)
        cr.set_line_width(max(2, shape.font_size() / 8))
        cr.stroke_preserve()
        cr.set_source_rgba(*shape.color)
        cr.fill()

    elif kind == "number":
        x, y = shape.points[0]
        r = shape.number_radius()
        cr.arc(x, y, r, 0, 2 * math.pi)
        cr.fill_preserve()
        cr.set_source_rgba(*_contrast(shape.color), 0.9)
        cr.set_line_width(2)
        cr.stroke()
        layout = _text_layout(cr, shape.text, r * 1.1)
        tw, th = layout.get_pixel_size()
        cr.move_to(x - tw / 2, y - th / 2)
        cr.set_source_rgb(*_contrast(shape.color))
        PangoCairo.show_layout(cr, layout)

    elif kind in ("blur", "pixelate"):
        x, y, w, h = shape.rect()
        if w >= 1 and h >= 1:
            surf, ix, iy = effects.get(shape)
            cr.set_source_surface(surf, ix, iy)
            cr.rectangle(ix, iy, surf.get_width(), surf.get_height())
            cr.fill()

    cr.restore()
