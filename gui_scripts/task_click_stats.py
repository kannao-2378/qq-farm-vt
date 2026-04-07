"""
主界面 / 好友农场「一键」点击次数统计（每次 pyautogui 成功点到对应模板算一次）。
供 game_region_locator 写入、控制中心读取；使用 SQLite 便于多进程并发累加。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Dict, Tuple

_DB_PATH = Path(__file__).resolve().parent / "task_click_stats.sqlite3"

MAIN_ACTIONS: Tuple[str, ...] = ("收获", "浇水", "除虫", "除草")
FRIEND_ACTIONS: Tuple[str, ...] = ("摘取", "浇水", "除虫", "除草")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_DB_PATH), timeout=15.0)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS task_clicks (
            scope TEXT NOT NULL,
            action TEXT NOT NULL,
            n INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (scope, action)
        )
        """
    )
    conn.commit()
    return conn


def record_main_action(action_name: str) -> None:
    if action_name not in MAIN_ACTIONS:
        return
    try:
        conn = _connect()
        try:
            conn.execute(
                "INSERT INTO task_clicks(scope, action, n) VALUES ('main', ?, 1) "
                "ON CONFLICT(scope, action) DO UPDATE SET n = n + 1",
                (action_name,),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception:
        pass


def record_friend_action(action_name: str) -> None:
    if action_name not in FRIEND_ACTIONS:
        return
    try:
        conn = _connect()
        try:
            conn.execute(
                "INSERT INTO task_clicks(scope, action, n) VALUES ('friend', ?, 1) "
                "ON CONFLICT(scope, action) DO UPDATE SET n = n + 1",
                (action_name,),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception:
        pass


def read_stats() -> Dict[str, Dict[str, int]]:
    main = {k: 0 for k in MAIN_ACTIONS}
    friend = {k: 0 for k in FRIEND_ACTIONS}
    try:
        conn = _connect()
        try:
            rows = conn.execute("SELECT scope, action, n FROM task_clicks").fetchall()
        finally:
            conn.close()
        for scope, action, n in rows:
            if scope == "main" and action in main:
                main[action] = int(n)
            elif scope == "friend" and action in friend:
                friend[action] = int(n)
    except Exception:
        pass
    return {"main": main, "friend": friend}


def reset_all_stats() -> None:
    """清空主界面与好友农场全部点击计数（SQLite 表）。"""
    try:
        conn = _connect()
        try:
            conn.execute("DELETE FROM task_clicks")
            conn.commit()
        finally:
            conn.close()
    except Exception:
        pass
