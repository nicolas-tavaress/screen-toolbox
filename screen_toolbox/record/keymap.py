"""Conversão de códigos evdev em rótulos legíveis, usando o layout real do teclado.

Gdk.Display.map_keycode usa o keymap do compositor (Wayland ou X11), então
teclas como Ç, acentos e AltGr respeitam o layout do usuário (ex.: ABNT2).
"""

from gi.repository import Gdk

from .. import log

logger = log.get(__name__)

# Códigos evdev (linux/input-event-codes.h)
KEY_LEFTCTRL, KEY_RIGHTCTRL = 29, 97
KEY_LEFTSHIFT, KEY_RIGHTSHIFT = 42, 54
KEY_LEFTALT, KEY_RIGHTALT = 56, 100
KEY_LEFTMETA, KEY_RIGHTMETA = 125, 126

MODIFIERS = {
    KEY_LEFTCTRL: "Ctrl", KEY_RIGHTCTRL: "Ctrl",
    KEY_LEFTSHIFT: "Shift", KEY_RIGHTSHIFT: "Shift",
    KEY_LEFTALT: "Alt", KEY_RIGHTALT: "AltGr",
    KEY_LEFTMETA: "Super", KEY_RIGHTMETA: "Super",
}
MODIFIER_ORDER = ["Ctrl", "Super", "Alt", "AltGr", "Shift"]

SPECIAL = {
    1: "Esc", 14: "⌫", 15: "Tab", 28: "Enter ⏎", 57: "Espaço", 58: "Caps Lock",
    59: "F1", 60: "F2", 61: "F3", 62: "F4", 63: "F5", 64: "F6", 65: "F7", 66: "F8",
    67: "F9", 68: "F10", 87: "F11", 88: "F12",
    69: "Num Lock", 70: "Scroll Lock", 96: "Enter ⏎", 99: "Print", 119: "Pause",
    102: "Home", 103: "↑", 104: "Page Up", 105: "←", 106: "→", 107: "End",
    108: "↓", 109: "Page Down", 110: "Insert", 111: "Del", 127: "Menu",
    113: "Mudo", 114: "Volume −", 115: "Volume +",
    163: "⏭", 164: "⏯", 165: "⏮", 166: "⏹",
    224: "Brilho −", 225: "Brilho +",
}

BUTTONS = {
    0x110: "Mouse: esquerdo",   # BTN_LEFT
    0x111: "Mouse: direito",    # BTN_RIGHT
    0x112: "Mouse: scroll",     # BTN_MIDDLE (clique na rodinha)
    0x113: "Mouse: trás",       # BTN_SIDE (lateral de trás)
    0x114: "Mouse: frente",     # BTN_EXTRA (lateral da frente)
    0x115: "Mouse: frente",     # BTN_FORWARD
    0x116: "Mouse: trás",       # BTN_BACK
}
DOUBLE_CLICK = "Mouse: esquerdo (duplo)"
SCROLL = "Mouse: scroll"

# teclas que, sozinhas, entram no "texto digitado" do badge
TYPING_KEYS = set(range(2, 14)) | set(range(16, 28)) | set(range(30, 42)) | set(range(43, 54)) | {86}


class KeyLabeler:
    """Pré-calcula o caractere de cada tecla (nível normal, Shift e AltGr).

    Precisa ser criado na thread principal (usa o display GDK).
    """

    def __init__(self):
        self.levels = {}
        display = Gdk.Display.get_default()
        if display is None:
            logger.warning("Sem display GDK: usando nomes genéricos de teclas")
            return
        for code in range(1, 256):
            ok, keys, keyvals = display.map_keycode(code + 8)
            if not ok:
                continue
            by_level = {}
            for key, keyval in zip(keys, keyvals):
                if key.group == 0 and key.level not in by_level:
                    by_level[key.level] = keyval
            self.levels[code] = by_level
        logger.debug("Mapa de teclado carregado: %d teclas", len(self.levels))

    def char(self, code, shift=False, altgr=False):
        """Caractere imprimível da tecla ou None."""
        levels = self.levels.get(code, {})
        level = (2 if altgr else 0) + (1 if shift else 0)
        keyval = levels.get(level)
        if keyval is None and altgr:
            return None
        if keyval is None:
            keyval = levels.get(0)
        if keyval is None:
            return None
        uc = Gdk.keyval_to_unicode(keyval)
        if uc and chr(uc).isprintable() and not chr(uc).isspace():
            return chr(uc)
        # teclas mortas (acentos): mostra o acento
        name = Gdk.keyval_name(keyval) or ""
        if name.startswith("dead_"):
            return {"acute": "´", "grave": "`", "tilde": "~", "circumflex": "^",
                    "diaeresis": "¨", "cedilla": "¸"}.get(name[5:], name[5:])
        return None

    def label(self, code):
        """Rótulo da tecla para combinações (Ctrl + C, Ctrl + ↑...)."""
        if code in SPECIAL:
            return SPECIAL[code]
        ch = self.char(code)
        if ch:
            return ch.upper()
        levels = self.levels.get(code, {})
        if 0 in levels:
            name = Gdk.keyval_name(levels[0])
            if name:
                return name.replace("KP_", "Num ").replace("_", " ")
        return f"Tecla {code}"
