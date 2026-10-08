"""Tray icon by the clock, straight from the Windows API (no extra packages): left-click opens Ghostline,
right-click shows the menu. Runs its message loop on the thread that calls run()."""
import ctypes
from ctypes import wintypes

u32, s32, k32 = ctypes.WinDLL("user32", use_last_error=True), ctypes.WinDLL("shell32"), ctypes.WinDLL("kernel32")
LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
WM_DESTROY, WM_CLOSE, WM_COMMAND, WM_LBUTTONUP, WM_RBUTTONUP, WM_APP = 0x0002, 0x0010, 0x0111, 0x0202, 0x0205, 0x8000
WM_TRAY = WM_APP + 1
NIM_ADD, NIM_MODIFY, NIM_DELETE = 0, 1, 2
NIF_MESSAGE, NIF_ICON, NIF_TIP, NIF_INFO = 0x1, 0x2, 0x4, 0x10
MF_STRING, MF_SEPARATOR, MF_CHECKED, MF_GRAYED = 0x0, 0x800, 0x8, 0x1
TPM_RETURNCMD, TPM_NONOTIFY, TPM_RIGHTBUTTON = 0x100, 0x80, 0x2
IMAGE_ICON, LR_LOADFROMFILE, LR_DEFAULTSIZE = 1, 0x10, 0x40


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("style", wintypes.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH), ("lpszMenuName", wintypes.LPCWSTR),
                ("lpszClassName", wintypes.LPCWSTR), ("hIconSm", wintypes.HICON)]


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND), ("uID", wintypes.UINT), ("uFlags", wintypes.UINT),
                ("uCallbackMessage", wintypes.UINT), ("hIcon", wintypes.HICON), ("szTip", wintypes.WCHAR * 128),
                ("dwState", wintypes.DWORD), ("dwStateMask", wintypes.DWORD), ("szInfo", wintypes.WCHAR * 256),
                ("uVersion", wintypes.UINT), ("szInfoTitle", wintypes.WCHAR * 64), ("dwInfoFlags", wintypes.DWORD),
                ("guidItem", ctypes.c_byte * 16), ("hBalloonIcon", wintypes.HICON)]


u32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
u32.DefWindowProcW.restype = LRESULT
u32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, ctypes.c_int, wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
u32.CreateWindowExW.restype = wintypes.HWND
u32.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT, ctypes.c_int, ctypes.c_int, wintypes.UINT]
u32.LoadImageW.restype = wintypes.HANDLE
u32.AppendMenuW.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_size_t, wintypes.LPCWSTR]
u32.TrackPopupMenu.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND, wintypes.LPVOID]
u32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
s32.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.POINTER(NOTIFYICONDATAW)]
k32.GetModuleHandleW.restype = wintypes.HMODULE


class Tray:
    """menu(): list of (label, callback, checked, enabled) or None for a separator, built fresh on each right-click."""

    def __init__(self, icon_path, tip, on_open, menu):
        self.icon_path, self.tip, self.on_open, self.menu = str(icon_path), tip, on_open, menu
        self.hwnd = None
        self._proc = WNDPROC(self._wndproc)   # keep a reference: Windows calls back into it

    def _nid(self, flags):
        nid = NOTIFYICONDATAW()
        nid.cbSize, nid.hWnd, nid.uID, nid.uFlags, nid.uCallbackMessage = ctypes.sizeof(NOTIFYICONDATAW), self.hwnd, 1, flags, WM_TRAY
        nid.hIcon = self.icon
        nid.szTip = self.tip[:127]
        return nid

    def notify(self, title, text):
        """A one-off Windows notification from the tray icon."""
        if self.hwnd:
            nid = self._nid(NIF_INFO)
            nid.szInfoTitle, nid.szInfo = title[:63], text[:255]
            s32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid))

    def _show_menu(self):
        items = [x for x in self.menu()]
        h = u32.CreatePopupMenu()
        for k, item in enumerate(items, 1):
            if item is None:
                u32.AppendMenuW(h, MF_SEPARATOR, 0, None)
            else:
                label, _, checked, enabled = item
                u32.AppendMenuW(h, MF_STRING | (MF_CHECKED if checked else 0) | (0 if enabled else MF_GRAYED), k, label)
        pt = wintypes.POINT()
        u32.GetCursorPos(ctypes.byref(pt))
        u32.SetForegroundWindow(self.hwnd)   # otherwise the menu doesn't close when clicking elsewhere
        cmd = u32.TrackPopupMenu(h, TPM_RETURNCMD | TPM_NONOTIFY | TPM_RIGHTBUTTON, pt.x, pt.y, 0, self.hwnd, None)
        u32.DestroyMenu(h)
        if cmd and items[cmd - 1]:
            try:
                items[cmd - 1][1]()
            except Exception as e:
                print("tray action failed", e)

    def _wndproc(self, hwnd, msg, wparam, lparam):
        if msg == WM_TRAY:
            if lparam == WM_LBUTTONUP:
                self.on_open()
            elif lparam == WM_RBUTTONUP:
                self._show_menu()
            return 0
        if msg == WM_CLOSE:
            s32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self._nid(0)))
            u32.DestroyWindow(hwnd)
            return 0
        if msg == WM_DESTROY:
            u32.PostQuitMessage(0)
            return 0
        return u32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def run(self):
        hinst = k32.GetModuleHandleW(None)
        wc = WNDCLASSEXW()
        wc.cbSize, wc.lpfnWndProc, wc.hInstance, wc.lpszClassName = ctypes.sizeof(WNDCLASSEXW), self._proc, hinst, "GhostlineTray"
        u32.RegisterClassExW(ctypes.byref(wc))
        self.hwnd = u32.CreateWindowExW(0, "GhostlineTray", "Ghostline", 0, 0, 0, 0, 0, None, None, hinst, None)
        self.icon = u32.LoadImageW(None, self.icon_path, IMAGE_ICON, 0, 0, LR_LOADFROMFILE | LR_DEFAULTSIZE)
        s32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(self._nid(NIF_MESSAGE | NIF_ICON | NIF_TIP)))
        msg = wintypes.MSG()
        while u32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            u32.TranslateMessage(ctypes.byref(msg))
            u32.DispatchMessageW(ctypes.byref(msg))

    def stop(self):
        """Safe from any thread."""
        if self.hwnd:
            u32.PostMessageW(self.hwnd, WM_CLOSE, 0, 0)
