"""Rótulos das teclas usando o layout de teclado ativo no Windows (ex.: ABNT2)."""

import ctypes

from .. import log
from ..record.keymap import SPECIAL, KeyLabeler
from . import KEYSTATE, user32
from .input_hook import windows_scancode

logger = log.get(__name__)

MAPVK_VSC_TO_VK_EX = 3
VK_SHIFT, VK_CONTROL, VK_MENU, VK_LSHIFT, VK_LCONTROL, VK_RMENU = 0x10, 0x11, 0x12, 0xA0, 0xA2, 0xA5
TOUNICODE_NO_STATE_CHANGE = 0x4  # não altera o estado de teclas mortas (Windows 10 1607+)


def _active_layout():
    """Layout do teclado da janela em foco (cada thread pode ter o seu)."""
    thread = user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), None)
    return user32.GetKeyboardLayout(thread)


class WinKeyLabeler(KeyLabeler):
    """Mesma interface de KeyLabeler: char(code, shift, altgr) e label(code)."""

    def __init__(self):
        self.levels = {}  # código evdev -> {nível: caractere}
        layout = _active_layout()
        buf = ctypes.create_unicode_buffer(8)
        for code in range(1, 256):
            found = windows_scancode(code)
            if found is None:
                continue
            scan, extended = found
            vk = user32.MapVirtualKeyExW(scan | (0xE000 if extended else 0), MAPVK_VSC_TO_VK_EX, layout)
            if not vk:
                continue
            by_level = {}
            for level in range(4):
                state = KEYSTATE()
                if level & 1:
                    state[VK_SHIFT] = state[VK_LSHIFT] = 0x80
                if level & 2:  # AltGr = Ctrl + Alt direito
                    state[VK_CONTROL] = state[VK_LCONTROL] = state[VK_MENU] = state[VK_RMENU] = 0x80
                count = user32.ToUnicodeEx(vk, scan, ctypes.byref(state), buf, len(buf),
                                           TOUNICODE_NO_STATE_CHANGE, layout)
                # count < 0: tecla morta (acento); o buffer traz o acento isolado
                text = buf.value[:1] if count < 0 else buf.value[:count]
                if len(text) == 1:
                    by_level[level] = text
            self.levels[code] = by_level
        logger.debug("Mapa de teclado carregado (Windows): %d teclas", len(self.levels))

    def char(self, code, shift=False, altgr=False):
        levels = self.levels.get(code, {})
        level = (2 if altgr else 0) + (1 if shift else 0)
        ch = levels.get(level)
        if ch is None and altgr:
            return None
        if ch is None:
            ch = levels.get(0)
        if ch and ch.isprintable() and not ch.isspace():
            return ch
        return None

    def label(self, code):
        if code in SPECIAL:
            return SPECIAL[code]
        ch = self.char(code)
        if ch:
            return ch.upper()
        found = windows_scancode(code)
        if found:
            scan, extended = found
            buf = ctypes.create_unicode_buffer(64)
            if user32.GetKeyNameTextW((scan << 16) | (1 << 24 if extended else 0), buf, len(buf)):
                return buf.value
        return f"Tecla {code}"
