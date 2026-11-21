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
user32.GetShellWindow.restype = ctypes.c_void_p
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
user32.RegisterClipboardFormatW.argtypes = [ctypes.c_wchar_p]
user32.RegisterClipboardFormatW.restype = ctypes.c_uint
user32.GetClipboardData.restype = ctypes.c_void_p
user32.GetClipboardData.argtypes = [ctypes.c_uint]
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


def get_foreground_window_rect():
    """取当前最前（前台）窗口的矩形（虚拟屏幕坐标）。

    优先用 DWM 的扩展边界（不含系统阴影），失败则退回 GetWindowRect。
    如果取到的是桌面/全屏窗口，返回 None。
    """
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return None
    rect = wintypes.RECT()
    if dwmapi.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(rect),
                                  ctypes.sizeof(rect)) != 0:
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
    w, h = rect.right - rect.left, rect.bottom - rect.top
    if w < 60 or h < 60:
        return None
    # 排除桌面窗口本身（GetShellWindow 返回的就是桌面）
    shell = user32.GetShellWindow()
    if shell and hwnd == shell:
        return None
    return (rect.left, rect.top, rect.right, rect.bottom)


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


def trim_window_frame(arr, max_trim=12, col_thresh=25, row_thresh=12):
    """去掉窗口截图四边的边框/阴影，返回 (x0, y0, x1, y1)。

    逐边扫描：比较相邻行/列的平均色，找到内容真正开始的位置。
    边框通常只有几像素，且颜色与内容差异明显。
    """
    h, w = arr.shape[:2]
    if h < 20 or w < 20:
        return (0, 0, w, h)
    a = arr.astype(np.float64)

    # ---- 左边界 ----
    x0 = 0
    col0 = a[:, 0].mean(axis=0)
    for x in range(1, min(max_trim, w - 1)):
        col = a[:, x].mean(axis=0)
        if np.abs(col - col0).sum() > col_thresh:
            # 再确认后续列保持稳定（避免停在渐变中）
            if x + 1 < w - 1:
                col_next = a[:, x + 1].mean(axis=0)
                if np.abs(col_next - col).sum() < col_thresh * 2:
                    x0 = x
                    break
            else:
                x0 = x
                break

    # ---- 右边界 ----
    x1 = w
    col_last = a[:, w - 1].mean(axis=0)
    for d in range(1, min(max_trim, w - 1)):
        x = w - 1 - d
        col = a[:, x].mean(axis=0)
        if np.abs(col - col_last).sum() > col_thresh:
            if x - 1 >= 0:
                col_prev = a[:, x - 1].mean(axis=0)
                if np.abs(col_prev - col).sum() < col_thresh * 2:
                    x1 = x + 1
                    break
            else:
                x1 = x + 1
                break

    # ---- 上边界 ----
    y0 = 0
    row0 = a[0].mean(axis=0)
    for y in range(1, min(max_trim, h - 1)):
        row = a[y].mean(axis=0)
        if np.abs(row - row0).sum() > row_thresh:
            y0 = y
            break

    # ---- 下边界 ----
    y1 = h
    row_last = a[h - 1].mean(axis=0)
    for d in range(1, min(max_trim, h - 1)):
        y = h - 1 - d
        row = a[y].mean(axis=0)
        if np.abs(row - row_last).sum() > row_thresh:
            y1 = y + 1
            break

    if x1 - x0 < 20 or y1 - y0 < 20:
        return (0, 0, w, h)
    return (int(x0), int(y0), int(x1), int(y1))


