"""Captura de tela via portal org.freedesktop.portal.Screenshot."""

import os
from urllib.parse import unquote, urlparse

import cairo
from gi.repository import Gdk, GdkPixbuf, GLib

from .. import log
from ..portal import RESPONSE_CANCELLED, RESPONSE_OK, get_portal

logger = log.get(__name__)

SCREENSHOT_IFACE = "org.freedesktop.portal.Screenshot"


def load_image_surface(path):
    """Carrega uma imagem como cairo.ImageSurface ARGB32."""
    try:
        return cairo.ImageSurface.create_from_png(path)
    except Exception as e:  # noqa: BLE001
        logger.debug("Não é PNG legível pelo Cairo (%s); usando GdkPixbuf", e)
        pixbuf = GdkPixbuf.Pixbuf.new_from_file(path)
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, pixbuf.get_width(), pixbuf.get_height())
        cr = cairo.Context(surface)
        Gdk.cairo_set_source_pixbuf(cr, pixbuf, 0, 0)
        cr.paint()
        return surface


def take_screenshot(callback):
    """Captura todas as telas sem diálogo (a área é escolhida depois, no seletor).

    callback(surface, error) — surface é cairo.ImageSurface ou None.
    """
    portal = get_portal()

    def build(token):
        options = {
            "handle_token": GLib.Variant("s", token),
            "interactive": GLib.Variant("b", False),
            "modal": GLib.Variant("b", False),
        }
        return GLib.Variant("(sa{sv})", ("", options))

    def on_response(response, results):
        if response == RESPONSE_CANCELLED:
            callback(None, None)
            return
        if response != RESPONSE_OK:
            callback(None, results.get("error") or "o portal de captura recusou a solicitação")
            return
        uri = results.get("uri", "")
        path = unquote(urlparse(uri).path)
        logger.debug("Portal entregou a captura em %s", uri)
        try:
            surface = load_image_surface(path)
        except Exception as e:  # noqa: BLE001
            logger.exception("Falha ao carregar a captura %s", path)
            callback(None, f"Não foi possível abrir a captura: {e}")
            return
        logger.info("Captura recebida: %dx%d", surface.get_width(), surface.get_height())
        # O portal grava um arquivo temporário só para nós; a versão final é salva pelo editor.
        try:
            os.unlink(path)
            logger.debug("Arquivo temporário do portal removido: %s", path)
        except OSError as e:
            logger.warning("Não foi possível remover o arquivo temporário %s: %s", path, e)
        callback(surface, None)

    logger.debug("Solicitando captura ao portal")
    portal.request(SCREENSHOT_IFACE, "Screenshot", build, on_response)
