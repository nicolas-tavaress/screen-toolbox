"""Integração com o Windows via ctypes (sem dependências extras).

Só deve ser importado no Windows. Todas as funções usadas têm argtypes/restype
declarados: no Windows 64 bits, handles são ponteiros e o restype padrão (int)
os truncaria.
"""

import ctypes
from ctypes import wintypes as w

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)

LRESULT = w.LPARAM
ULONG_PTR = w.WPARAM
HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, w.WPARAM, w.LPARAM)
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, w.HWND, w.UINT, w.WPARAM, w.LPARAM)
MONITORENUMPROC = ctypes.WINFUNCTYPE(w.BOOL, w.HMONITOR, w.HDC, ctypes.POINTER(w.RECT), w.LPARAM)
KEYSTATE = ctypes.c_ubyte * 256

# mensagens
WM_NULL = 0x0000
WM_DESTROY = 0x0002
WM_CLOSE = 0x0010
WM_QUIT = 0x0012
WM_CONTEXTMENU = 0x007B
WM_KEYDOWN, WM_KEYUP, WM_SYSKEYDOWN, WM_SYSKEYUP = 0x0100, 0x0101, 0x0104, 0x0105
WM_HOTKEY = 0x0312
WM_LBUTTONDOWN, WM_LBUTTONUP = 0x0201, 0x0202
WM_RBUTTONDOWN, WM_RBUTTONUP = 0x0204, 0x0205
WM_MBUTTONDOWN, WM_MBUTTONUP = 0x0207, 0x0208
WM_MOUSEWHEEL = 0x020A
WM_XBUTTONDOWN, WM_XBUTTONUP = 0x020B, 0x020C
WM_MOUSEHWHEEL = 0x020E
WM_APP = 0x8000


class MSG(ctypes.Structure):
    _fields_ = [("hwnd", w.HWND), ("message", w.UINT), ("wParam", w.WPARAM), ("lParam", w.LPARAM),
                ("time", w.DWORD), ("pt", w.POINT), ("lPrivate", w.DWORD)]


class MONITORINFOEXW(ctypes.Structure):
    _fields_ = [("cbSize", w.DWORD), ("rcMonitor", w.RECT), ("rcWork", w.RECT), ("dwFlags", w.DWORD),
                ("szDevice", w.WCHAR * 32)]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", w.DWORD), ("biWidth", w.LONG), ("biHeight", w.LONG), ("biPlanes", w.WORD),
                ("biBitCount", w.WORD), ("biCompression", w.DWORD), ("biSizeImage", w.DWORD),
                ("biXPelsPerMeter", w.LONG), ("biYPelsPerMeter", w.LONG), ("biClrUsed", w.DWORD),
                ("biClrImportant", w.DWORD)]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", w.DWORD * 3)]


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("vkCode", w.DWORD), ("scanCode", w.DWORD), ("flags", w.DWORD), ("time", w.DWORD),
                ("dwExtraInfo", ULONG_PTR)]


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("pt", w.POINT), ("mouseData", w.DWORD), ("flags", w.DWORD), ("time", w.DWORD),
                ("dwExtraInfo", ULONG_PTR)]


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [("cbSize", w.UINT), ("style", w.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int), ("hInstance", w.HINSTANCE), ("hIcon", w.HICON),
                ("hCursor", w.HANDLE), ("hbrBackground", w.HBRUSH), ("lpszMenuName", w.LPCWSTR),
                ("lpszClassName", w.LPCWSTR), ("hIconSm", w.HICON)]


class GUID(ctypes.Structure):
    _fields_ = [("Data1", w.DWORD), ("Data2", w.WORD), ("Data3", w.WORD), ("Data4", w.BYTE * 8)]


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [("cbSize", w.DWORD), ("hWnd", w.HWND), ("uID", w.UINT), ("uFlags", w.UINT),
                ("uCallbackMessage", w.UINT), ("hIcon", w.HICON), ("szTip", w.WCHAR * 128),
                ("dwState", w.DWORD), ("dwStateMask", w.DWORD), ("szInfo", w.WCHAR * 256),
                ("uVersion", w.UINT), ("szInfoTitle", w.WCHAR * 64), ("dwInfoFlags", w.DWORD),
                ("guidItem", GUID), ("hBalloonIcon", w.HICON)]


def _sig(func, restype, *argtypes):
    func.restype = restype
    func.argtypes = argtypes


