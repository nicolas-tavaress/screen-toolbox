"""Ícone na barra superior / bandeja (StatusNotifierItem + menu DBusMenu).

O GTK4 não tem API de bandeja, então o protocolo é implementado direto via D-Bus.
Funciona no KDE nativamente e no GNOME com a extensão AppIndicator (padrão no Ubuntu).
"""

import os
from pathlib import Path

from gi.repository import Gio, GLib

from . import APP_ID, APP_NAME, log

logger = log.get(__name__)

WATCHER_NAME = "org.kde.StatusNotifierWatcher"
WATCHER_PATH = "/StatusNotifierWatcher"
ITEM_PATH = "/StatusNotifierItem"
MENU_PATH = "/MenuBar"

ICON_IDLE = f"{APP_ID}-tray"
ICON_RECORDING = f"{APP_ID}-tray-recording"

SNI_XML = """
<node>
  <interface name="org.kde.StatusNotifierItem">
    <property name="Category" type="s" access="read"/>
    <property name="Id" type="s" access="read"/>
    <property name="Title" type="s" access="read"/>
    <property name="Status" type="s" access="read"/>
    <property name="WindowId" type="i" access="read"/>
    <property name="IconName" type="s" access="read"/>
    <property name="IconThemePath" type="s" access="read"/>
    <property name="OverlayIconName" type="s" access="read"/>
    <property name="AttentionIconName" type="s" access="read"/>
    <property name="ToolTip" type="(sa(iiay)ss)" access="read"/>
    <property name="ItemIsMenu" type="b" access="read"/>
    <property name="Menu" type="o" access="read"/>
    <method name="ContextMenu"><arg name="x" type="i" direction="in"/><arg name="y" type="i" direction="in"/></method>
    <method name="Activate"><arg name="x" type="i" direction="in"/><arg name="y" type="i" direction="in"/></method>
    <method name="SecondaryActivate"><arg name="x" type="i" direction="in"/><arg name="y" type="i" direction="in"/></method>
    <method name="Scroll"><arg name="delta" type="i" direction="in"/><arg name="orientation" type="s" direction="in"/></method>
    <signal name="NewTitle"/>
    <signal name="NewIcon"/>
    <signal name="NewAttentionIcon"/>
    <signal name="NewOverlayIcon"/>
    <signal name="NewToolTip"/>
    <signal name="NewStatus"><arg name="status" type="s"/></signal>
  </interface>
</node>
"""

MENU_XML = """
<node>
  <interface name="com.canonical.dbusmenu">
    <property name="Version" type="u" access="read"/>
    <property name="TextDirection" type="s" access="read"/>
    <property name="Status" type="s" access="read"/>
    <property name="IconThemePath" type="as" access="read"/>
    <method name="GetLayout">
      <arg name="parentId" type="i" direction="in"/>
      <arg name="recursionDepth" type="i" direction="in"/>
      <arg name="propertyNames" type="as" direction="in"/>
      <arg name="revision" type="u" direction="out"/>
      <arg name="layout" type="(ia{sv}av)" direction="out"/>
    </method>
    <method name="GetGroupProperties">
      <arg name="ids" type="ai" direction="in"/>
      <arg name="propertyNames" type="as" direction="in"/>
      <arg name="properties" type="a(ia{sv})" direction="out"/>
    </method>
    <method name="GetProperty">
      <arg name="id" type="i" direction="in"/>
      <arg name="name" type="s" direction="in"/>
      <arg name="value" type="v" direction="out"/>
    </method>
    <method name="Event">
      <arg name="id" type="i" direction="in"/>
      <arg name="eventId" type="s" direction="in"/>
      <arg name="data" type="v" direction="in"/>
      <arg name="timestamp" type="u" direction="in"/>
    </method>
    <method name="EventGroup">
      <arg name="events" type="a(isvu)" direction="in"/>
      <arg name="idErrors" type="ai" direction="out"/>
    </method>
    <method name="AboutToShow">
      <arg name="id" type="i" direction="in"/>
      <arg name="needUpdate" type="b" direction="out"/>
    </method>
    <method name="AboutToShowGroup">
      <arg name="ids" type="ai" direction="in"/>
      <arg name="updatesNeeded" type="ai" direction="out"/>
      <arg name="idErrors" type="ai" direction="out"/>
    </method>
    <signal name="ItemsPropertiesUpdated">
      <arg name="updatedProps" type="a(ia{sv})"/>
      <arg name="removedProps" type="a(ias)"/>
    </signal>
    <signal name="LayoutUpdated">
      <arg name="revision" type="u"/>
      <arg name="parent" type="i"/>
    </signal>
    <signal name="ItemActivationRequested">
      <arg name="id" type="i"/>
      <arg name="timestamp" type="u"/>
    </signal>
  </interface>
</node>
"""

