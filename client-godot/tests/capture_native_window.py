"""Capture only the supplied test process's visible native window, including its frame."""
import ctypes
from ctypes import wintypes
from pathlib import Path
import sys
from PIL import ImageGrab

hwnd, expected_pid, destination = int(sys.argv[1]), int(sys.argv[2]), Path(sys.argv[3])
user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.WindowFromPoint.argtypes = [wintypes.POINT]
user32.WindowFromPoint.restype = wintypes.HWND
pid = wintypes.DWORD()
user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
assert pid.value == expected_pid, "window belongs to another process"
bounds = wintypes.RECT()
assert user32.GetWindowRect(hwnd, ctypes.byref(bounds))
dwm = ctypes.WinDLL("dwmapi")
dwm.DwmGetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
dwm.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(bounds), ctypes.sizeof(bounds))
assert bounds.right > bounds.left and bounds.bottom > bounds.top
for x in (bounds.left + 12, (bounds.left + bounds.right) // 2, bounds.right - 12):
    for y in (bounds.top + 12, (bounds.top + bounds.bottom) // 2, bounds.bottom - 12):
        assert user32.WindowFromPoint(wintypes.POINT(x, y)) == hwnd, "test window is obscured or outside the visible desktop"
ImageGrab.grab(bbox=(bounds.left, bounds.top, bounds.right, bounds.bottom), all_screens=True).save(destination)
print("Native test window screenshot: PASS")
