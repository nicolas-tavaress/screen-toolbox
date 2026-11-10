"""Print da tela no Windows (GDI) e informações dos monitores."""

import ctypes

import cairo
from gi.repository import GLib

from .. import log
from . import BITMAPINFO, MONITORENUMPROC, MONITORINFOEXW, gdi32, last_error, user32

logger = log.get(__name__)

SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN, SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN = 76, 77, 78, 79
SRCCOPY, CAPTUREBLT = 0x00CC0020, 0x40000000
DIB_RGB_COLORS = 0
MONITORINFOF_PRIMARY = 1


def virtual_screen():
    """(x, y, largura, altura) da área que engloba todos os monitores, em pixels físicos."""
    return tuple(user32.GetSystemMetrics(i) for i in
                 (SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN, SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN))


def monitors():
    """Monitores em pixels físicos: o principal primeiro, depois da esquerda para a direita.

    Cada item: {"handle", "x", "y", "width", "height", "primary", "device"}.
    """
    found = []

    def callback(hmonitor, _hdc, _rect, _data):
        info = MONITORINFOEXW()
        info.cbSize = ctypes.sizeof(MONITORINFOEXW)
        if user32.GetMonitorInfoW(hmonitor, ctypes.byref(info)):
            r = info.rcMonitor
            found.append({
                "handle": int(hmonitor), "x": r.left, "y": r.top,
                "width": r.right - r.left, "height": r.bottom - r.top,
                "primary": bool(info.dwFlags & MONITORINFOF_PRIMARY), "device": info.szDevice,
            })
        return True

    user32.EnumDisplayMonitors(None, None, MONITORENUMPROC(callback), 0)
    found.sort(key=lambda m: (not m["primary"], m["x"], m["y"]))
    return found


def capture_virtual_screen():
    """Copia todos os monitores para uma cairo.ImageSurface ARGB32 (opaca)."""
    x, y, width, height = virtual_screen()
    if width <= 0 or height <= 0:
        raise OSError("Tamanho da tela inválido")
    screen_dc = user32.GetDC(None)
    if not screen_dc:
        raise last_error()
    mem_dc = gdi32.CreateCompatibleDC(screen_dc)
    bmi = BITMAPINFO()
    bmi.bmiHeader.biSize = ctypes.sizeof(bmi.bmiHeader)
    bmi.bmiHeader.biWidth = width
    bmi.bmiHeader.biHeight = -height  # negativo: linhas de cima para baixo, como no Cairo
    bmi.bmiHeader.biPlanes = 1
    bmi.bmiHeader.biBitCount = 32
    bits = ctypes.c_void_p()
    bitmap = gdi32.CreateDIBSection(mem_dc, ctypes.byref(bmi), DIB_RGB_COLORS, ctypes.byref(bits), None, 0)
    try:
        if not bitmap:
            raise last_error()
        old = gdi32.SelectObject(mem_dc, bitmap)
        ok = gdi32.BitBlt(mem_dc, 0, 0, width, height, screen_dc, x, y, SRCCOPY | CAPTUREBLT)
        gdi32.SelectObject(mem_dc, old)
        if not ok:
            raise last_error()
        # BGRA de 32 bits é o layout nativo do Cairo; o GDI deixa o alfa zerado, então
        # a imagem entra como RGB24 e é pintada numa superfície ARGB32 opaca.
        rgb = cairo.ImageSurface(cairo.FORMAT_RGB24, width, height)
        stride, row = rgb.get_stride(), width * 4
        target = (ctypes.c_char * (stride * height)).from_buffer(rgb.get_data())
        base = ctypes.addressof(target)
        if stride == row:
            ctypes.memmove(base, bits.value, row * height)
        else:
            for line in range(height):
                ctypes.memmove(base + line * stride, bits.value + line * row, row)
        del target
        rgb.mark_dirty()
    finally:
        if bitmap:
            gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(mem_dc)
        user32.ReleaseDC(None, screen_dc)
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
    cr = cairo.Context(surface)
    cr.set_source_surface(rgb, 0, 0)
    cr.paint()
    return surface


def take_screenshot(callback):
    """Mesma interface de capture.screenshot: callback(surface | None, erro | None)."""

    def run():
        try:
            surface = capture_virtual_screen()
        except OSError as e:
            logger.error("Falha no print via GDI: %s", e)
            callback(None, str(e))
            return False
        logger.info("Print da tela virtual: %dx%d", surface.get_width(), surface.get_height())
        callback(surface, None)
        return False

    GLib.idle_add(run)


def monitor_offsets():
    """Retângulos dos monitores relativos à origem da tela virtual (na ordem de monitors())."""
    vx, vy, _w, _h = virtual_screen()
    return [dict(m, x=m["x"] - vx, y=m["y"] - vy) for m in monitors()]
