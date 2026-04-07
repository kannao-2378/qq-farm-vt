"""
游戏窗口区域：自动拾取（按标题「QQ经典农场」）或窗口拾取（列表选窗）。
仅 Windows；结果写入 config 中的 game_region（与 game_region_locator 一致）。
"""
from __future__ import annotations

import argparse
import ctypes
import sys
from ctypes import wintypes
from typing import Dict, List, Optional, Tuple

from game_region_locator import _diag, _diag_init, save_config_region, validate_region

# ---------------------------------------------------------------------------
# Win32
# ---------------------------------------------------------------------------

GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080

user32 = ctypes.windll.user32


class RECT(ctypes.Structure):
    _fields_ = (
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    )


def _enum_top_level_windows() -> List[Tuple[int, str]]:
    """可见、非最小化、有标题、非工具窗口的顶层窗口 (hwnd, title)。"""
    out: List[Tuple[int, str]] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _cb(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        if user32.IsIconic(hwnd):
            return True
        ex = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        if ex & WS_EX_TOOLWINDOW:
            return True
        n = user32.GetWindowTextLengthW(hwnd)
        if n <= 0:
            return True
        buf = ctypes.create_unicode_buffer(n + 2)
        user32.GetWindowTextW(hwnd, buf, n + 2)
        title = (buf.value or "").strip()
        if not title:
            return True
        out.append((int(hwnd), title))
        return True

    user32.EnumWindows(_cb, 0)
    return out


def hwnd_to_region(hwnd: int) -> Dict[str, int]:
    rect = RECT()
    if not user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(rect)):
        raise RuntimeError("GetWindowRect 失败")
    w = int(rect.right - rect.left)
    h = int(rect.bottom - rect.top)
    return {"x": int(rect.left), "y": int(rect.top), "w": w, "h": h}


def find_hwnd_qq_classic_farm() -> Optional[int]:
    """标题完全为「QQ经典农场」优先，否则标题包含该字符串的第一个窗口。"""
    target = "QQ经典农场"
    wins = _enum_top_level_windows()
    for hwnd, title in wins:
        if title == target:
            return hwnd
    for hwnd, title in wins:
        if target in title:
            return hwnd
    return None


def run_pick_gui() -> Optional[int]:
    """弹出列表，返回所选 hwnd；取消返回 None。"""
    import tkinter as tk
    from tkinter import messagebox

    wins = _enum_top_level_windows()
    wins.sort(key=lambda t: t[1].lower())

    result: List[Optional[int]] = [None]
    root = tk.Tk()
    root.title("窗口拾取 — 选择游戏窗口")
    root.geometry("720x480")
    try:
        root.attributes("-topmost", True)
    except Exception:
        pass

    tk.Label(
        root,
        text="请在下表中选中游戏窗口，然后点「确定」。取消则关闭不保存。",
        anchor="w",
    ).pack(fill="x", padx=8, pady=(8, 4))

    frame = tk.Frame(root)
    frame.pack(fill="both", expand=True, padx=8, pady=4)

    sb = tk.Scrollbar(frame)
    sb.pack(side="right", fill="y")
    lb = tk.Listbox(frame, yscrollcommand=sb.set, font=("Microsoft YaHei UI", 10), selectmode=tk.SINGLE)
    lb.pack(side="left", fill="both", expand=True)
    sb.config(command=lb.yview)

    for _hwnd, title in wins:
        display = title if len(title) <= 120 else title[:117] + "..."
        lb.insert(tk.END, display)

    def do_ok() -> None:
        sel = lb.curselection()
        if not sel:
            messagebox.showwarning("提示", "请先选中一个窗口。", parent=root)
            return
        idx = int(sel[0])
        result[0] = wins[idx][0]
        root.destroy()

    def do_cancel() -> None:
        result[0] = None
        root.destroy()

    bf = tk.Frame(root)
    bf.pack(fill="x", padx=8, pady=8)
    tk.Button(bf, text="确定", width=12, command=do_ok).pack(side="right", padx=4)
    tk.Button(bf, text="取消", width=12, command=do_cancel).pack(side="right", padx=4)

    root.bind("<Return>", lambda e: do_ok())
    root.bind("<Escape>", lambda e: do_cancel())
    lb.focus_set()
    root.mainloop()
    return result[0]


def main() -> int:
    if sys.platform != "win32":
        print("[REGION] 仅支持 Windows。")
        return 1

    parser = argparse.ArgumentParser(description="游戏窗口：自动拾取 / 窗口拾取（Win32）。")
    parser.add_argument(
        "--mode",
        choices=("auto", "pick"),
        default="auto",
        help="auto=按标题「QQ经典农场」自动拾取；pick=弹出窗口列表手动选择。",
    )
    args = parser.parse_args()

    _diag_init()
    try:
        if args.mode == "pick":
            _diag("region_pick", "pick_start", "窗口拾取：打开列表")
            hwnd = run_pick_gui()
            if hwnd is None:
                _diag("region_pick", "pick_cancel", "窗口拾取：已取消")
                print("[REGION] pick cancelled")
                return 1
            _diag("region_pick", "pick_hwnd", f"窗口拾取：hwnd={hwnd}")
        else:
            _diag("region_auto", "auto_start", "自动拾取：查找 QQ经典农场")
            hwnd = find_hwnd_qq_classic_farm()
            if hwnd is None:
                msg = '未找到标题为「QQ经典农场」或包含该文字的可见窗口。'
                _diag("region_auto", "auto_fail", msg, level="error")
                print(f"[REGION] {msg}")
                return 1
            _diag("region_auto", "auto_hwnd", f"自动拾取：hwnd={hwnd}")

        region = hwnd_to_region(hwnd)
        if not validate_region(region):
            raise ValueError(
                f"窗口区域过小或无效（需宽≥320、高≥200）：{region}。"
                "请换更大的游戏窗口或调整窗口大小后再试。"
            )
        save_config_region(region)
        _diag("region", "save_ok", "区域已保存", region=region)
        print(f"[REGION] ok: {region}")
        return 0
    except Exception as exc:
        _diag("region", "fail", str(exc), level="error", exc_type=type(exc).__name__)
        print(f"[REGION] fail: {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
