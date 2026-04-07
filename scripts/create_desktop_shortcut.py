#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""在桌面创建「QQ农场」快捷方式（草图标、中文名无乱码）。需 pywin32：pip install pywin32"""
from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import sys
from pathlib import Path

# 本文件在 scripts/ 下，项目根为其上一级
_ROOT = Path(__file__).resolve().parent.parent

# 通知资源管理器刷新图标/关联（换图标后同路径常被缓存）
SHCNE_ASSOCCHANGED = 0x08000000
SHCNF_IDLIST = 0x0000


def _win_path(p: Path) -> str:
    return str(p.resolve()).replace("/", "\\")


def _notify_shell_change() -> None:
    try:
        ctypes.windll.shell32.SHChangeNotify(SHCNE_ASSOCCHANGED, SHCNF_IDLIST, None, None)
    except Exception:
        pass
    # Win10+：刷新用户磁贴/图标缓存（存在则调用）
    ie4 = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "ie4uinit.exe"
    if ie4.is_file():
        try:
            subprocess.run(
                [str(ie4), "-show"],
                shell=False,
                capture_output=True,
                timeout=10,
            )
        except Exception:
            pass


def main() -> int:
    try:
        import win32com.client  # type: ignore
    except ImportError:
        print("请先安装: pip install pywin32", file=sys.stderr)
        return 1

    script = (_ROOT / "gui_scripts" / "new_main_pyqt.py").resolve()
    icon = (_ROOT / "assets" / "app_icon.ico").resolve()
    if not script.is_file():
        print("找不到:", script, file=sys.stderr)
        return 1
    if not icon.is_file():
        print("找不到图标:", icon, file=sys.stderr)
        return 1

    pyw_raw = shutil.which("pythonw.exe") or shutil.which("python.exe")
    if not pyw_raw:
        print("PATH 中未找到 pythonw.exe / python.exe", file=sys.stderr)
        return 1
    pyw = _win_path(Path(pyw_raw).resolve())

    desktop = Path(os.path.expanduser("~")) / "Desktop"
    # 源码用转义，避免 Windows 下非 UTF-8 保存导致桌面快捷方式名称乱码
    lnk_path = desktop / "QQ\u519c\u573a.lnk"

    # 删掉旧快捷方式，避免 Shell 沿用缓存的图标
    if lnk_path.is_file():
        try:
            lnk_path.unlink()
        except OSError:
            pass

    shell = win32com.client.Dispatch("WScript.Shell")
    sc = shell.CreateShortcut(_win_path(lnk_path))
    sc.TargetPath = pyw
    sc.Arguments = f'"{_win_path(script)}"'
    sc.WorkingDirectory = _win_path(_ROOT)
    sc.Description = "QQ Farm control center (PyQt6)"
    # 必须用绝对路径 + 反斜杠，否则图标常不更新
    sc.IconLocation = f"{_win_path(icon)},0"
    sc.Save()
    _notify_shell_change()
    print("OK:", lnk_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
