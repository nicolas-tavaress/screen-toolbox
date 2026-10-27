"""Leitura de teclado/mouse direto do kernel (evdev) para exibir no vídeo.

No Wayland não há API para escutar teclas globalmente, então lemos
/dev/input/event* (requer o usuário no grupo `input`). Só fica ativo
enquanto uma gravação com exibição de teclas/cliques está em andamento.
"""

import glob
import os
import select
import struct
import threading
import time

from .. import log
from .keymap import BUTTONS, DOUBLE_CLICK, MODIFIER_ORDER, MODIFIERS, SCROLL, TYPING_KEYS

logger = log.get(__name__)

EV_KEY, EV_REL = 1, 2
REL_HWHEEL, REL_WHEEL = 6, 8
KEY_SPACE = 57

EVENT_FORMAT = "llHHi"
EVENT_SIZE = struct.calcsize(EVENT_FORMAT)

MAX_TEXT = 32
MAX_BADGES = 5
FADE = 0.4


def readable_devices():
    return [p for p in sorted(glob.glob("/dev/input/event*")) if os.access(p, os.R_OK)]


def _device_name(path):
    try:
        with open(f"/sys/class/input/{os.path.basename(path)}/device/name", encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return "?"


def input_access_ok():
    return bool(readable_devices())


class InputMonitor(threading.Thread):
    """Thread que lê eventos de todos os dispositivos e repassa para `handler`."""

    def __init__(self, handler):
        super().__init__(daemon=True, name="evdev-reader")
        self.handler = handler
        self._stop_r, self._stop_w = os.pipe()
        self.fds = []
        self.names = {}
        for path in readable_devices():
            try:
                fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
            except OSError as e:
                logger.warning("Não foi possível abrir %s: %s", path, e)
                continue
            self.fds.append(fd)
            self.names[fd] = path
        # Por privacidade, nunca registramos as teclas em si — só os dispositivos.
        logger.info("Lendo teclado/mouse de %d dispositivo(s)", len(self.fds))
        logger.debug("Dispositivos: %s", ", ".join(f"{p} ({_device_name(p)})" for p in self.names.values()))

    def run(self):
        poller = select.poll()
        for fd in self.fds:
            poller.register(fd, select.POLLIN)
        poller.register(self._stop_r, select.POLLIN)
        try:
            while True:
                for fd, flags in poller.poll():
                    if fd == self._stop_r:
                        return
                    if flags & (select.POLLERR | select.POLLHUP | select.POLLNVAL):
                        logger.info("Dispositivo desconectado: %s", self.names.get(fd))
                        poller.unregister(fd)
                        continue
                    try:
                        data = os.read(fd, EVENT_SIZE * 64)
                    except BlockingIOError:
                        continue
                    except OSError as e:
                        logger.warning("Erro lendo %s: %s", self.names.get(fd), e)
                        poller.unregister(fd)
                        continue
                    for off in range(0, len(data) - EVENT_SIZE + 1, EVENT_SIZE):
                        _s, _us, etype, code, value = struct.unpack_from(EVENT_FORMAT, data, off)
                        if etype in (EV_KEY, EV_REL):
                            self.handler(etype, code, value)
        finally:
            logger.debug("Leitura de dispositivos encerrada")
            for fd in self.fds:
                os.close(fd)
            os.close(self._stop_r)

    def stop(self):
        try:
            os.write(self._stop_w, b"x")
            os.close(self._stop_w)
        except OSError:
            pass


class Badge:
    __slots__ = ("kind", "key", "text", "count", "start", "last")

    def __init__(self, kind, key, text, now):
        self.kind, self.key, self.text = kind, key, text
        self.count = 1
        self.start = self.last = now

    def display(self):
        text = self.text
        if self.kind == "text" and len(text) > MAX_TEXT:
            text = "…" + text[-MAX_TEXT:]
        return f"{text}  ×{self.count}" if self.count > 1 else text


class KeystrokeModel:
    """Transforma eventos crus em 'badges' (Ctrl + C, texto digitado, cliques...)."""

    def __init__(self, labeler, show_keys=True, show_clicks=True, duration=2.0):
        self.labeler = labeler
        self.show_keys = show_keys
        self.show_clicks = show_clicks
        self.duration = duration
        self.lock = threading.Lock()
        self.badges = []
        self.held = {}  # código -> nome do modificador
        self.mod_alone = {}  # modificador pressionado sem outra tecla
        # só contadores (diagnóstico); o conteúdo das teclas nunca é registrado
        self.events = 0
        self.badges_created = 0

    # --- chamado pela thread de leitura ---------------------------------
    def handle(self, etype, code, value):
        with self.lock:
            self.events += 1
            now = time.monotonic()
            if etype == EV_REL:
                if code in (REL_WHEEL, REL_HWHEEL) and self.show_clicks and value:
                    if code == REL_WHEEL:
                        arrow = "↑" if value > 0 else "↓"
                    else:
                        arrow = "→" if value > 0 else "←"
                    self._use_mods()
                    self._push("scroll", (code, value > 0), self._combo(f"{SCROLL} {arrow}"), now)
                return

            if code in MODIFIERS:
                if value == 1:
                    self.held[code] = MODIFIERS[code]
                    self.mod_alone[code] = True
                elif value == 0:
                    name = self.held.pop(code, MODIFIERS[code])
                    if self.mod_alone.pop(code, False) and self.show_keys and name not in ("Shift", "AltGr"):
                        self._push("key", code, name, now)
                return

            if code in BUTTONS:
                if value == 1 and self.show_clicks:
                    self._use_mods()
                    last = self.badges[-1] if self.badges else None
                    if (last and last.kind == "click" and last.key == code
                            and now - last.last < 0.4 and last.count == 1 and code == 0x110):
                        last.text = self._combo(DOUBLE_CLICK)
                        last.last = now
                        return
                    self._push("click", code, self._combo(BUTTONS[code]), now, merge=False)
                return

            if value == 0 or not self.show_keys:
                return
            self._use_mods()
            mods = set(self.held.values())
            command_mods = mods - {"Shift", "AltGr"}

            if not command_mods:
                if code in TYPING_KEYS:
                    ch = self.labeler.char(code, "Shift" in mods, "AltGr" in mods)
                    if ch:
                        self._type(ch, now)
                        return
                if code == KEY_SPACE and self._typing(now):
                    self._type(" ", now)
                    return
            label = self.labeler.label(code)
            self._push("key", code, self._combo(label, include_shift=True), now)

    def _use_mods(self):
        for code in self.mod_alone:
            self.mod_alone[code] = False

    def _combo(self, label, include_shift=True):
        names = []
        for name in MODIFIER_ORDER:
            if name in self.held.values() and (include_shift or name != "Shift"):
                names.append(name)
        return " + ".join(names + [label])

    def _typing(self, now):
        last = self.badges[-1] if self.badges else None
        return last is not None and last.kind == "text" and now - last.last < self.duration

    def _type(self, ch, now):
        if self._typing(now):
            last = self.badges[-1]
            last.text += ch
            last.last = now
        else:
            self._append(Badge("text", None, ch, now))

    def _push(self, kind, key, text, now, merge=True):
        last = self.badges[-1] if self.badges else None
        if merge and last and last.kind == kind and last.key == key and last.text == text \
                and now - last.last < self.duration:
            last.count += 1
            last.last = now
            return
        self._append(Badge(kind, key, text, now))

    def _append(self, badge):
        self.badges_created += 1
        self.badges.append(badge)
        del self.badges[:-MAX_BADGES]

    # --- chamado pelo overlay (thread do GStreamer) ---------------------
    def visible(self):
        """Lista de (texto, opacidade) dos badges ainda visíveis."""
        now = time.monotonic()
        out = []
        with self.lock:
            self.badges = [b for b in self.badges if now - b.last < self.duration + FADE]
            for b in self.badges:
                age = now - b.last
                alpha = 1.0 if age < self.duration else max(0.0, 1 - (age - self.duration) / FADE)
                out.append((b.display(), alpha))
        return out