# ids dos itens do menu
CAPTURE, RECORD, SEP1, SHOW, PREFS, SEP2, QUIT = range(1, 8)


def _icon_dir():
    """Pasta onde estão os SVGs do ícone (código-fonte ou instalação)."""
    here = Path(__file__).resolve().parent
    for candidate in (here.parent / "data", here.parents[1] / "icons" / "hicolor" / "scalable" / "apps"):
        if (candidate / f"{ICON_IDLE}.svg").exists():
            return str(candidate)
    return ""


class Tray:
    def __init__(self, app):
        self.app = app
        self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        self.bus_name = f"org.kde.StatusNotifierItem-{os.getpid()}-1"
        self.icon_dir = _icon_dir()
        self.revision = 1
        self.recording = False
        self.record_label = "Gravar tela inteira"
        self.record_enabled = True
        self._ids = []
        self._own_id = 0
        self._watch_id = 0

    # --- ciclo de vida ---------------------------------------------------
    def start(self):
        sni_info = Gio.DBusNodeInfo.new_for_xml(SNI_XML).interfaces[0]
        menu_info = Gio.DBusNodeInfo.new_for_xml(MENU_XML).interfaces[0]
        self._ids.append(self.bus.register_object(ITEM_PATH, sni_info, self._on_sni_call, self._get_sni_prop, None))
        self._ids.append(self.bus.register_object(MENU_PATH, menu_info, self._on_menu_call, self._get_menu_prop, None))
        self._own_id = Gio.bus_own_name_on_connection(self.bus, self.bus_name, Gio.BusNameOwnerFlags.NONE, None, None)
        # registra quando o "watcher" (painel/extensão) existir — inclusive se ele reiniciar depois
        self._watch_id = Gio.bus_watch_name_on_connection(
            self.bus, WATCHER_NAME, Gio.BusNameWatcherFlags.NONE, self._on_watcher_appeared, self._on_watcher_vanished)
        logger.debug("Ícone da bandeja exportado como %s (ícones em %s)", self.bus_name, self.icon_dir or "tema")

    def stop(self):
        for reg_id in self._ids:
            self.bus.unregister_object(reg_id)
        self._ids.clear()
        if self._watch_id:
            Gio.bus_unwatch_name(self._watch_id)
            self._watch_id = 0
        if self._own_id:
            Gio.bus_unown_name(self._own_id)
            self._own_id = 0
        logger.debug("Ícone da bandeja removido")

    def _on_watcher_appeared(self, _conn, _name, _owner):
        def done(bus, res):
            try:
                bus.call_finish(res)
                logger.info("Ícone adicionado à barra superior")
            except GLib.Error as e:
                logger.warning("Não foi possível registrar o ícone na bandeja: %s", e.message)

        self.bus.call(WATCHER_NAME, WATCHER_PATH, WATCHER_NAME, "RegisterStatusNotifierItem",
                      GLib.Variant("(s)", (self.bus_name,)), None, Gio.DBusCallFlags.NONE, -1, None, done)

    def _on_watcher_vanished(self, _conn, _name):
        logger.warning("Sem suporte a ícones na barra superior (StatusNotifierWatcher ausente). No GNOME, "
                       "ative a extensão AppIndicator/KStatusNotifierItem.")

    # --- estado ----------------------------------------------------------
    def update_record_state(self, recording, label, enabled):
        icon_changed = recording != self.recording
        label_changed = (label, enabled) != (self.record_label, self.record_enabled)
        self.recording, self.record_label, self.record_enabled = recording, label, enabled
        if icon_changed:
            self._emit(ITEM_PATH, "org.kde.StatusNotifierItem", "NewIcon", None)
            self._emit(ITEM_PATH, "org.kde.StatusNotifierItem", "NewToolTip", None)
        if label_changed:
            props = GLib.Variant("a(ia{sv})", [(RECORD, self._item_props(RECORD))])
            self._emit(MENU_PATH, "com.canonical.dbusmenu", "ItemsPropertiesUpdated",
                       GLib.Variant.new_tuple(props, GLib.Variant("a(ias)", [])))

    def _emit(self, path, iface, signal, params):
        try:
            self.bus.emit_signal(None, path, iface, signal, params)
        except GLib.Error as e:
            logger.debug("Falha ao emitir %s: %s", signal, e.message)

    # --- StatusNotifierItem ----------------------------------------------
    def _get_sni_prop(self, _conn, _sender, _path, _iface, name):
        tooltip = "Gravando…" if self.recording else "Prints e gravação de tela"
        values = {
            "Category": GLib.Variant("s", "ApplicationStatus"),
            "Id": GLib.Variant("s", APP_ID),
            "Title": GLib.Variant("s", APP_NAME),
            "Status": GLib.Variant("s", "Active"),
            "WindowId": GLib.Variant("i", 0),
            "IconName": GLib.Variant("s", ICON_RECORDING if self.recording else ICON_IDLE),
            "IconThemePath": GLib.Variant("s", self.icon_dir),
            "OverlayIconName": GLib.Variant("s", ""),
            "AttentionIconName": GLib.Variant("s", ICON_RECORDING),
            "ToolTip": GLib.Variant("(sa(iiay)ss)", ("", [], APP_NAME, tooltip)),
            "ItemIsMenu": GLib.Variant("b", False),
            "Menu": GLib.Variant("o", MENU_PATH),
        }
        return values.get(name)

    def _on_sni_call(self, _conn, _sender, _path, _iface, method, _params, invocation):
        if method == "Activate":
            logger.info("Ícone da bandeja clicado: abrindo janela")
            GLib.idle_add(lambda: self.app.activate() and False)
        elif method == "SecondaryActivate":
            GLib.idle_add(lambda: self.app.capture() and False)
        invocation.return_value(None)

    # --- DBusMenu --------------------------------------------------------
    def _items(self):
        return [CAPTURE, RECORD, SEP1, SHOW, PREFS, SEP2, QUIT]

    def _item_props(self, item_id):
        labels = {
            CAPTURE: "Capturar área",
            RECORD: self.record_label,
            SHOW: "Abrir janela",
            PREFS: "Preferências",
            QUIT: "Sair",
        }
        if item_id in (SEP1, SEP2):
            return {"type": GLib.Variant("s", "separator")}
        props = {"label": GLib.Variant("s", labels[item_id]), "visible": GLib.Variant("b", True)}
        enabled = True
        if item_id == RECORD:
            enabled = self.record_enabled
        elif item_id in (CAPTURE, QUIT):
            enabled = not self.recording
        props["enabled"] = GLib.Variant("b", enabled)
        return props

    def _layout(self):
        children = [GLib.Variant("(ia{sv}av)", (i, self._item_props(i), [])) for i in self._items()]
        return GLib.Variant("(ia{sv}av)", (0, {"children-display": GLib.Variant("s", "submenu")}, children))

    def _get_menu_prop(self, _conn, _sender, _path, _iface, name):
        values = {
            "Version": GLib.Variant("u", 3),
            "TextDirection": GLib.Variant("s", "ltr"),
            "Status": GLib.Variant("s", "normal"),
            "IconThemePath": GLib.Variant("as", [self.icon_dir] if self.icon_dir else []),
        }
        return values.get(name)

    def _on_menu_call(self, _conn, _sender, _path, _iface, method, params, invocation):
        if method == "GetLayout":
            invocation.return_value(GLib.Variant.new_tuple(GLib.Variant("u", self.revision), self._layout()))
        elif method == "GetGroupProperties":
            ids, _names = params.unpack()
            ids = ids or self._items()
            result = [(i, self._item_props(i)) for i in ids if i in self._items()]
            invocation.return_value(GLib.Variant("(a(ia{sv}))", (result,)))
        elif method == "GetProperty":
            item_id, name = params.unpack()
            value = self._item_props(item_id).get(name, GLib.Variant("s", ""))
            invocation.return_value(GLib.Variant("(v)", (value,)))
        elif method == "Event":
            item_id, event_id, _data, _ts = params.unpack()
            if event_id == "clicked":
                GLib.idle_add(self._on_item_clicked, item_id)
            invocation.return_value(None)
        elif method == "EventGroup":
            events = params.unpack()[0]
            for item_id, event_id, _data, _ts in events:
                if event_id == "clicked":
                    GLib.idle_add(self._on_item_clicked, item_id)
            invocation.return_value(GLib.Variant("(ai)", ([],)))
        elif method == "AboutToShow":
            invocation.return_value(GLib.Variant("(b)", (False,)))
        elif method == "AboutToShowGroup":
            invocation.return_value(GLib.Variant("(aiai)", ([], [])))
        else:
            invocation.return_dbus_error("org.freedesktop.DBus.Error.UnknownMethod", method)

    def _on_item_clicked(self, item_id):
        names = {CAPTURE: "capturar", RECORD: "gravar/parar", SHOW: "abrir janela", PREFS: "preferências", QUIT: "sair"}
        logger.info("Menu da bandeja: %s", names.get(item_id, item_id))
        if item_id == CAPTURE:
            self.app.capture()
        elif item_id == RECORD:
            self.app.toggle_recording()
        elif item_id == SHOW:
            self.app.activate()
        elif item_id == PREFS:
            self.app.show_preferences()
        elif item_id == QUIT:
            self.app.request_quit()
        return False
