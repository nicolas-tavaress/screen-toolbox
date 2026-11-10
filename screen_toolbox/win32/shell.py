"""Ícone na bandeja, atalhos globais e notificações no Windows.

Uma thread própria mantém uma janela oculta com loop de mensagens: ela recebe os
cliques no ícone (Shell_NotifyIcon), os atalhos (RegisterHotKey) e os cliques nos
balões. Tudo que mexe no app volta para a thread principal via GLib.idle_add.
Mesma interface de tray.Tray, mais notify().
"""

import ctypes
import threading
from ctypes import wintypes
from pathlib import Path

from gi.repository import GLib

from .. import APP_ID, APP_NAME, log
from . import (MSG, NOTIFYICONDATAW, WM_APP, WM_CLOSE, WM_CONTEXTMENU, WM_DESTROY, WM_HOTKEY, WM_NULL,
               WNDCLASSEXW, WNDPROC, kernel32, shell32, user32)

logger = log.get(__name__)

NIM_ADD, NIM_MODIFY, NIM_DELETE, NIM_SETVERSION = 0, 1, 2, 4
NIF_MESSAGE, NIF_ICON, NIF_TIP, NIF_INFO, NIF_SHOWTIP = 0x01, 0x02, 0x04, 0x10, 0x80
NIIF_INFO, NIIF_NOSOUND = 0x01, 0x10
NOTIFYICON_VERSION_4 = 4
NIN_SELECT, NIN_KEYSELECT, NIN_BALLOONUSERCLICK = 0x0400, 0x0401, 0x0405
IMAGE_ICON, LR_LOADFROMFILE, LR_DEFAULTSIZE = 1, 0x10, 0x40
MF_STRING, MF_GRAYED, MF_SEPARATOR = 0x0, 0x1, 0x800
TPM_RIGHTBUTTON, TPM_NONOTIFY, TPM_RETURNCMD = 0x2, 0x80, 0x100
MOD_ALT, MOD_CONTROL, MOD_NOREPEAT = 0x1, 0x2, 0x4000

WM_TRAY = WM_APP + 1     # callback do ícone
WM_REFRESH = WM_APP + 2  # atualizar ícone/dica (pedido de outra thread)
WM_BALLOON = WM_APP + 3  # mostrar balão (pedido de outra thread)

ICON_IDLE = f"{APP_ID}-tray"
ICON_RECORDING = f"{APP_ID}-tray-recording"

# ids dos itens do menu (mesmos de tray.py)
CAPTURE, RECORD, SHOW, PREFS, QUIT = 1, 2, 4, 5, 7

# atalhos globais: id -> (modificadores, tecla virtual, texto, ação)
HOTKEYS = {
    1: (MOD_CONTROL | MOD_ALT, ord("S"), "Ctrl+Alt+S", "capture"),
    2: (MOD_CONTROL | MOD_ALT, ord("R"), "Ctrl+Alt+R", "toggle_recording"),
}
HOTKEY_LABELS = [("Capturar área", HOTKEYS[1][2]), ("Iniciar/parar gravação", HOTKEYS[2][2])]


def _icon_path(name):
    data = Path(__file__).resolve().parents[2] / "data"
    path = data / f"{name}.ico"
    return str(path) if path.exists() else None