def find_toolbar_bottom(img_np, max_scan=150, mode_thresh=12,
                        content_ratio=0.35, stable_rows=8):
    """用颜色识别窗口顶部栏的下边界（不用固定高度）。

    原理：
    1. 逐行求众数色，找"众数色发生变化"的行 → 这些是候选边界
       （顶部栏是均匀色带，内容区众数色不同）
    2. 对每个候选，检查下方内容区：
       - 内容占比：与背景色明显不同的像素比例
       - 稳定性：连续 stable_rows 行的占比都够高
    3. 选第一个满足条件的候选

    返回内容区起始的 y 坐标，识别失败返回 0。
    """
    h, w = img_np.shape[:2]
    if h < stable_rows + 20:
        return 0
    arr = img_np.astype(np.int32)
    limit = min(max_scan, h)

    # 逐行众数色
    modes = np.zeros((limit, 3), dtype=np.float32)
    for y in range(limit):
        row = arr[y]
        q = row // 8
        keys = (q[:, 0].astype(np.int64) * 4096
                + q[:, 1].astype(np.int64) * 64
                + q[:, 2].astype(np.int64))
        vals, counts = np.unique(keys, return_counts=True)
        modes[y] = np.median(row[keys == vals[np.argmax(counts)]], axis=0)

    # 候选：众数色相对基准发生变化的行
    base = modes[0]
    candidates = []
    for y in range(1, limit):
        if np.abs(modes[y] - base).sum() > mode_thresh:
            candidates.append(y)

    if not candidates:
        return 0

    # 背景色（用于算内容占比）：取基准行的众数色
    bg = base.astype(np.float32)

    # 每行与背景色不同的像素占比
    ratios = np.zeros(limit, dtype=np.float64)
    for y in range(limit):
        d = np.abs(arr[y].astype(np.float32) - bg).sum(axis=1)
        ratios[y] = np.count_nonzero(d > 25) / w

    # 选第一个"下方内容占比高且稳定"的候选
    for y in candidates:
        if y + stable_rows >= limit:
            continue
        window = ratios[y:y + stable_rows]
        if np.count_nonzero(window > content_ratio) >= stable_rows - 1:
            return int(y)

    # 都没满足，返回第一个候选（宁可多切也不要留工具栏）
    return int(candidates[0])



