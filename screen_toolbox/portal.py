"""Helpers mínimos para chamar o xdg-desktop-portal via D-Bus (sem dependências extras)."""

import secrets

from gi.repository import Gio, GLib

from . import log

logger = log.get(__name__)

BUS_NAME = "org.freedesktop.portal.Desktop"
OBJECT_PATH = "/org/freedesktop/portal/desktop"
REQUEST_IFACE = "org.freedesktop.portal.Request"
SESSION_IFACE = "org.freedesktop.portal.Session"

# Códigos de resposta do portal
RESPONSE_OK = 0
RESPONSE_CANCELLED = 1
RESPONSE_ERROR = 2
RESPONSE_NAMES = {RESPONSE_OK: "ok", RESPONSE_CANCELLED: "cancelado", RESPONSE_ERROR: "erro"}


class Portal:
    def __init__(self):
        self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        self.sender = self.bus.get_unique_name()[1:].replace(".", "_")
        logger.debug("Conectado ao barramento de sessão como %s", self.bus.get_unique_name())

    @staticmethod
    def new_token(prefix="screentoolbox"):
        return f"{prefix}_{secrets.token_hex(6)}"

    def get_property(self, interface, name, default=None):
        try:
            result = self.bus.call_sync(
                BUS_NAME, OBJECT_PATH, "org.freedesktop.DBus.Properties", "Get",
                GLib.Variant("(ss)", (interface, name)), GLib.VariantType("(v)"),
                Gio.DBusCallFlags.NONE, -1, None,
            )
            return result.unpack()[0]
        except GLib.Error as e:
            logger.debug("Propriedade %s.%s indisponível: %s", interface, name, e.message)
            return default

    def request(self, interface, method, build_args, callback):
        """Chama um método do portal que segue o padrão Request/Response.

        build_args(token) deve retornar o GLib.Variant de parâmetros (já incluindo
        'handle_token': token nas opções). callback(response, results) é chamado
        no loop principal quando o portal responder.
        """
        token = self.new_token()
        short_iface = interface.rsplit(".", 1)[-1]
        request_path = f"/org/freedesktop/portal/desktop/request/{self.sender}/{token}"
        state = {"sub": 0, "done": False}

        def finish(response, results):
            if state["done"]:
                return
            state["done"] = True
            level = logger.debug if response == RESPONSE_OK else (
                logger.info if response == RESPONSE_CANCELLED else logger.error)
            level("Portal %s.%s -> %s%s", short_iface, method, RESPONSE_NAMES.get(response, response),
                  f": {results['error']}" if "error" in results else "")
            if state["sub"]:
                self.bus.signal_unsubscribe(state["sub"])
                state["sub"] = 0
            callback(response, results)

        def on_response(_conn, _sender, _path, _iface, _signal, params):
            response, results = params.unpack()
            finish(response, results)

        # Inscreve antes de chamar, para não perder a resposta (evita corrida).
        state["sub"] = self.bus.signal_subscribe(
            BUS_NAME, REQUEST_IFACE, "Response", request_path, None,
            Gio.DBusSignalFlags.NONE, on_response,
        )

        def on_called(bus, res):
            try:
                bus.call_finish(res)
            except GLib.Error as e:
                finish(RESPONSE_ERROR, {"error": e.message})

        logger.debug("Portal %s.%s (token %s)", short_iface, method, token)
        self.bus.call(
            BUS_NAME, OBJECT_PATH, interface, method, build_args(token),
            GLib.VariantType("(o)"), Gio.DBusCallFlags.NONE, -1, None, on_called,
        )

    def close_session(self, session_handle):
        if not session_handle:
            return
        logger.debug("Fechando sessão do portal %s", session_handle)
        self.bus.call(
            BUS_NAME, session_handle, SESSION_IFACE, "Close", None, None,
            Gio.DBusCallFlags.NONE, -1, None, None,
        )

    def on_session_closed(self, session_handle, callback):
        """Assina o sinal Closed da sessão. Retorna o id da inscrição."""
        def handler(*_args):
            callback()
        return self.bus.signal_subscribe(
            BUS_NAME, SESSION_IFACE, "Closed", session_handle, None,
            Gio.DBusSignalFlags.NONE, handler,
        )


_portal = None


def get_portal():
    global _portal
    if _portal is None:
        _portal = Portal()
    return _portal