class Tray:
    def __init__(self, app):
        self.app = app
        self.recording = False
        self.record_label = "Gravar tela inteira"
        self.record_enabled = True
        self.hwnd = None
        self._lock = threading.Lock()
        self._balloon = None  # (título, texto)
        self._balloon_action = None  # (ação, alvo) do último balão
        self._thread = None
        self._ready = threading.Event()
        self._icons = {}
        self._failed_hotkeys = []
        self._taskbar_created = None  # mensagem registrada em _run
        self._wndproc = WNDPROC(self._on_message)  # referência mantida
        self._class_name = f"ScreenToolboxTray{id(self)}"

    # --- ciclo de vida ---------------------------------------------------
    def start(self):
        self._thread = threading.Thread(target=self._run, name="tray", daemon=True)
        self._thread.start()
        self._ready.wait(5)

    def stop(self):
        if self.hwnd:
            user32.PostMessageW(self.hwnd, WM_CLOSE, 0, 0)
        if self._thread is not None:
            self._thread.join(3)
            self._thread = None
        logger.debug("Ícone da bandeja removido")

    def _run(self):
        instance = kernel32.GetModuleHandleW(None)
        wc = WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
        wc.lpfnWndProc = self._wndproc
        wc.hInstance = instance
        wc.lpszClassName = self._class_name
        if not user32.RegisterClassExW(ctypes.byref(wc)):
            logger.error("Bandeja: RegisterClassExW falhou (erro %d)", ctypes.get_last_error())
            self._ready.set()
            return
        # janela comum (não "message-only"), para receber o aviso TaskbarCreated
        self.hwnd = user32.CreateWindowExW(0, self._class_name, APP_NAME, 0, 0, 0, 0, 0,
                                           None, None, instance, None)
        if not self.hwnd:
            logger.error("Bandeja: CreateWindowExW falhou (erro %d)", ctypes.get_last_error())
            self._ready.set()
            return
        self._taskbar_created = user32.RegisterWindowMessageW("TaskbarCreated")
        for name in (ICON_IDLE, ICON_RECORDING):
            path = _icon_path(name)
            if path:
                self._icons[name] = user32.LoadImageW(None, path, IMAGE_ICON, 0, 0,
                                                      LR_LOADFROMFILE | LR_DEFAULTSIZE)
        self._add_icon()
        self._register_hotkeys()
        self._ready.set()

        msg = MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        for icon in self._icons.values():
            if icon:
                user32.DestroyIcon(icon)
        user32.UnregisterClassW(self._class_name, instance)

    def _register_hotkeys(self):
        for hotkey_id, (mods, vk, text, _action) in HOTKEYS.items():
            if user32.RegisterHotKey(self.hwnd, hotkey_id, mods | MOD_NOREPEAT, vk):
                logger.info("Atalho global registrado: %s", text)
            else:
                logger.warning("Atalho %s já está em uso por outro programa", text)
                self._failed_hotkeys.append(text)
        if self._failed_hotkeys:
            message = f"Atalho em uso por outro programa: {', '.join(self._failed_hotkeys)}"
            GLib.idle_add(lambda: self.app.notify_user(message) and False)

    # --- ícone -----------------------------------------------------------
    def _data(self, flags):
        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = self.hwnd
        nid.uID = 1
        nid.uFlags = flags
        return nid

    def _add_icon(self):
        nid = self._data(NIF_MESSAGE | NIF_ICON | NIF_TIP | NIF_SHOWTIP)
        nid.uCallbackMessage = WM_TRAY
        self._fill_icon(nid)
        if not shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid)):
            logger.warning("Não foi possível adicionar o ícone na bandeja")
            return
        nid.uVersion = NOTIFYICON_VERSION_4
        shell32.Shell_NotifyIconW(NIM_SETVERSION, ctypes.byref(nid))
        logger.info("Ícone adicionado à bandeja")

    def _fill_icon(self, nid):
        with self._lock:
            recording = self.recording
        nid.hIcon = self._icons.get(ICON_RECORDING if recording else ICON_IDLE) or None
        nid.szTip = f"{APP_NAME} — gravando…" if recording else f"{APP_NAME} — prints e gravação de tela"

    def _refresh_icon(self):
        nid = self._data(NIF_ICON | NIF_TIP | NIF_SHOWTIP)
        self._fill_icon(nid)
        shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid))

    def _show_balloon(self):
        with self._lock:
            pending, self._balloon = self._balloon, None
        if pending is None:
            return
        title, text = pending
        nid = self._data(NIF_INFO)
        nid.szInfoTitle = title[:63]
        nid.szInfo = text[:255]
        nid.dwInfoFlags = NIIF_INFO | NIIF_NOSOUND
        shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid))

    # --- interface usada pelo app (thread principal) ----------------------
    def update_record_state(self, recording, label, enabled):
        with self._lock:
            icon_changed = recording != self.recording
            self.recording, self.record_label, self.record_enabled = recording, label, enabled
        if icon_changed and self.hwnd:
            user32.PostMessageW(self.hwnd, WM_REFRESH, 0, 0)

    def notify(self, text, action=None, target=None):
        """Balão de notificação; clicar nele executa a ação (ex.: app.open-file)."""
        with self._lock:
            self._balloon = (APP_NAME, text)
            self._balloon_action = (action, target) if action else None
        if self.hwnd:
            user32.PostMessageW(self.hwnd, WM_BALLOON, 0, 0)

    # --- mensagens (thread da bandeja) ------------------------------------
    def _on_message(self, hwnd, msg, w_param, l_param):
        try:
            if msg == WM_TRAY:
                self._on_tray_event(l_param & 0xFFFF)
                return 0
            if msg == WM_HOTKEY:
                action = HOTKEYS.get(w_param, (0, 0, "", None))[3]
                if action:
                    logger.info("Atalho global: %s", HOTKEYS[w_param][2])
                    GLib.idle_add(lambda: getattr(self.app, action)() and False)
                return 0
            if msg == WM_REFRESH:
                self._refresh_icon()
                return 0
            if msg == WM_BALLOON:
                self._show_balloon()
                return 0
            if msg == self._taskbar_created:
                logger.info("Barra de tarefas reiniciada; adicionando o ícone de novo")
                self._add_icon()
                return 0
            if msg == WM_CLOSE:
                user32.DestroyWindow(hwnd)
                return 0
            if msg == WM_DESTROY:
                shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self._data(0)))
                for hotkey_id in HOTKEYS:
                    user32.UnregisterHotKey(hwnd, hotkey_id)
                self.hwnd = None
                user32.PostQuitMessage(0)
                return 0
        except Exception:  # noqa: BLE001
            logger.exception("Erro na bandeja (mensagem 0x%x)", msg)
        return user32.DefWindowProcW(hwnd, msg, w_param, l_param)

    def _on_tray_event(self, event):
        if event in (NIN_SELECT, NIN_KEYSELECT):
            logger.info("Ícone da bandeja clicado: abrindo janela")
            GLib.idle_add(lambda: self.app.activate() and False)
        elif event == WM_CONTEXTMENU:
            self._show_menu()
        elif event == NIN_BALLOONUSERCLICK:
            with self._lock:
                pending = self._balloon_action
            if pending:
                action, target = pending
                GLib.idle_add(self._run_action, action, target)

    def _run_action(self, action, target):
        name = action.removeprefix("app.")
        self.app.activate_action(name, target)
        return False

    def _show_menu(self):
        with self._lock:
            recording, label, enabled = self.recording, self.record_label, self.record_enabled
        menu = user32.CreatePopupMenu()
        items = [
            (CAPTURE, "Capturar área\tCtrl+Alt+S", not recording),
            (RECORD, f"{label}\tCtrl+Alt+R", enabled),
            None,
            (SHOW, "Abrir janela", True),
            (PREFS, "Preferências", True),
            None,
            (QUIT, "Sair", not recording),
        ]
        for item in items:
            if item is None:
                user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
            else:
                item_id, text, active = item
                user32.AppendMenuW(menu, MF_STRING | (0 if active else MF_GRAYED), item_id, text)
        point = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(point))
        # sem isso o menu não fecha ao clicar fora
        user32.SetForegroundWindow(self.hwnd)
        chosen = user32.TrackPopupMenu(menu, TPM_RIGHTBUTTON | TPM_NONOTIFY | TPM_RETURNCMD,
                                       point.x, point.y, 0, self.hwnd, None)
        user32.PostMessageW(self.hwnd, WM_NULL, 0, 0)
        user32.DestroyMenu(menu)
        if chosen:
            GLib.idle_add(self._on_item_clicked, chosen)

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
