"""Teclado/mouse no Windows via hooks de baixo nível, traduzidos para eventos evdev.

O KeystrokeModel (record/input_events.py) fala a semântica do evdev do Linux; aqui
os eventos do Windows viram (EV_KEY, código evdev, 1/0/2) e (EV_REL, roda, ±1), para
que o modelo e o desenho no vídeo sejam os mesmos nas duas plataformas.
"""

import ctypes
import threading

from .. import log
from . import (HOOKPROC, KBDLLHOOKSTRUCT, MSG, MSLLHOOKSTRUCT, WM_KEYDOWN, WM_KEYUP, WM_LBUTTONDOWN,
               WM_LBUTTONUP, WM_MBUTTONDOWN, WM_MBUTTONUP, WM_MOUSEHWHEEL, WM_MOUSEWHEEL, WM_QUIT,
               WM_RBUTTONDOWN, WM_RBUTTONUP, WM_SYSKEYDOWN, WM_SYSKEYUP, WM_XBUTTONDOWN, WM_XBUTTONUP,
               kernel32, user32)

logger = log.get(__name__)

EV_KEY, EV_REL = 1, 2
REL_HWHEEL, REL_WHEEL = 6, 8
WH_KEYBOARD_LL, WH_MOUSE_LL = 13, 14
LLKHF_EXTENDED = 0x01
FAKE_CTRL_SCAN = 0x200  # Ctrl falso que o Windows envia antes do AltGr

# scancodes com prefixo E0 -> códigos evdev (linux/input-event-codes.h)
EXTENDED = {
    0x1C: 96, 0x1D: 97, 0x35: 98, 0x37: 99, 0x38: 100, 0x47: 102, 0x48: 103, 0x49: 104,
    0x4B: 105, 0x4D: 106, 0x4F: 107, 0x50: 108, 0x51: 109, 0x52: 110, 0x53: 111,
    0x5B: 125, 0x5C: 126, 0x5D: 127,
}
# scancodes sem prefixo fora da faixa 1–88 (onde o set 1 coincide com o evdev)
PLAIN = {0x73: 89, 0x7E: 121}  # ABNT2: "/?" e o ponto do teclado numérico
# teclas identificadas pelo código virtual (sem scancode útil)
BY_VK = {
    0x13: 119,   # Pause
    0x90: 69,    # Num Lock (chega com o mesmo scancode do Pause)
    0xAD: 113, 0xAE: 114, 0xAF: 115,          # mudo, volume −, volume +
    0xB0: 163, 0xB1: 165, 0xB2: 166, 0xB3: 164,  # próxima, anterior, parar, play/pause
}

BTN_LEFT, BTN_RIGHT, BTN_MIDDLE, BTN_SIDE, BTN_EXTRA = 0x110, 0x111, 0x112, 0x113, 0x114
MOUSE_BUTTONS = {
    WM_LBUTTONDOWN: (BTN_LEFT, 1), WM_LBUTTONUP: (BTN_LEFT, 0),
    WM_RBUTTONDOWN: (BTN_RIGHT, 1), WM_RBUTTONUP: (BTN_RIGHT, 0),
    WM_MBUTTONDOWN: (BTN_MIDDLE, 1), WM_MBUTTONUP: (BTN_MIDDLE, 0),
}


def evdev_code(vk, scan, extended):
    """Código evdev de uma tecla do Windows, ou None."""
    if vk in BY_VK:
        return BY_VK[vk]
    if extended:
        return EXTENDED.get(scan)
    if 1 <= scan <= 88:
        return scan
    return PLAIN.get(scan)


def windows_scancode(code):
    """Inverso de evdev_code para teclas comuns: (scancode, estendida) ou None."""
    for scan, value in EXTENDED.items():
        if value == code:
            return scan, True
    for scan, value in PLAIN.items():
        if value == code:
            return scan, False
    if 1 <= code <= 88:
        return code, False
    return None


def _signed_hiword(value):
    word = (value >> 16) & 0xFFFF
    return word - 0x10000 if word & 0x8000 else word


def input_access_ok():
    return True


class InputMonitor(threading.Thread):
    """Mesma interface de record.input_events.InputMonitor: handler(etype, code, value)."""

    def __init__(self, handler):
        super().__init__(name="input-hook", daemon=True)
        self.handler = handler
        self._thread_id = None
        self._ready = threading.Event()
        self._held = set()
        # referências mantidas: o Windows chama estes ponteiros enquanto os hooks existirem
        self._keyboard_proc = HOOKPROC(self._on_keyboard)
        self._mouse_proc = HOOKPROC(self._on_mouse)

    def run(self):
        self._thread_id = kernel32.GetCurrentThreadId()
        module = kernel32.GetModuleHandleW(None)
        keyboard = user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._keyboard_proc, module, 0)
        mouse = user32.SetWindowsHookExW(WH_MOUSE_LL, self._mouse_proc, module, 0)
        self._ready.set()
        if not keyboard or not mouse:
            logger.error("Não foi possível instalar os hooks de teclado/mouse (erro %d)", ctypes.get_last_error())
        else:
            logger.info("Lendo teclado e mouse (hooks do Windows)")
        msg = MSG()
        # os hooks de baixo nível são chamados dentro do loop de mensagens desta thread
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        for hook in (keyboard, mouse):
            if hook:
                user32.UnhookWindowsHookEx(hook)
        logger.debug("Hooks de teclado/mouse removidos")

    def stop(self):
        self._ready.wait(2)
        if self._thread_id is not None:
            user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        self.join(2)

    def _emit(self, etype, code, value):
        try:
            self.handler(etype, code, value)
        except Exception:  # noqa: BLE001
            logger.exception("Erro ao processar evento de entrada")

    # --- hooks (precisam retornar rápido: o Windows remove hooks lentos) --
    def _on_keyboard(self, n_code, w_param, l_param):
        if n_code == 0:
            event = ctypes.cast(l_param, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
            if not event.scanCode & FAKE_CTRL_SCAN:
                code = evdev_code(event.vkCode, event.scanCode & 0xFF, bool(event.flags & LLKHF_EXTENDED))
                if code is not None:
                    if w_param in (WM_KEYDOWN, WM_SYSKEYDOWN):
                        value = 2 if code in self._held else 1  # repetição automática
                        self._held.add(code)
                        self._emit(EV_KEY, code, value)
                    elif w_param in (WM_KEYUP, WM_SYSKEYUP):
                        self._held.discard(code)
                        self._emit(EV_KEY, code, 0)
        return user32.CallNextHookEx(None, n_code, w_param, l_param)

    def _on_mouse(self, n_code, w_param, l_param):
        if n_code == 0:
            if w_param in MOUSE_BUTTONS:
                self._emit(EV_KEY, *MOUSE_BUTTONS[w_param])
            elif w_param in (WM_XBUTTONDOWN, WM_XBUTTONUP):
                event = ctypes.cast(l_param, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
                button = BTN_SIDE if (event.mouseData >> 16) & 0xFFFF == 1 else BTN_EXTRA
                self._emit(EV_KEY, button, 1 if w_param == WM_XBUTTONDOWN else 0)
            elif w_param in (WM_MOUSEWHEEL, WM_MOUSEHWHEEL):
                event = ctypes.cast(l_param, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
                delta = _signed_hiword(event.mouseData)
                if delta:
                    axis = REL_WHEEL if w_param == WM_MOUSEWHEEL else REL_HWHEEL
                    self._emit(EV_REL, axis, 1 if delta > 0 else -1)
        return user32.CallNextHookEx(None, n_code, w_param, l_param)
