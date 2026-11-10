"""Recortes do print: por monitor e por região."""

import cairo

from .. import IS_WINDOWS, log

logger = log.get(__name__)


def crop_surface(surface, x, y, w, h):
    x, y = max(0, int(round(x))), max(0, int(round(y)))
    w = max(1, min(int(round(w)), surface.get_width() - x))
    h = max(1, min(int(round(h)), surface.get_height() - y))
    out = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
    cr = cairo.Context(out)
    cr.set_source_surface(surface, -x, -y)
    cr.paint()
    return out


def monitor_crop(surface, display, monitor):
    """Recorta, do print de todas as telas, a parte correspondente a `monitor`.

    O print vem em pixels físicos cobrindo o retângulo que engloba todos os
    monitores; as geometrias dos monitores estão em coordenadas lógicas.
    """
    monitors = [display.get_monitors().get_item(i) for i in range(display.get_monitors().get_n_items())]
    if len(monitors) <= 1 or monitor is None:
        return surface
    if IS_WINDOWS:
        return _monitor_crop_windows(surface, monitors, monitor)
    geos = [m.get_geometry() for m in monitors]
    min_x = min(g.x for g in geos)
    min_y = min(g.y for g in geos)
    total_w = max(g.x + g.width for g in geos) - min_x
    total_h = max(g.y + g.height for g in geos) - min_y
    sx = surface.get_width() / total_w
    sy = surface.get_height() / total_h
    if abs(sx - sy) > 0.05:  # layout inesperado: devolve tudo
        logger.warning("Layout de monitores inesperado (escalas %.3f x %.3f); usando a captura inteira", sx, sy)
        return surface
    g = monitor.get_geometry()
    crop = crop_surface(surface, (g.x - min_x) * sx, (g.y - min_y) * sy, g.width * sx, g.height * sy)
    # O compositor gera o print inteiro na maior escala entre os monitores; volta este
    # monitor para a sua resolução real (ex.: monitor 1x num print feito a 1.25x).
    scale = monitor.get_scale() if hasattr(monitor, "get_scale") else monitor.get_scale_factor()
    target_w, target_h = round(g.width * scale), round(g.height * scale)
    if target_w < crop.get_width() * 0.98:
        logger.debug("Monitor %s: reamostrando %dx%d -> %dx%d", monitor.get_connector(),
                     crop.get_width(), crop.get_height(), target_w, target_h)
        return _resize(crop, target_w, target_h)
    return crop


def _monitor_crop_windows(surface, monitors, monitor):
    """No Windows o print vem em pixels físicos e cada monitor pode ter um DPI diferente,
    então as geometrias lógicas do GDK não formam um layout com escala única. Os monitores
    do GDK são casados com os retângulos físicos do Windows pela ordem de posição."""
    from ..win32.screenshot import monitor_offsets

    rects = sorted(monitor_offsets(), key=lambda r: (r["x"], r["y"]))
    ordered = sorted(monitors, key=lambda m: (m.get_geometry().x, m.get_geometry().y))
    if len(rects) != len(ordered):
        logger.warning("Monitores do GDK (%d) e do Windows (%d) não batem; usando a captura inteira",
                       len(ordered), len(rects))
        return surface
    r = rects[ordered.index(monitor)]
    return crop_surface(surface, r["x"], r["y"], r["width"], r["height"])


def _resize(surface, width, height):
    out = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
    cr = cairo.Context(out)
    cr.scale(width / surface.get_width(), height / surface.get_height())
    cr.set_source_surface(surface, 0, 0)
    cr.get_source().set_filter(cairo.FILTER_BEST)
    cr.paint()
    return out
