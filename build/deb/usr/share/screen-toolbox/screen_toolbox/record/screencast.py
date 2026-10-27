"""Sessão de captura de tela via portal org.freedesktop.portal.ScreenCast + PipeWire."""

import os

from gi.repository import Gio, GLib

from .. import log
from ..portal import BUS_NAME, OBJECT_PATH, RESPONSE_CANCELLED, RESPONSE_OK, get_portal

logger = log.get(__name__)

IFACE = "org.freedesktop.portal.ScreenCast"

SOURCE_MONITOR, SOURCE_WINDOW = 1, 2
CURSOR_HIDDEN, CURSOR_EMBEDDED = 1, 2
PERSIST_UNTIL_REVOKED = 2


class ScreenCastSession:
    def __init__(self):
        self.portal = get_portal()
        self.session_handle = None
        self.fd = None
        self.node_id = None
        self.size = None
        self.restore_token = ""
        self.not_monitor = False
        self._closed_sub = 0

    def start(self, on_ready, on_error, on_closed, show_cursor=True, restore_token="", persist=True):
        """on_ready(fd, node_id, size) | on_error(mensagem ou None se cancelado) | on_closed()"""
        portal = self.portal
        version = portal.get_property(IFACE, "version", 1)
        cursor_modes = portal.get_property(IFACE, "AvailableCursorModes", CURSOR_HIDDEN)
        source_types = portal.get_property(IFACE, "AvailableSourceTypes", SOURCE_MONITOR)
        logger.debug("ScreenCast v%s: fontes=%s cursores=%s", version, source_types, cursor_modes)
        if not source_types & SOURCE_MONITOR:
            logger.warning("O portal não anuncia captura de monitor (fontes=%s); tentando mesmo assim", source_types)
        if version < 4 and persist:
            logger.info("Portal ScreenCast v%s não suporta lembrar a tela escolhida", version)

        def fail(response, results):
            if response == RESPONSE_CANCELLED:
                on_error(None)
            else:
                on_error(results.get("error") or "O portal de captura de tela recusou a solicitação.")
            self.close()

        def create_args(token):
            return GLib.Variant("(a{sv})", ({
                "handle_token": GLib.Variant("s", token),
                "session_handle_token": GLib.Variant("s", portal.new_token("session")),
            },))

        def on_created(response, results):
            if response != RESPONSE_OK:
                return fail(response, results)
            self.session_handle = results["session_handle"]
            logger.info("Sessão de captura criada: %s", self.session_handle)
            self._closed_sub = portal.on_session_closed(self.session_handle, self._on_closed)
            portal.request(IFACE, "SelectSources", select_args, on_selected)

        def select_args(token):
            options = {
                "handle_token": GLib.Variant("s", token),
                # gravação sempre da tela inteira (monitor), nunca de uma janela isolada
                "types": GLib.Variant("u", SOURCE_MONITOR),
                "multiple": GLib.Variant("b", False),
            }
            if version >= 2:
                wanted = CURSOR_EMBEDDED if show_cursor else CURSOR_HIDDEN
                if cursor_modes & wanted:
                    options["cursor_mode"] = GLib.Variant("u", wanted)
                else:
                    logger.warning("Modo de cursor %s não suportado pelo portal (disponíveis: %s)",
                                   wanted, cursor_modes)
            if version >= 4 and persist:
                options["persist_mode"] = GLib.Variant("u", PERSIST_UNTIL_REVOKED)
                if restore_token:
                    options["restore_token"] = GLib.Variant("s", restore_token)
            return GLib.Variant("(oa{sv})", (self.session_handle, options))

        def on_selected(response, results):
            if response != RESPONSE_OK:
                return fail(response, results)
            logger.debug("Fontes selecionadas; iniciando captura")
            portal.request(IFACE, "Start", start_args, on_started)

        def start_args(token):
            return GLib.Variant("(osa{sv})", (self.session_handle, "", {"handle_token": GLib.Variant("s", token)}))

        def on_started(response, results):
            if response != RESPONSE_OK:
                return fail(response, results)
            streams = results.get("streams") or []
            if not streams:
                return fail(2, {"error": "Nenhuma tela foi compartilhada."})
            self.node_id, props = streams[0]
            self.size = props.get("size")
            self.restore_token = results.get("restore_token", "")
            logger.info("Captura iniciada: %d stream(s), nó %s, tamanho %s, tipo de fonte %s",
                        len(streams), self.node_id, self.size, props.get("source_type"))
            if props.get("source_type", SOURCE_MONITOR) != SOURCE_MONITOR:
                # token antigo (de quando janelas eram permitidas): descarta para perguntar de novo
                logger.warning("Fonte restaurada não é uma tela inteira; o token salvo será descartado")
                self.restore_token = ""
                self.not_monitor = True
            if len(streams) > 1:
                logger.warning("Mais de um stream recebido; gravando apenas o primeiro")
            self._open_remote(on_ready, on_error)

        self._on_closed_cb = on_closed
        portal.request(IFACE, "CreateSession", create_args, on_created)

    def _open_remote(self, on_ready, on_error):
        def done(bus, res):
            try:
                result, fd_list = bus.call_with_unix_fd_list_finish(res)
            except GLib.Error as e:
                logger.error("OpenPipeWireRemote falhou: %s", e.message)
                on_error(f"Falha ao conectar ao PipeWire: {e.message}")
                self.close()
                return
            index = result.unpack()[0]
            self.fd = fd_list.get(index)
            logger.debug("Conexão PipeWire aberta (fd %d)", self.fd)
            on_ready(self.fd, self.node_id, self.size)

        self.portal.bus.call_with_unix_fd_list(
            BUS_NAME, OBJECT_PATH, IFACE, "OpenPipeWireRemote",
            GLib.Variant("(oa{sv})", (self.session_handle, {})), GLib.VariantType("(h)"),
            Gio.DBusCallFlags.NONE, -1, None, None, done,
        )

    def _on_closed(self):
        """O usuário encerrou o compartilhamento pelo sistema (ex.: ícone do GNOME)."""
        handle = self.session_handle
        logger.info("Portal sinalizou fim da sessão %s", handle)
        self.session_handle = None
        if handle and self._on_closed_cb:
            self._on_closed_cb()

    def close(self):
        if self._closed_sub:
            self.portal.bus.signal_unsubscribe(self._closed_sub)
            self._closed_sub = 0
        if self.session_handle:
            self.portal.close_session(self.session_handle)
            self.session_handle = None
        if self.fd is not None:
            try:
                os.close(self.fd)
            except OSError as e:
                logger.debug("Falha ao fechar fd do PipeWire: %s", e)
            self.fd = None
