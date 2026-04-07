#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""删除运行产生的日志、调试图、统计库、操作会话目录等。

不删除：user_data/、gui_scripts/config.json、gui_scripts/planting_strategy_config.json、
assets 内模板图（仅删 game_preview.png 等运行截图）。
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _rm(path: Path) -> None:
    if path.is_file():
        path.unlink(missing_ok=True)
    elif path.is_dir():
        shutil.rmtree(path, ignore_errors=True)


def main() -> int:
    removed: list[str] = []

    # 项目根 logs/
    log_root = ROOT / "logs"
    if log_root.is_dir():
        for c in list(log_root.iterdir()):
            _rm(c)
            removed.append(str(c.relative_to(ROOT)))

    # 历史：诊断写在 gui_scripts/logs/
    gsl = ROOT / "gui_scripts" / "logs"
    if gsl.is_dir():
        for c in list(gsl.iterdir()):
            _rm(c)
            removed.append(str(c.relative_to(ROOT)))

    _rm(ROOT / "action_session_logs")

    _rm(ROOT / "gui_scripts" / "task_click_stats.sqlite3")

    for name in ("game_preview.png",):
        p = ROOT / "assets" / name
        if p.is_file():
            p.unlink(missing_ok=True)
            removed.append(str(p.relative_to(ROOT)))

    for pat in ("debug_visit_check_roi.png", "debug_visit_game_full.png", "level_roi_last.png"):
        p = ROOT / "logs" / pat
        if p.is_file():
            p.unlink(missing_ok=True)
            removed.append(str(p.relative_to(ROOT)))

    for p in ROOT.glob("debug_*.png"):
        if p.is_file():
            p.unlink(missing_ok=True)
            removed.append(str(p.relative_to(ROOT)))

    dc = ROOT / "logs" / "debug_clicks"
    if dc.is_dir():
        _rm(dc)
        removed.append(str(dc.relative_to(ROOT)))

    if removed:
        print("已删除:")
        for r in sorted(set(removed)):
            print(" ", r)
    else:
        print("没有需要清理的运行产物（或目录本为空）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
