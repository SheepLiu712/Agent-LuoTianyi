"""Check real HWND ownership/taskbar eligibility and independent minimization."""
import ctypes, sys
from ctypes import wintypes
u=ctypes.WinDLL('user32',use_last_error=True)
u.GetWindow.argtypes=[wintypes.HWND,wintypes.UINT]; u.GetWindow.restype=wintypes.HWND
u.GetWindowLongPtrW.argtypes=[wintypes.HWND,ctypes.c_int]; u.GetWindowLongPtrW.restype=ctypes.c_ssize_t
u.IsWindowVisible.argtypes=[wintypes.HWND]; u.IsIconic.argtypes=[wintypes.HWND]
main,dynamics=map(int,sys.argv[1:])
assert main!=dynamics and main and dynamics
assert u.IsIconic(main),'main must actually be minimized'
assert u.IsWindowVisible(dynamics) and not u.IsIconic(dynamics),'dynamics must remain usable'
assert not u.GetWindow(dynamics,4),'dynamics must be unowned for independent taskbar entry'
assert not u.GetWindowLongPtrW(dynamics,-20)&0x80,'dynamics cannot be TOOLWINDOW'
print('Native HWND ownership, taskbar eligibility and independent minimize: PASS')
