"""Drive only the supplied test HWND. Real mouse/keyboard events verify Godot chrome."""
import ctypes
from ctypes import wintypes
import json
from pathlib import Path
import sys
import time

hwnd, expected_pid, destination = int(sys.argv[1]), int(sys.argv[2]), Path(sys.argv[3])
u = ctypes.WinDLL("user32", use_last_error=True)
u.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
u.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
u.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
u.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
u.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
u.SetForegroundWindow.argtypes = [wintypes.HWND]
u.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
u.IsIconic.argtypes = [wintypes.HWND]
u.IsZoomed.argtypes = [wintypes.HWND]
u.IsWindowVisible.argtypes = [wintypes.HWND]
u.WindowFromPoint.argtypes = [wintypes.POINT]
u.WindowFromPoint.restype = wintypes.HWND
u.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
u.MonitorFromWindow.restype = wintypes.HANDLE
u.mouse_event.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_size_t]
checks = []
probe = {}
probe["hwnd"] = hwnd


class MonitorInfo(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("monitor", wintypes.RECT), ("work", wintypes.RECT), ("flags", wintypes.DWORD)]


class TitleBarInfo(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("title", wintypes.RECT), ("states", wintypes.DWORD * 6), ("rectangles", wintypes.RECT * 6)]


def system_button(index):
    owned()
    info = TitleBarInfo()
    info.size = ctypes.sizeof(info)
    u.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    u.SendMessageW(hwnd, 0x033F, 0, ctypes.addressof(info))
    bounds = info.rectangles[index]
    assert bounds.right > bounds.left and bounds.bottom > bounds.top, "system caption button must be present"
    return ((bounds.left + bounds.right) / 2, (bounds.top + bounds.bottom) / 2)


def fills_work_area():
    info = MonitorInfo()
    info.size = ctypes.sizeof(info)
    u.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MonitorInfo)]
    assert u.GetMonitorInfoW(u.MonitorFromWindow(hwnd, 2), ctypes.byref(info))
    actual = rect()
    return all(abs(a-b) < 16 for a, b in zip(actual, (info.work.left, info.work.top, info.work.right, info.work.bottom)))


def owned():
    pid = wintypes.DWORD()
    u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    assert pid.value == expected_pid, "test HWND no longer belongs to the launched engine"


def rect():
    owned()
    value = wintypes.RECT()
    assert u.GetWindowRect(hwnd, ctypes.byref(value))
    return (value.left, value.top, value.right, value.bottom)


def wait_for(predicate, label):
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        if predicate():
            checks.append(label)
            return
        time.sleep(.025)
    raise AssertionError(label)


def click(x, y):
    owned()
    u.SetCursorPos(int(x), int(y))
    u.mouse_event(2, 0, 0, 0, 0)
    time.sleep(.035)
    u.mouse_event(4, 0, 0, 0, 0)


def drag(start, offset):
    owned()
    probe["foreground_request_ok"] = bool(u.SetForegroundWindow(hwnd))
    probe["set_cursor_ok"] = bool(u.SetCursorPos(*map(int, start)))
    probe["cursor_error"] = ctypes.get_last_error()
    point = wintypes.POINT()
    u.GetCursorPos(ctypes.byref(point))
    probe["cursor"] = [point.x, point.y]
    probe["target"] = list(start)
    probe["foreground"] = int(u.GetForegroundWindow())
    u.mouse_event(2, 0, 0, 0, 0)
    time.sleep(.08)
    for step in range(1, 7):
        u.SetCursorPos(int(start[0] + offset[0] * step / 6), int(start[1] + offset[1] * step / 6))
        time.sleep(.025)
    u.mouse_event(4, 0, 0, 0, 0)
    time.sleep(.12)


try:
    owned()
    u.ShowWindow(hwnd, 9)
    u.SetForegroundWindow(hwnd)
    time.sleep(.2)
    before = rect()
    probe["window_at_body"] = u.WindowFromPoint(wintypes.POINT((before[0]+before[2])//2,(before[1]+before[3])//2))
    if probe["window_at_body"] != hwnd:
        raise RuntimeError("input target is obscured by another desktop window")
    click((before[0]+before[2])/2,(before[1]+before[3])/2)
    time.sleep(.3)
    before = rect()
    probe["initial_rect"] = before
    drag((before[0] + 180, before[1] + 22), (35, 25))
    probe["after_drag_rect"] = rect()
    wait_for(lambda: abs(rect()[0] - before[0] - 35) < 8 and abs(rect()[1] - before[1] - 25) < 8, "native title drag")
    normal = rect()
    for expected in [True, False]:
        current = rect()
        click(current[0] + 180, current[1] + 22)
        time.sleep(.065)
        click(current[0] + 180, current[1] + 22)
        # System maximize is verified against the monitor work area.
        wait_for(lambda: fills_work_area() if expected else all(abs(a-b) < 8 for a,b in zip(rect(),normal)), "title double-click " + ("maximizes" if expected else "restores"))
        time.sleep(.2)
    for edge in ["NW", "N", "NE", "W", "E", "SW", "S", "SE"]:
        u.SetWindowPos(hwnd, None, 160, 120, 800, 600, 0x0044)
        time.sleep(.12)
        before = rect()
        x = before[0] + 3 if "W" in edge else before[2] - 3 if "E" in edge else (before[0] + before[2]) / 2
        y = before[1] + 3 if "N" in edge else before[3] - 3 if "S" in edge else (before[1] + before[3]) / 2
        dx = -24 if "W" in edge else 24 if "E" in edge else 0
        dy = -24 if "N" in edge else 24 if "S" in edge else 0
        drag((x, y), (dx, dy))
        after = rect()
        if dx:
            index = 0 if dx < 0 else 2
            assert abs(after[index] - before[index] - dx) < 8, "horizontal edge resize " + edge
        if dy:
            index = 1 if dy < 0 else 3
            assert abs(after[index] - before[index] - dy) < 8, "vertical edge resize " + edge
        checks.append("native resize " + edge)
    current = rect()
    click(*system_button(2))
    wait_for(lambda: u.IsIconic(hwnd), "minimize control")
    u.ShowWindow(hwnd, 9)
    u.SetForegroundWindow(hwnd)
    wait_for(lambda: u.IsWindowVisible(hwnd) and not u.IsIconic(hwnd), "system restore")
    time.sleep(.15)
    current = rect()
    click(*system_button(3))
    normal = current
    wait_for(fills_work_area, "maximize control")
    current = rect()
    click(*system_button(3))
    wait_for(lambda: all(abs(a-b) < 8 for a,b in zip(rect(),normal)), "restore control")
    current = rect()
    click(*system_button(5))
    time.sleep(.15)
    owned()
    u.keybd_event(0x12, 0, 0, 0)
    u.keybd_event(0x73, 0, 0, 0)
    time.sleep(.05)
    u.keybd_event(0x73, 0, 2, 0)
    u.keybd_event(0x12, 0, 2, 0)
    time.sleep(.2)
    report = {"ok": True, "checks": checks}
except Exception as error:
    report = {"ok": False, "checks": checks, "error": str(error), "probe": probe}
finally:
    u.mouse_event(4, 0, 0, 0, 0)
    u.keybd_event(0x73, 0, 2, 0)
    u.keybd_event(0x12, 0, 2, 0)
destination.with_suffix(".tmp").write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
destination.with_suffix(".tmp").replace(destination)