def find_content_by_variance(img_np, threshold=12):
    """用自适应阈值的逐列/逐行标准差找内容边界。

    原理：
    - 纯色留白行/列：标准差很小（几乎没有颜色变化）
    - 内容行/列：标准差明显大（有照片、边框、文字）
    - 阈值取"全部列/行标准差中位数"的一定比例，自适应不同内容
    - 从左右两侧向内扫描，跳过连续的低标准差区域

    优点：
    - 不依赖背景色具体值
    - 浅色深色背景都适用
    - 照片内有白色衣服也不怕（看的是变化幅度）
    """
    h, w = img_np.shape[:2]
    if h < 20 or w < 20:
        return (0, 0, w, h)

    gray = np.mean(img_np.astype(np.float32), axis=2)
    col_std = gray.std(axis=0)
    row_std = gray.std(axis=1)

    # 自适应阈值：取中位数的一定比例（至少 threshold）
    col_thr = max(threshold, float(np.median(col_std)) * 0.35)
    row_thr = max(threshold, float(np.median(row_std)) * 0.35)

    def scan(arr, thr, limit=None):
        """从两端向内扫描，返回内容段的起止。"""
        n = len(arr)
        if limit is None:
            limit = n
        # 左边：跳过连续的低值区
        lo = 0
        while lo < limit and arr[lo] <= thr:
            lo += 1
        # 右边
        hi = n - 1
        while hi >= 0 and arr[hi] <= thr:
            hi -= 1
        return lo, hi + 1

    x0, x1 = scan(col_std, col_thr)
    y0, y1 = scan(row_std, row_thr)

    if x1 - x0 < 10 or y1 - y0 < 10:
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
    """把图像写入剪贴板。

    同时写入两种格式，保证到处都能粘贴：
    - PNG 注册格式：浏览器（Chrome/Edge/OpenWebUI/微信）粘贴图片用这个
    - CF_DIB：原生 Windows 应用（Office/画图/资源管理器）用这个
    - CF_BITMAP：部分老程序用这个

    PNG 格式保留 alpha 透明通道，浏览器粘贴时背景透明效果正确。
    """
    import io as _io
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    w, h = img.size

    # ---------- 1. PNG 字节（浏览器用） ----------
    png_buf = _io.BytesIO()
    img.save(png_buf, format="PNG")
    png_data = png_buf.getvalue()

    # ---------- 2. CF_DIB 字节（原生应用用） ----------
    src = np.asarray(img)
    bgra = np.empty_like(src)
    bgra[:, :, 0] = src[:, :, 2]   # B
    bgra[:, :, 1] = src[:, :, 1]   # G
    bgra[:, :, 2] = src[:, :, 0]   # R
    bgra[:, :, 3] = src[:, :, 3]   # A
    row_stride = ((w * 4 + 3) // 4) * 4
    buf = np.zeros((h, row_stride), dtype=np.uint8)
    buf[:, : w * 4] = bgra.reshape(h, -1)
    buf = np.ascontiguousarray(buf[::-1])   # DIB 自底向上
    dib_data = buf.tobytes()

    # BITMAPV4HEADER (108 bytes) + BI_BITFIELDS 四掩码
    hdr = struct.pack("<IiiHHIIiiII", 108, w, h, 1, 32, 3, len(dib_data), 0, 0, 0, 0)
    hdr += struct.pack("<IIII", 0x00FF0000, 0x0000FF00, 0x000000FF, 0xFF000000)
    hdr += struct.pack("<I", 0x57696E20)                      # LCS_WINDOWS_COLOR_SPACE
    hdr += struct.pack("<9i", 0, 0, 0, 0, 0, 0, 0, 0, 0)     # CIEXYZTRIPLE
    hdr += struct.pack("<III", 0, 0, 0)                        # Gamma
    assert len(hdr) == 108, len(hdr)

    GMEM_MOVEABLE = 0x0002
    CF_DIB = 8
    CF_BITMAP = 2

    # 注册 PNG / HTML 剪贴板格式
    fmt_png = user32.RegisterClipboardFormatW("PNG")
    fmt_html = user32.RegisterClipboardFormatW("HTML Format")

    # ---------- 分配内存并写入 ----------
    def alloc_copy(data):
        hmem = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
        if not hmem:
            raise RuntimeError("GlobalAlloc failed")
        pmem = kernel32.GlobalLock(hmem)
        if not pmem:
            raise RuntimeError("GlobalLock failed")
        ctypes.memmove(pmem, data, len(data))
        kernel32.GlobalUnlock(hmem)
        return hmem

    hmem_dib = alloc_copy(hdr + dib_data)
    hmem_png = alloc_copy(png_data) if fmt_png else None

    if not user32.OpenClipboard(0):
        raise RuntimeError("OpenClipboard failed")
    try:
        user32.EmptyClipboard()
        # PNG（浏览器粘贴图片）
        if hmem_png and fmt_png:
            if not user32.SetClipboardData(fmt_png, hmem_png):
                raise RuntimeError("SetClipboardData(PNG) failed")
        # CF_DIB（原生应用）
        if not user32.SetClipboardData(CF_DIB, hmem_dib):
            raise RuntimeError("SetClipboardData(CF_DIB) failed")
    finally:
        user32.CloseClipboard()

    print(f"已复制到剪贴板 ({w} x {h})  [PNG + DIB]")



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

    # 关键：必须在创建全屏蒙层之前取前台窗口
    # （创建后前台窗口会变成蒙层自己）
    fg = get_foreground_window_rect()
    log2(f"前台窗口矩形: {fg}")

    root = tk.Tk()
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.attributes("-alpha", 0.3)
    root.configure(bg="black")
    root.geometry(f"{mw}x{mh}+{ml}+{mt}")
    root.focus_force()

    canvas = tk.Canvas(root, cursor="cross", highlightthickness=0, bg="black")
    canvas.pack(fill="both", expand=True)

    state = {"box": None, "win": None, "inset": 0, "hover": None,
             "dragging": False, "drag_start": None, "drag_cur": None}
    result = {"rect": None, "cancelled": False}
    last_cursor = {"x": mw // 2, "y": mh // 2}
    DRAG_THRESHOLD = 5   # 位移小于此值视为单击

    # 初始选框 = 前台窗口
    if fg:
        _c = (max(0, fg[0] - ml), max(0, fg[1] - mt),
              min(mw, fg[2] - ml), min(mh, fg[3] - mt))
        if _c[2] - _c[0] > 40 and _c[3] - _c[1] > 40:
            state["win"] = _c
            state["hover"] = _c
            state["box"] = _c

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
        if state["dragging"] and state["drag_start"] and state["drag_cur"]:
            # 拖拽中：绘制实时矩形
            sx, sy = state["drag_start"]
            cx, cy = state["drag_cur"]
            dx0, dy0 = min(sx, cx), min(sy, cy)
            dx1, dy1 = max(sx, cx), max(sy, cy)
            canvas.create_rectangle(dx0, dy0, dx1, dy1, outline="#00e0ff", width=2)
            canvas.create_rectangle(dx0, dy0, dx1, dy1, outline="#ffffff", width=1)
            canvas.create_text(dx0 + 6, max(dy0 - 14, 12), anchor="w", fill="#00e0ff",
                             font=("Consolas", 11), text=f"{dx1-dx0} x {dy1-dy0}")
            canvas.create_text(mw // 2, mh - 44,
                             text="松开鼠标以截取此区域  |  Esc取消",
                             fill="#aaa", font=("Microsoft YaHei", 10))
        elif state["box"]:
            x0, y0, x1, y1 = state["box"]
            canvas.create_rectangle(x0, y0, x1, y1, outline="#00e0ff", width=3)
            canvas.create_text(x0 + 6, max(y0 - 14, 12), anchor="w", fill="#00e0ff",
                             font=("Consolas", 11), text=f"{x1-x0} x {y1-y0}")
            canvas.create_text(mw // 2, mh - 44,
                             text=f"单击确认  |  按住拖拽可自选区域  |  ↑↓ 向内收缩({state['inset']}px)  |  Esc取消",
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
                             text="已识别当前最前窗口  |  单击确认  |  ↑↓ 收缩  |  Esc取消",
                             fill="white", font=("Microsoft YaHei", 13))

    def on_motion(e):
        # 只跟踪鼠标位置用于十字准星，选框固定为前台窗口
        last_cursor["x"], last_cursor["y"] = e.x, e.y
        if state["dragging"]:
            state["drag_cur"] = (e.x, e.y)
        redraw()

    def on_press(e):
        """按下鼠标：开始拖拽，记录起点。"""
        last_cursor["x"], last_cursor["y"] = e.x, e.y
        state["dragging"] = True
        state["drag_start"] = (e.x, e.y)
        state["drag_cur"] = (e.x, e.y)
        redraw()

    def on_drag(e):
        """拖动中：实时更新矩形。"""
        last_cursor["x"], last_cursor["y"] = e.x, e.y
        if state["dragging"]:
            state["drag_cur"] = (e.x, e.y)
            redraw()

    def on_release(e):
        """松开鼠标：
        - 位移很小 → 视为单击，走原有窗口吸附逻辑
        - 位移较大 → 使用拖拽的矩形
        """
        cx, cy = e.x, e.y
        last_cursor["x"], last_cursor["y"] = cx, cy
        was_dragging = state["dragging"]
        start = state["drag_start"]
        state["dragging"] = False
        state["drag_start"] = None
        state["drag_cur"] = None

        if was_dragging and start:
            sx, sy = start
            moved = max(abs(cx - sx), abs(cy - sy))
            if moved >= DRAG_THRESHOLD:
                # 拖拽模式：用拖拽矩形
                dx0, dy0 = min(sx, cx), min(sy, cy)
                dx1, dy1 = max(sx, cx), max(sy, cy)
                if dx1 - dx0 >= 4 and dy1 - dy0 >= 4:
                    sl, st = to_screen(dx0, dy0)
                    er, eb = to_screen(dx1, dy1)
                    result["rect"] = (sl, st, er, eb)
                    result["mode"] = "drag"
                    log2(f"拖拽选区: ({dx0},{dy0})-({dx1},{dy1})")
                    root.destroy()
                else:
                    redraw()
                return

        # 单击模式：沿用原有逻辑（确认当前窗口框）
        log2(f"单击 at ({cx+ml},{cy+mt}) 当前box={state['box']}")
        if state["box"]:
            x0, y0, x1, y1 = state["box"]
            sl, st = to_screen(x0, y0)
            er, eb = to_screen(x1, y1)
            result["rect"] = (sl, st, er, eb)
            result["mode"] = "window"
            root.destroy()

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
    canvas.bind("<ButtonPress-1>", on_press)
    canvas.bind("<B1-Motion>", on_drag)
    canvas.bind("<ButtonRelease-1>", on_release)
    canvas.bind("<Double-Button-1>", lambda e: None)
    canvas.bind("<Motion>", on_motion)
    root.bind("<Escape>", lambda e: (result.update(cancelled=True), root.destroy()))
    root.bind("<Up>", lambda e: apply_inset(4))
    root.bind("<Down>", lambda e: apply_inset(-4))

    redraw()
    root.mainloop()
    if result["cancelled"]:
        return None, 0, "none"
    return result["rect"], 0, result.get("mode", "window")


def do_capture(args):
    _LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "shottrim.log")
    def _log(msg):
        try:
            with open(_LOG_PATH, "a", encoding="utf-8") as f:
                f.write(time.strftime("[%H:%M:%S] ") + str(msg) + chr(10))
        except Exception:
            pass

    if getattr(args, "delay", 0) and args.delay > 0:
        time.sleep(args.delay)

    if getattr(args, "rect", None):
        x, y, w, h = args.rect
        rect = (x, y, x + w, y + h)
        margin = args.margin
        sel_mode = "window"
    elif getattr(args, "auto", False):
        mon = mss.MSS().monitors[0]
        rect = (mon["left"], mon["top"],
                mon["left"] + mon["width"], mon["top"] + mon["height"])
        margin = args.margin
        sel_mode = "window"
    elif getattr(args, "interactive", False) or True:
        # 直接在本进程内跑 tkinter 蒙层（pythonw 下可正常工作）
        # 不再启动子进程，避免启动开销导致慢
        mon = monitor_containing(*cursor_pos())
        rect, margin, sel_mode = select_region(mon)
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

    if sel_mode == "drag":
        # 拖拽模式：用户已精确指定区域，直接用原图，不再做边缘识别
        x0, y0, x1, y1 = 0, 0, img.width, img.height
        _log("拖拽模式: 使用原始矩形 %sx%s" % (img.width, img.height))
    else:
        # 窗口模式：先去边框，再识别顶部栏 + 内容边缘
        fx0, fy0, fx1, fy1 = trim_window_frame(rgb)
        _log("去边框: (%s,%s)-(%s,%s) (原 %sx%s)" % (
            fx0, fy0, fx1, fy1, img.width, img.height))
        img = img.crop((fx0, fy0, fx1, fy1))
        rgb = np.asarray(img)

        # 用颜色识别窗口顶部栏的下边界（去掉标题栏/工具栏）
        top_cut = find_toolbar_bottom(rgb.astype(np.float32))
        _log("顶部栏下边界: y=%s (窗口高 %s)" % (top_cut, img.height))

        # 用方差法找内容边界（比颜色距离法更稳：照片里有白色衣服也不受影响）
        x0, y0, x1, y1 = find_content_by_variance(rgb, threshold=args.threshold)
        # 顶部栏下边界优先（top_cut 识别成功时强制用它）
        if top_cut > 0:
            y0 = top_cut
        _log("裁剪区域: (%s,%s)-(%s,%s)" % (x0, y0, x1, y1))
        # 向外扩大 margin，避免边缘像素被漏掉
        x0 = max(0, x0 - args.margin)
        y0 = max(0, y0 - args.margin)
        x1 = min(img.width, x1 + args.margin)
        y1 = min(img.height, y1 + args.margin)

    rgb_out = img.crop((x0, y0, x1, y1))
    if sel_mode == "drag":
        # 拖拽模式：保留原始像素（不做透明化），用户已明确指定范围
        rgba_out = rgb_out.convert("RGBA")
    else:
        rgba_out = transparent_background(
            img, background_color(np.asarray(img)), args.threshold).crop((x0, y0, x1, y1))

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