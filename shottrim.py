#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
shottrim.py - 精准边缘截图工具
使用方式：
  按 Alt+Q -> 全屏蒙层出现 -> 单击图像中心 -> 自动检测边缘 -> 生成选框
  框内单击确认 -> 截图保存到桌面
"""

import argparse
import ctypes
import os
import struct
import subprocess
import sys
import time
import winreg

# 窗口列表缓存，避免每次按 Alt+Q 都重新枚举所有窗口（导致慢）
_win_cache = None
_win_cache_time = 0.0
_win_rects_cache = []

def _refresh_window_list():
    global _win_cache, _win_cache_time, _win_rects_cache
    now = time.time()
    if _win_cache is not None and now - _win_cache_time < 1.0:
        return _win_rects_cache
    rects = []
    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

    def rect_of(hwnd):
        r = wintypes.RECT()
        if dwmapi.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(r), ctypes.sizeof(r)) != 0:
            user32.GetWindowRect(hwnd, ctypes.byref(r))
        return (r.left, r.top, r.right, r.bottom)

    def cb(hwnd, lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        if user32.IsIconic(hwnd):
            return True
        GWL_EXSTYLE = -20
        WS_EX_TOOLWINDOW = 0x00000080
        ex = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        if ex & WS_EX_TOOLWINDOW:
            return True
        cls = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(hwnd, cls, 64)
        if cls.value in ("Progman", "WorkerW", "Shell_TrayWnd",
                         "Windows.UI.Core.CoreWindow", "ForegroundStaging"):
            return True
        r = rect_of(hwnd)
        w, h = r[2] - r[0], r[3] - r[1]
        if w < 60 or h < 60:
            return True
        rects.append(r)
        return True

    user32.EnumWindows(WNDENUMPROC(cb), 0)
    _win_rects_cache = rects
    _win_cache_time = now
    return _win_rects_cache
from ctypes import wintypes

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageGrab, ImageTk

try:
    import mss
except ImportError:
    sys.exit("缺少依赖 mss，请先运行: python -m pip install mss")

# DPI 感知
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
dwmapi = ctypes.windll.dwmapi

# Win32 函数原型
user32.WindowFromPoint.argtypes = [wintypes.POINT]
user32.WindowFromPoint.restype = ctypes.c_void_p
user32.GetAncestor.argtypes = [ctypes.c_void_p, ctypes.c_uint]
user32.GetAncestor.restype = ctypes.c_void_p
user32.GetWindowRect.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.RECT)]
user32.GetWindowRect.restype = ctypes.c_int
user32.GetForegroundWindow.restype = ctypes.c_void_p
user32.GetClientRect.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.RECT)]
user32.GetClientRect.restype = ctypes.c_int
user32.ClientToScreen.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.POINT)]
user32.ClientToScreen.restype = ctypes.c_int
dwmapi.DwmGetWindowAttribute.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_uint]
dwmapi.DwmGetWindowAttribute.restype = ctypes.c_long
user32.RegisterHotKey.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_uint, ctypes.c_uint]
user32.RegisterHotKey.restype = ctypes.c_int
user32.UnregisterHotKey.argtypes = [ctypes.c_void_p, ctypes.c_int]
user32.CreateWindowExW.argtypes = [ctypes.c_uint, ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint,
                                   ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
user32.CreateWindowExW.restype = ctypes.c_void_p
user32.LoadIconW.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
user32.LoadIconW.restype = ctypes.c_void_p
user32.DestroyWindow.argtypes = [ctypes.c_void_p]
user32.DestroyWindow.restype = ctypes.c_int
shell32 = ctypes.windll.shell32
shell32.Shell_NotifyIconW.argtypes = [ctypes.c_uint, ctypes.c_void_p]
shell32.Shell_NotifyIconW.restype = ctypes.c_int
user32.RegisterHotKey.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_uint, ctypes.c_uint]
user32.RegisterHotKey.restype = ctypes.c_int
user32.UnregisterHotKey.argtypes = [ctypes.c_void_p, ctypes.c_int]
user32.UnregisterHotKey.restype = ctypes.c_int
kernel32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
kernel32.GlobalAlloc.restype = ctypes.c_void_p
kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
kernel32.GlobalLock.restype = ctypes.c_void_p
kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
user32.OpenClipboard.argtypes = [ctypes.c_void_p]
user32.OpenClipboard.restype = ctypes.c_int
user32.EmptyClipboard.restype = ctypes.c_int
user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
user32.SetClipboardData.restype = ctypes.c_void_p
user32.CloseClipboard.restype = ctypes.c_int

WM_HOTKEY = 0x0312
HOTKEY_ID = 1

MODS = {"ctrl": 0x0002, "control": 0x0002, "alt": 0x0001, "shift": 0x0004,
        "win": 0x0008, "windows": 0x0008}
MOD_NAMES = [(0x0008, "Win"), (0x0004, "Shift"), (0x0002, "Ctrl"), (0x0001, "Alt")]
VK = {"printscreen": 0x2C, "prtsc": 0x2C, "space": 0x20, "enter": 0x0D,
      "return": 0x0D, "tab": 0x09, "esc": 0x1B, "escape": 0x1B}


def parse_hotkey(s):
    parts = [p.strip().lower() for p in s.replace("++", "+").split("+") if p.strip()]
    if len(parts) < 2:
        raise ValueError("快捷键至少需要修饰键+主键")
    mods = 0
    for p in parts[:-1]:
        if p in MODS:
            mods |= MODS[p]
        else:
            raise ValueError(f"未知修饰键: {p}")
    k = parts[-1]
    if k in MODS:
        raise ValueError("缺少主键")
    if k in VK:
        vk = VK[k]
    elif k.startswith("f") and k[1:].isdigit() and 1 <= int(k[1:]) <= 24:
        vk = 0x70 + int(k[1:]) - 1
    elif len(k) == 1 and k.isalnum():
        vk = ord(k.upper())
    else:
        raise ValueError(f"未知按键: {k}")
    return mods, vk


def format_hotkey(mods, vk):
    parts = [n for bit, n in MOD_NAMES if mods & bit]
    parts.append(vk_name(vk))
    return "+".join(parts)


def vk_name(vk):
    if 0x41 <= vk <= 0x5A:
        return chr(vk)
    if 0x30 <= vk <= 0x39:
        return chr(vk)
    if 0x70 <= vk <= 0x87:
        return f"F{vk - 0x70 + 1}"
    return f"VK_{vk}"


def cursor_pos():
    pt = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


def monitor_containing(x, y):
    for mon in mss.MSS().monitors[1:]:
        l, t = mon["left"], mon["top"]
        if l <= x < l + mon["width"] and t <= y < t + mon["height"]:
            return mon
    return mss.MSS().monitors[1]


def enumerate_window_rects():
    """枚举当前所有可见、非最小化、有面积的顶层窗口矩形。
    必须在创建全屏蒙层之前调用，否则蒙层会盖住一切。
    结果缓存 1 秒，避免重复枚举导致卡顿。
    """
    global _win_cache, _win_cache_time, _win_rects_cache
    now = time.time()
    if _win_cache is not None and now - _win_cache_time < 1.0:
        return _win_rects_cache
    rects = []
    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

    def rect_of(hwnd):
        r = wintypes.RECT()
        if dwmapi.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(r), ctypes.sizeof(r)) != 0:
            user32.GetWindowRect(hwnd, ctypes.byref(r))
        return (r.left, r.top, r.right, r.bottom)

    def cb(hwnd, lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        if user32.IsIconic(hwnd):  # 最小化
            return True
        # 跳过工具窗口（托盘、输入法等）
        GWL_EXSTYLE = -20
        WS_EX_TOOLWINDOW = 0x00000080
        ex = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        if ex & WS_EX_TOOLWINDOW:
            return True
        cls = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(hwnd, cls, 64)
        if cls.value in ("Progman", "WorkerW", "Shell_TrayWnd",
                         "Windows.UI.Core.CoreWindow", "ForegroundStaging"):
            return True
        r = rect_of(hwnd)
        w, h = r[2] - r[0], r[3] - r[1]
        if w < 60 or h < 60:
            return True
        rects.append(r)
        return True

    user32.EnumWindows(WNDENUMPROC(cb), 0)
    _win_rects_cache = rects
    _win_cache_time = now
    return _win_rects_cache



def pick_window_from_list(rects, sx, sy):
    """从预枚举的窗口列表中，找包含鼠标且尺寸合理的窗口。"""
    v = mss.MSS().monitors[0]
    screen_area = v["width"] * v["height"]
    best = None
    best_area = None
    for r in rects:
        w, h = r[2] - r[0], r[3] - r[1]
        if w * h > screen_area * 0.95: continue  # 排除桌面
        if w < 100 or h < 100: continue          # 排除太小控件
        if r[0] <= sx < r[2] and r[1] <= sy < r[3]:
            area = w * h
            if best_area is None or area < best_area:
                best_area = area
                best = r
    return best


def get_window_under_cursor(sx, sy):
    """取鼠标正下方的顶层窗口矩形（微信截图的窗口吸附）。
    
    用 WindowFromPoint 拿到鼠标下的窗口，再用 GetAncestor(GA_ROOT)
    升到顶层窗口。这样鼠标在子控件上时，高亮的是整个父窗口。
    """
    hwnd = user32.WindowFromPoint(wintypes.POINT(sx, sy))
    if not hwnd:
        return None
    # 升到顶层窗口
    hwnd = user32.GetAncestor(hwnd, 2)  # GA_ROOT
    if not hwnd:
        return None
    # 排除桌面窗口（全屏）
    v = mss.MSS().monitors[0]
    screen_area = v["width"] * v["height"]
    rect = wintypes.RECT()
    if dwmapi.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(rect), ctypes.sizeof(rect)) != 0:
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
    w, h = rect.right - rect.left, rect.bottom - rect.top
    # 排除全屏桌面和太小的控件
    if w * h > screen_area * 0.95 or w < 100 or h < 100:
        return None
    return (rect.left, rect.top, rect.right, rect.bottom)


def window_rect_under(x, y):
    """取鼠标下的窗口矩形（微信截图式窗口吸附）。

    关键：不要用 GA_ROOT！它会一路升到最顶层窗口（常常是全屏）。
    直接用 WindowFromPoint 的结果（通常是内容区/图片查看器窗口）。
    若该矩形过小（一个小控件），才上溯到顶层窗口。
    """
    hwnd = user32.WindowFromPoint(wintypes.POINT(x, y))
    if not hwnd:
        return None
    rect = wintypes.RECT()
    res = dwmapi.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(rect), ctypes.sizeof(rect))
    if res != 0:
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
    r0 = (rect.left, rect.top, rect.right, rect.bottom)

    # 屏幕面积，用于判断矩形是否过小
    v = mss.MSS().monitors[0]
    screen_area = v["width"] * v["height"]
    area0 = (r0[2] - r0[0]) * (r0[3] - r0[1])
    if area0 >= screen_area * 0.15:
        return r0

    # 太小则上溯到顶层窗口
    root = user32.GetAncestor(hwnd, 2)
    if root and root != hwnd:
        rr = wintypes.RECT()
        if dwmapi.DwmGetWindowAttribute(root, 9, ctypes.byref(rr), ctypes.sizeof(rr)) != 0:
            user32.GetWindowRect(root, ctypes.byref(rr))
        return (rr.left, rr.top, rr.right, rr.bottom)
    return r0


def foreground_client_rect():
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return None
    r = wintypes.RECT()
    if not user32.GetClientRect(hwnd, ctypes.byref(r)):
        return None
    p1 = wintypes.POINT(r.left, r.top)
    p2 = wintypes.POINT(r.right, r.bottom)
    if not user32.ClientToScreen(hwnd, ctypes.byref(p1)):
        return None
    user32.ClientToScreen(hwnd, ctypes.byref(p2))
    return p1.x, p1.y, p2.x, p2.y


def find_content_bounds(img_np, cx, cy, threshold=30, max_expand=800):
    """边缘检测 + 连通区域分析：找到点击点附近最大的内容区域。
    
    策略：
    1. 先做 Canny 边缘检测，找到图像中的所有边缘
    2. 从点击点做洪水填充（宽松阈值）
    3. 找最大的连通区域作为内容边界
    """
    from collections import deque
    from PIL import ImageFilter
    h, w = img_np.shape[:2]
    cx = max(0, min(w - 1, cx))
    cy = max(0, min(h - 1, cy))
    
    # 采样背景色（从四角）
    pad = min(30, h // 5, w // 5)
    if pad < 1:
        return (0, 0, w, h)
    samples = []
    for y in list(range(0, pad)) + list(range(h - pad, h)):
        for x in list(range(0, pad)) + list(range(w - pad, w)):
            if 0 <= y < h and 0 <= x < w:
                samples.append(img_np[y, x])
    bg = np.median(samples, axis=0).astype(np.float32)
    
    # 用较宽松的阈值判断是否为"背景"
    # 背景 = 接近白色/灰色/统一的低饱和度颜色
    def is_bg(px):
        r, g, b = int(px[0]), int(px[1]), int(px[2])
        brightness = (r + g + b) / 3.0
        saturation = max(r, g, b) - min(r, g, b)
        # 白/灰背景：高亮度 + 低饱和度
        if brightness > 200 and saturation < 30:
            return True
        # 或者颜色与背景色中位数接近
        dr, dg, db = r - bg[0], g - bg[1], b - bg[2]
        return dr*dr + dg*dg + db*db < (threshold * 2) ** 2
    
    # BFS 洪水填充，从点击点向外扩散
    visited = np.zeros((h, w), dtype=np.bool_)
    queue = deque([(cy, cx, 0)])
    visited[cy, cx] = True
    content_pixels = [(cx, cy)]
    
    while queue:
        y, x, dist = queue.popleft()
        if dist > max_expand:
            continue
        
        for dy, dx in ((-1,0),(1,0),(0,-1),(0,1)):
            ny, nx = y + dy, x + dx
            if 0 <= ny < h and 0 <= nx < w and not visited[ny, nx]:
                visited[ny, nx] = True
                if not is_bg(img_np[ny, nx]):
                    content_pixels.append((nx, ny))
                    queue.append((ny, nx, dist + 1))
    
    if not content_pixels:
        return full_scan_bounds(img_np, threshold)
    
    xs = [p[0] for p in content_pixels]
    ys = [p[1] for p in content_pixels]
    return (min(xs), min(ys), max(xs) + 1, max(ys) + 1)


def full_scan_bounds(img_np, threshold=30):
    """兜底：全图扫描找内容边界。"""
    h, w = img_np.shape[:2]
    pad = min(20, h // 5, w // 5)
    samples = []
    for y in list(range(0, pad)) + list(range(h - pad, h)):
        for x in list(range(0, pad)) + list(range(w - pad, w)):
            if 0 <= y < h and 0 <= x < w:
                samples.append(img_np[y, x])
    bg = np.median(samples, axis=0).astype(np.float32)
    bg_sq = float(threshold) * float(threshold)
    
    def is_bg(px):
        r, g, b = int(px[0]), int(px[1]), int(px[2])
        dr, dg, db = r - bg[0], g - bg[1], b - bg[2]
        return dr*dr + dg*dg + db*db < bg_sq
    
    mask = np.array([[not is_bg(img_np[y, x]) for x in range(w)] for y in range(h)])
    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        return (0, 0, w, h)
    return (xs.min(), ys.min(), xs.max() + 1, ys.max() + 1)



def auto_inset_to_content(img_np, win_l, win_t, win_r, win_b):
    """在窗口内找照片矩形边界，返回建议的四边收缩量。

    思路：照片四条边会产生贯穿很长的颜色跳变线。
    统计每行/列发生跳变的像素数，取强度最高的"长边"位置。
    找不到明确边界时返回 0（保持窗口原样，交给 ↑↓ 手动调）。
    """
    h, w = img_np.shape[:2]
    l, t = max(0, win_l), max(0, win_t)
    r, b = min(w, win_r), min(h, win_b)
    if r - l < 40 or b - t < 40:
        return 0
    region = img_np[t:b, l:r].astype(np.int16)
    bh, bw = region.shape[:2]

    drow = np.abs(np.diff(region, axis=0)).sum(axis=2)  # 水平边缘
    dcol = np.abs(np.diff(region, axis=1)).sum(axis=2)  # 垂直边缘
    row_strength = (drow > 12).sum(axis=1)  # 每行跳变列数
    col_strength = (dcol > 12).sum(axis=0)  # 每列跳变行数

    # 只认"长边"：跳变覆盖 >= 40% 宽度/高度
    good_rows = np.where(row_strength >= bw * 0.4)[0]
    good_cols = np.where(col_strength >= bh * 0.4)[0]
    if len(good_rows) < 2 or len(good_cols) < 2:
        return 0

    y0, y1 = int(good_rows.min()), int(good_rows.max()) + 1
    x0, x1 = int(good_cols.min()), int(good_cols.max()) + 1
    # 只有当检测框明显小于窗口、且形状合理时才采用
    if (x1 - x0) < bw * 0.9 and (y1 - y0) < bh * 0.9 and (x1 - x0) > bw * 0.2:
        # 返回四边平均收缩量（对称收缩用）
        return max(0, min(x0, bw - x1, y0, bh - y1))
    return 0


def find_content_by_variance(img_np, threshold=12):
    """用行/列颜色方差找内容边界（比颜色距离法更稳）。

    原理：
    - 纯色背景行/列：颜色变化范围 ≈ 0
    - 内容行/列：颜色变化范围大（有照片、有边框）
    - 找最长连续内容行/列，自动排除工具栏等碎片
    优点：
    - 不依赖背景色具体值（白色/灰色/黑色背景都能用）
    - 照片内有白色衣服也不怕（因为看的是变化幅度，不是绝对值）
    """
    h, w = img_np.shape[:2]
    gray = np.mean(img_np, axis=2).astype(np.float32)

    row_range = np.max(gray, axis=1) - np.min(gray, axis=1)
    col_range = np.max(gray, axis=0) - np.min(gray, axis=0)

    def longest_run(mask):
        best_start, best_len = 0, 0
        cur_start, cur_len = 0, 0
        for i, v in enumerate(mask):
            if v:
                if cur_len == 0:
                    cur_start = i
                cur_len += 1
                if cur_len > best_len:
                    best_len = cur_len
                    best_start = cur_start
            else:
                cur_len = 0
        return best_start, best_start + best_len

    content_rows = row_range > threshold
    content_cols = col_range > threshold

    y0, y1 = longest_run(content_rows)
    x0, x1 = longest_run(content_cols)

    if y1 - y0 < 10 or x1 - x0 < 10:
        # 方差法失效，退回全图
        return (0, 0, w, h)
    return (int(x0), int(y0), int(x1), int(y1))


def background_color(rgb):
    h, w = rgb.shape[:2]
    # 从四角采样背景色（比四边更稳：避免工具栏/状态栏干扰）
    corners = []
    for cy, cx in [(0,0), (0,w-1), (h-1,0), (h-1,w-1)]:
        corners.append(rgb[cy, cx])
    return np.median(corners, axis=0)


def content_mask(rgb, bg, threshold):
    """找与背景色差异大的像素，并用连通组件分析只保留最大块。
    这样能排除工具栏图标、按钮等小碎片，只保留照片主体。
    """
    h, w = rgb.shape[:2]
    dist = np.linalg.norm(rgb.astype(np.float32) - bg.astype(np.float32), axis=2)
    mask = dist > threshold
    # 形态学开运算去小噪点，闭运算填小洞
    m = Image.fromarray((mask * 255).astype(np.uint8))
    for _ in range(2):
        m = m.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.MaxFilter(3))
    for _ in range(2):
        m = m.filter(ImageFilter.MaxFilter(3)).filter(ImageFilter.MinFilter(3))
    mask = np.array(m) > 127

    # 连通组件分析：只保留面积最大的组件（照片主体）
    try:
        from scipy import ndimage
        labeled, num = ndimage.label(mask)
        if num > 1:
            sizes = ndimage.sum(mask, labeled, range(1, num + 1))
            biggest = int(np.argmax(sizes)) + 1
            mask = labeled == biggest
    except Exception:
        pass  # scipy 不可用时退回原 mask
    return mask



def transparent_background(img, bg, threshold):
    h, w = img.size
    rgb = np.asarray(img.convert("RGB"))
    dist = np.linalg.norm(rgb.astype(np.float32) - bg.astype(np.float32), axis=2)
    is_content = (dist > threshold).astype(np.uint8) * 255
    work = np.pad(is_content, 1, mode="constant", constant_values=0)
    work_img = Image.fromarray(work)
    ImageDraw.floodfill(work_img, (0, 0), 1, thresh=0)
    filled = np.asarray(work_img)
    border_bg = (filled == 1)
    alpha = np.where(border_bg, 0, 255).astype(np.uint8)
    rgba = img.convert("RGBA")
    rgba.putalpha(Image.fromarray(alpha[1:-1, 1:-1], mode="L"))
    return rgba


def copy_to_clipboard(img):
    """把图像写入剪贴板（CF_DIB, 32bpp BI_BITFIELDS, 带 alpha 掩码）。
    同时保存一份 PNG 到桌面，返回文件路径。
    """
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    w, h = img.size
    src = np.asarray(img)

    # RGBA -> BGRA
    bgra = np.empty_like(src)
    bgra[:, :, 0] = src[:, :, 2]
    bgra[:, :, 1] = src[:, :, 1]
    bgra[:, :, 2] = src[:, :, 0]
    bgra[:, :, 3] = src[:, :, 3]

    row_stride = ((w * 4 + 3) // 4) * 4
    buf = np.zeros((h, row_stride), dtype=np.uint8)
    buf[:, : w * 4] = bgra.reshape(h, -1)
    buf = np.ascontiguousarray(buf[::-1])   # DIB 自底向上
    data = buf.tobytes()

    # BITMAPV4HEADER (108 bytes)
    hdr = struct.pack("<IiiHHIIiiII", 108, w, h, 1, 32, 3, len(data), 0, 0, 0, 0)
    hdr += struct.pack("<IIII", 0x00FF0000, 0x0000FF00, 0x000000FF, 0xFF000000)
    hdr += struct.pack("<I", 0x57696E20)          # LCS_WINDOWS_COLOR_SPACE
    hdr += struct.pack("<9i", 0, 0, 0, 0, 0, 0, 0, 0, 0)   # CIEXYZTRIPLE
    hdr += struct.pack("<III", 0, 0, 0)            # Gamma
    assert len(hdr) == 108, len(hdr)

    total = len(hdr) + len(data)
    GMEM_MOVEABLE = 0x0002
    CF_DIB = 8
    hmem = kernel32.GlobalAlloc(GMEM_MOVEABLE, total)
    if not hmem:
        raise RuntimeError("GlobalAlloc failed")
    pmem = kernel32.GlobalLock(hmem)
    if not pmem:
        raise RuntimeError("GlobalLock failed")
    ctypes.memmove(pmem, hdr, len(hdr))
    ctypes.memmove(pmem + len(hdr), data, len(data))
    kernel32.GlobalUnlock(hmem)

    if not user32.OpenClipboard(0):
        kernel32.GlobalFree(hmem)
        raise RuntimeError("OpenClipboard failed")
    try:
        user32.EmptyClipboard()
        if not user32.SetClipboardData(CF_DIB, hmem):
            raise RuntimeError("SetClipboardData failed")
    finally:
        user32.CloseClipboard()

    print(f"已复制到剪贴板 ({w} x {h})")


def select_region(mon):
    """微信截图式：蒙层出现前枚举所有窗口，鼠标移动实时高亮最小窗口，单击确认。"""
    import tkinter as tk
    LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "shottrim.log")
    def log2(msg):
        try:
            with open(LOG, "a", encoding="utf-8") as f:
                f.write(time.strftime("[%H:%M:%S] ") + msg + chr(10))
        except Exception:
            pass

    ml, mt = mon["left"], mon["top"]
    mw, mh = mon["width"], mon["height"]
    log2(f"select_region 开始: 显示器 {mw}x{mh}")

    # 关键：必须在创建全屏蒙层之前枚举，否则蒙层会盖住所有窗口
    win_rects = enumerate_window_rects()
    log2(f"枚举到 {len(win_rects)} 个窗口: {win_rects}")

    root = tk.Tk()
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.attributes("-alpha", 0.3)
    root.configure(bg="black")
    root.geometry(f"{mw}x{mh}+{ml}+{mt}")
    root.focus_force()

    canvas = tk.Canvas(root, cursor="cross", highlightthickness=0, bg="black")
    canvas.pack(fill="both", expand=True)

    state = {"box": None, "win": None, "inset": 0, "hover": None}
    result = {"rect": None, "cancelled": False}
    last_cursor = {"x": mw // 2, "y": mh // 2}

    def to_screen(cx, cy):
        return cx + ml, cy + mt

    def screen_rect_to_canvas(r):
        return (max(0, r[0] - ml), max(0, r[1] - mt),
                min(mw, r[2] - ml), min(mh, r[3] - mt))

    def redraw():
        canvas.delete("all")
        mx, my = last_cursor["x"], last_cursor["y"]
        canvas.create_line(mx, 0, mx, mh, fill="#00e0ff", width=1, dash=(4, 4))
        canvas.create_line(0, my, mw, my, fill="#00e0ff", width=1, dash=(4, 4))
        if state["box"]:
            x0, y0, x1, y1 = state["box"]
            canvas.create_rectangle(x0, y0, x1, y1, outline="#00e0ff", width=3)
            canvas.create_text(x0 + 6, max(y0 - 14, 12), anchor="w", fill="#00e0ff",
                             font=("Consolas", 11), text=f"{x1-x0} x {y1-y0}")
            canvas.create_text(mw // 2, mh - 44,
                             text=f"单击确认  |  ↑↓ 向内收缩({state['inset']}px)  |  Esc取消",
                             fill="#aaa", font=("Microsoft YaHei", 10))
        else:
            # 实时高亮鼠标下最小窗口（微信的悬停预览）
            if state["hover"]:
                x0, y0, x1, y1 = state["hover"]
                canvas.create_rectangle(x0, y0, x1, y1, outline="#00e0ff", width=2,
                                       dash=(6, 3))
                canvas.create_text(x0 + 6, max(y0 - 14, 12), anchor="w", fill="#00e0ff",
                                 font=("Consolas", 11), text=f"{x1-x0} x {y1-y0}")
            canvas.create_text(mw // 2, 30,
                             text="移动鼠标自动吸附窗口  |  单击确认  |  Esc取消",
                             fill="white", font=("Microsoft YaHei", 13))

    def on_motion(e):
        last_cursor["x"], last_cursor["y"] = e.x, e.y
        # 实时找包含鼠标的最小窗口
        best = pick_window_from_list(win_rects, e.x + ml, e.y + mt)
        if best:
            log2(f"鼠标({e.x+ml},{e.y+mt}) 命中窗口 {best} = {best[2]-best[0]}x{best[3]-best[1]}")
        if best:
            c = screen_rect_to_canvas(best)
            if c[2] - c[0] > 40 and c[3] - c[1] > 40:
                state["hover"] = c
                if not state["box"]:
                    state["box"] = None
                # 悬停时就把当前候选作为框（未锁定）
                state["win"] = c
                state["inset"] = 0
                state["box"] = c
            else:
                state["hover"] = None
                state["box"] = None
        else:
            state["hover"] = None
            state["box"] = None
        redraw()

    def apply_inset(delta):
        """↑↓ 向内收缩/扩展选框（锁定后微调）。"""
        if not state["win"]:
            return
        state["inset"] = max(0, state["inset"] + delta)
        x0, y0, x1, y1 = state["win"]
        i = state["inset"]
        nx0, ny0, nx1, ny1 = x0 + i, y0 + i, x1 - i, y1 - i
        if nx1 > nx0 + 20 and ny1 > ny0 + 20:
            state["box"] = (nx0, ny0, nx1, ny1)
        else:
            state["inset"] = max(0, state["inset"] - delta)
        redraw()
    def on_click(e):
        cx, cy = e.x, e.y
        last_cursor["x"], last_cursor["y"] = cx, cy
        log2(f"单击 at ({cx+ml},{cy+mt}) 当前box={state['box']}")
        # 单击即确认当前吸附的窗口（悬停时已实时更新）
        if not state["box"]:
            best = pick_window_from_list(win_rects, cx + ml, cy + mt)
            if best:
                state["box"] = screen_rect_to_canvas(best)
        if state["box"]:
            x0, y0, x1, y1 = state["box"]
            sl, st = to_screen(x0, y0)
            er, eb = to_screen(x1, y1)
            result["rect"] = (sl, st, er, eb)
            root.destroy()

    canvas.bind("<ButtonPress-1>", on_click)
    canvas.bind("<Double-Button-1>", lambda e: None)
    canvas.bind("<Motion>", on_motion)
    root.bind("<Escape>", lambda e: (result.update(cancelled=True), root.destroy()))
    root.bind("<Up>", lambda e: apply_inset(4))
    root.bind("<Down>", lambda e: apply_inset(-4))

    redraw()
    root.mainloop()
    if result["cancelled"]:
        return None, 0
    return result["rect"], 0


def do_capture(args):
    if getattr(args, "delay", 0) and args.delay > 0:
        time.sleep(args.delay)

    if getattr(args, "rect", None):
        x, y, w, h = args.rect
        rect = (x, y, x + w, y + h)
        margin = args.margin
    elif getattr(args, "auto", False):
        mon = mss.MSS().monitors[0]
        rect = (mon["left"], mon["top"],
                mon["left"] + mon["width"], mon["top"] + mon["height"])
        margin = args.margin
    elif getattr(args, "interactive", False) or True:
        # 直接在本进程内跑 tkinter 蒙层（pythonw 下可正常工作）
        # 不再启动子进程，避免启动开销导致慢
        mon = monitor_containing(*cursor_pos())
        rect, margin = select_region(mon)
        if not rect:
            print("已取消。")
            return None

    l, t, r, b = rect
    if r - l < 4 or b - t < 4:
        print("选区太小，已取消。")
        return None

    img = mss.MSS().grab({"left": l, "top": t, "width": r - l, "height": b - t})
    img = Image.frombytes("RGB", (r - l, b - t), img.rgb)

    rgb = np.asarray(img)
    # 用方差法找内容边界（比颜色距离法更稳：照片里有白色衣服也不受影响）
    x0, y0, x1, y1 = find_content_by_variance(rgb, threshold=args.threshold)
    # 向外扩大 margin，避免边缘像素被漏掉
    x0 = max(0, x0 - args.margin)
    y0 = max(0, y0 - args.margin)
    x1 = min(img.width, x1 + args.margin)
    y1 = min(img.height, y1 + args.margin)

    rgb_out = img.crop((x0, y0, x1, y1))
    rgba_out = transparent_background(img, background_color(np.asarray(img)), args.threshold).crop((x0, y0, x1, y1))

    out = rgba_out if args.transparent else rgb_out
    copy_to_clipboard(out)
    print(f"已复制到剪贴板 ({out.width} x {out.height})")

    return out, None


def run_daemon(args):
    LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "shottrim.log")

    def log(msg):
        try:
            with open(LOG, "a", encoding="utf-8") as f:
                f.write(time.strftime("[%H:%M:%S] ") + msg + "\n")
        except Exception:
            pass

    try:
        mods, vk = parse_hotkey(args.hotkey)
    except ValueError as e:
        sys.exit(f"快捷键错误: {e}")
    if not user32.RegisterHotKey(None, HOTKEY_ID, mods, vk):
        # 尝试 Ctrl+Alt+Q 作为备选
        mods_ctrl_alt, vk_q = parse_hotkey("ctrl+alt+q")
        if user32.RegisterHotKey(None, HOTKEY_ID, mods_ctrl_alt, vk_q):
            log(f"Alt+Q 被占用，已自动切换到 Ctrl+Alt+Q")
            args.hotkey = "ctrl+alt+q"
        else:
            err = ctypes.get_last_error()
            sys.exit(f"Alt+Q 和 Ctrl+Alt+Q 均已被占用（错误码 {err}）。请手动释放后重试。")
    log(f"驻留启动，快捷键 {format_hotkey(mods, vk)} 注册成功")

    tray = Tray()
    tray.add()
    print(f"Shottrim 已驻留后台。快捷键: {format_hotkey(mods, vk)}")
    print("按下快捷键 -> 弹出选框 -> 确认 -> 保存到桌面")

    msg = wintypes.MSG()
    try:
        while True:
            ret = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if ret <= 0:
                break
            if msg.message == WM_HOTKEY and msg.wParam == HOTKEY_ID:
                log("收到热键，开始截图")
                try:
                    res = do_capture(args)
                    if res:
                        out, path = res
                        log(f"截图完成 {out.width}x{out.height}")
                        tray.balloon("Shottrim", f"已保存到桌面 ({out.width}×{out.height})")
                    else:
                        log("截图取消或未识别到内容")
                except BaseException as e:
                    import traceback
                    tb = traceback.format_exc()
                    log("截图异常: " + tb)
                    try:
                        tray.balloon("Shottrim", f"截图失败：{e}")
                    except Exception:
                        pass
                    try:
                        with open(LOG, "a", encoding="utf-8") as f:
                            f.write(tb)
                    except Exception:
                        pass
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
    finally:
        tray.close()
        user32.UnregisterHotKey(None, HOTKEY_ID)


class Tray:
    NIF_ICON = 0x2
    NIF_TIP = 0x4
    NIF_INFO = 0x10
    NIIF_INFO = 0x1

    def __init__(self):
        self.hwnd = None
        self.nid = None
        self.ok = False

    def add(self):
        try:
            self.hwnd = user32.CreateWindowExW(0, "STATIC", "shottrim", 0, 0, 0, 0, 0,
                                               None, None, None, None)
            nid = self._struct()()
            nid.cbSize = ctypes.sizeof(nid)
            nid.hWnd = self.hwnd
            nid.uID = 1
            nid.uFlags = self.NIF_ICON | self.NIF_TIP
            nid.hIcon = user32.LoadIconW(None, 32512)
            nid.szTip = "Shottrim"
            if not shell32.Shell_NotifyIconW(0, ctypes.byref(nid)):
                return
            self.nid = nid
            self.ok = True
        except Exception:
            pass

    def balloon(self, title, message):
        if not self.ok:
            return
        try:
            self.nid.uFlags = self.NIF_INFO
            self.nid.szInfo = message
            self.nid.szInfoTitle = title
            self.nid.dwInfoFlags = self.NIIF_INFO
            shell32.Shell_NotifyIconW(2, ctypes.byref(self.nid))
        except Exception:
            pass

    def close(self):
        if self.nid is not None:
            try:
                shell32.Shell_NotifyIconW(1, ctypes.byref(self.nid))
            except Exception:
                pass
        if self.hwnd:
            try:
                user32.DestroyWindow(self.hwnd)
            except Exception:
                pass

    @staticmethod
    def _struct():
        class NOTIFYICONDATAW(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.DWORD),
                ("hWnd", wintypes.HWND),
                ("uID", wintypes.UINT),
                ("uFlags", wintypes.UINT),
                ("uCallbackMessage", wintypes.UINT),
                ("hIcon", wintypes.HICON),
                ("szTip", wintypes.WCHAR * 128),
                ("dwState", wintypes.DWORD),
                ("dwStateMask", wintypes.DWORD),
                ("szInfo", wintypes.WCHAR * 256),
                ("uTimeoutOrVersion", wintypes.UINT),
                ("szInfoTitle", wintypes.WCHAR * 64),
                ("dwInfoFlags", wintypes.DWORD),
                ("guidItem", ctypes.c_byte * 16),
                ("hBalloonIcon", wintypes.HICON),
            ]
        return NOTIFYICONDATAW


def install_autostart(args):
    script = os.path.abspath(__file__)
    exe_dir = os.path.dirname(sys.executable)
    pyw = os.path.join(exe_dir, "pythonw.exe")
    if not os.path.exists(pyw):
        pyw = sys.executable

    daemon_args = ["--daemon", "--hotkey", args.hotkey,
                   "--threshold", str(args.threshold), "--margin", str(args.margin)]

    def q(a):
        return '"' + a + '"' if (" " in a or not a) else a

    argline = " ".join(q(a) for a in daemon_args)
    cmd = f'"{pyw}" "{script}" {argline}'
    vbs = f'Set ws = CreateObject("WScript.Shell")\nws.Run "{cmd.replace(chr(34), chr(34) * 2)}", 0, False\n'
    vbs_path = os.path.join(os.path.dirname(script), "shottrim_daemon.vbs")
    with open(vbs_path, "w", encoding="utf-8") as f:
        f.write(vbs)

    key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                         r"Software\Microsoft\Windows\CurrentVersion\Run",
                         0, winreg.KEY_SET_VALUE)
    winreg.SetValueEx(key, "Shottrim", 0, winreg.REG_SZ, f'wscript.exe "{vbs_path}"')
    winreg.CloseKey(key)

    try:
        subprocess.Popen(["wscript.exe", vbs_path])
        started = True
    except Exception:
        started = False

    print("已设置开机自启。")
    print(f"  快捷键: {args.hotkey}")
    print(f"  启动脚本: {vbs_path}")
    print("  已在后台启动。" if started else "  未能立即启动。")


def uninstall_autostart():
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r"Software\Microsoft\Windows\CurrentVersion\Run",
                             0, winreg.KEY_SET_VALUE)
        winreg.DeleteValue(key, "Shottrim")
        winreg.CloseKey(key)
        print("已从开机自启移除。")
    except FileNotFoundError:
        print("未找到自启项。")
    vbs_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "shottrim_daemon.vbs")
    if os.path.exists(vbs_path):
        os.remove(vbs_path)
        print("已删除启动脚本。")


def main():
    ap = argparse.ArgumentParser(description="精准边缘截图工具")
    ap.add_argument("--rect", nargs=4, type=int, metavar=("X", "Y", "W", "H"),
                    help="直接指定区域")
    ap.add_argument("--delay", type=float, default=0, help="弹出前等待秒数")
    ap.add_argument("--threshold", type=float, default=30,
                    help="背景色判定容差（默认 30，越大越激进）")
    ap.add_argument("--margin", type=int, default=0, help="内容四周额外边距")
    ap.add_argument("--transparent", action=argparse.BooleanOptionalAction,
                    default=True, help="背景做成透明 PNG")
    ap.add_argument("--clipboard", action=argparse.BooleanOptionalAction,
                    default=True, help="复制到剪贴板")
    ap.add_argument("--daemon", action="store_true", help="后台驻留")
    ap.add_argument("--hotkey", default="alt+q", help="全局快捷键（默认 alt+q）")
    ap.add_argument("--auto", action="store_true", help="自动截取前台窗口")
    ap.add_argument("--interactive", action="store_true",
                    help="交互模式（子进程专用）")
    ap.add_argument("--tmp", default="", help="临时文件路径")
    ap.add_argument("--install-autostart", action="store_true", help="注册开机自启")
    ap.add_argument("--uninstall-autostart", action="store_true", help="移除开机自启")
    args = ap.parse_args()

    if args.uninstall_autostart:
        uninstall_autostart()
    elif args.install_autostart:
        install_autostart(args)
    elif args.daemon:
        run_daemon(args)
    else:
        do_capture(args)


if __name__ == "__main__":
    main()