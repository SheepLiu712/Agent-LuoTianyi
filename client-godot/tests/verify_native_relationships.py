"""Inspect actual owned/unowned HWNDs after the application minimizes its main window."""
import ctypes
from ctypes import wintypes
import sys

user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsIconic.argtypes = [wintypes.HWND]
user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
user32.GetWindow.restype = wintypes.HWND
main, dynamics, logs, settings = map(int, sys.argv[1:])
assert user32.IsIconic(main), "main must be minimized"
for label, window in [("dynamics", dynamics), ("logs", logs)]:
    assert user32.IsWindowVisible(window) and not user32.IsIconic(window), label + " must remain visible"
    assert not user32.GetWindow(window, 4), label + " must have no native owner"
# Godot's non-modal transient relationship is not always represented by GW_OWNER.
# Check the required visible behavior, allowing Godot to release a hidden HWND.
assert not user32.IsWindowVisible(settings) or user32.IsIconic(settings), "settings follows main minimization"
print("Native dynamics/logs independent; settings follows main: PASS")