# user32
_sig(user32.GetSystemMetrics, ctypes.c_int, ctypes.c_int)
_sig(user32.GetDC, w.HDC, w.HWND)
_sig(user32.ReleaseDC, ctypes.c_int, w.HWND, w.HDC)
_sig(user32.EnumDisplayMonitors, w.BOOL, w.HDC, ctypes.POINTER(w.RECT), MONITORENUMPROC, w.LPARAM)
_sig(user32.GetMonitorInfoW, w.BOOL, w.HMONITOR, ctypes.POINTER(MONITORINFOEXW))
_sig(user32.SetWindowsHookExW, w.HHOOK, ctypes.c_int, HOOKPROC, w.HINSTANCE, w.DWORD)
_sig(user32.CallNextHookEx, LRESULT, w.HHOOK, ctypes.c_int, w.WPARAM, w.LPARAM)
_sig(user32.UnhookWindowsHookEx, w.BOOL, w.HHOOK)
_sig(user32.GetMessageW, w.BOOL, ctypes.POINTER(MSG), w.HWND, w.UINT, w.UINT)
_sig(user32.TranslateMessage, w.BOOL, ctypes.POINTER(MSG))
_sig(user32.DispatchMessageW, LRESULT, ctypes.POINTER(MSG))
_sig(user32.PostThreadMessageW, w.BOOL, w.DWORD, w.UINT, w.WPARAM, w.LPARAM)
_sig(user32.PostMessageW, w.BOOL, w.HWND, w.UINT, w.WPARAM, w.LPARAM)
_sig(user32.PostQuitMessage, None, ctypes.c_int)
_sig(user32.RegisterClassExW, w.ATOM, ctypes.POINTER(WNDCLASSEXW))
_sig(user32.UnregisterClassW, w.BOOL, w.LPCWSTR, w.HINSTANCE)
_sig(user32.CreateWindowExW, w.HWND, w.DWORD, w.LPCWSTR, w.LPCWSTR, w.DWORD, ctypes.c_int, ctypes.c_int,
     ctypes.c_int, ctypes.c_int, w.HWND, w.HMENU, w.HINSTANCE, w.LPVOID)
_sig(user32.DefWindowProcW, LRESULT, w.HWND, w.UINT, w.WPARAM, w.LPARAM)
_sig(user32.DestroyWindow, w.BOOL, w.HWND)
_sig(user32.RegisterHotKey, w.BOOL, w.HWND, ctypes.c_int, w.UINT, w.UINT)
_sig(user32.UnregisterHotKey, w.BOOL, w.HWND, ctypes.c_int)
_sig(user32.CreatePopupMenu, w.HMENU)
_sig(user32.AppendMenuW, w.BOOL, w.HMENU, w.UINT, ULONG_PTR, w.LPCWSTR)
_sig(user32.TrackPopupMenu, w.BOOL, w.HMENU, w.UINT, ctypes.c_int, ctypes.c_int, ctypes.c_int, w.HWND,
     ctypes.POINTER(w.RECT))
_sig(user32.DestroyMenu, w.BOOL, w.HMENU)
_sig(user32.GetCursorPos, w.BOOL, ctypes.POINTER(w.POINT))
_sig(user32.SetForegroundWindow, w.BOOL, w.HWND)
_sig(user32.GetForegroundWindow, w.HWND)
_sig(user32.GetWindowThreadProcessId, w.DWORD, w.HWND, ctypes.POINTER(w.DWORD))
_sig(user32.LoadImageW, w.HANDLE, w.HINSTANCE, w.LPCWSTR, w.UINT, ctypes.c_int, ctypes.c_int, w.UINT)
_sig(user32.DestroyIcon, w.BOOL, w.HICON)
_sig(user32.RegisterWindowMessageW, w.UINT, w.LPCWSTR)
_sig(user32.GetKeyboardLayout, w.HKL, w.DWORD)
_sig(user32.MapVirtualKeyExW, w.UINT, w.UINT, w.UINT, w.HKL)
_sig(user32.ToUnicodeEx, ctypes.c_int, w.UINT, w.UINT, ctypes.POINTER(KEYSTATE), w.LPWSTR, ctypes.c_int,
     w.UINT, w.HKL)
_sig(user32.GetKeyNameTextW, ctypes.c_int, w.LONG, w.LPWSTR, ctypes.c_int)

# gdi32
_sig(gdi32.CreateCompatibleDC, w.HDC, w.HDC)
_sig(gdi32.CreateDIBSection, w.HBITMAP, w.HDC, ctypes.POINTER(BITMAPINFO), w.UINT,
     ctypes.POINTER(ctypes.c_void_p), w.HANDLE, w.DWORD)
_sig(gdi32.SelectObject, w.HGDIOBJ, w.HDC, w.HGDIOBJ)
_sig(gdi32.BitBlt, w.BOOL, w.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, w.HDC,
     ctypes.c_int, ctypes.c_int, w.DWORD)
_sig(gdi32.DeleteObject, w.BOOL, w.HGDIOBJ)
_sig(gdi32.DeleteDC, w.BOOL, w.HDC)

# kernel32
_sig(kernel32.GetModuleHandleW, w.HMODULE, w.LPCWSTR)
_sig(kernel32.GetCurrentThreadId, w.DWORD)

# shell32
_sig(shell32.Shell_NotifyIconW, w.BOOL, w.DWORD, ctypes.POINTER(NOTIFYICONDATAW))


def enable_dpi_awareness():
    """Coordenadas em pixels físicos em todos os monitores (o GTK4 também pede isso;
    chamar antes garante o modo certo mesmo que a ordem de inicialização mude)."""
    try:
        per_monitor_v2 = ctypes.c_void_p(-4)
        user32.SetProcessDpiAwarenessContext.restype = w.BOOL
        user32.SetProcessDpiAwarenessContext.argtypes = (ctypes.c_void_p,)
        user32.SetProcessDpiAwarenessContext(per_monitor_v2)
    except (AttributeError, OSError):
        pass


def last_error():
    return ctypes.WinError(ctypes.get_last_error())
