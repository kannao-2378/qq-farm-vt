"""控制台与子进程共用：日志、会话环境、子进程参数（无 GUI 依赖）。"""
from __future__ import annotations

import locale
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Dict, Optional, Tuple

BASE_DIR = Path(__file__).resolve().parent
_CONTROL_CENTER_LOG = (BASE_DIR.parent / "logs" / "control_center.log").resolve()
_LOG_IO_LOCK = threading.Lock()

# 为 False 时暂停「操作会话记录器」：不建会话目录、不注入 QQFARM_ACTION_SESSION_DIR
ACTION_SESSION_RECORDING_ENABLED = False


def _write_control_center_log(line: str) -> None:
    """运行记录转后台：写入项目 logs/control_center.log，并同步 print 到控制台（若有）。"""
    text = line.rstrip("\n") + "\n"
    try:
        _CONTROL_CENTER_LOG.parent.mkdir(parents=True, exist_ok=True)
        with _LOG_IO_LOCK:
            with open(_CONTROL_CENTER_LOG, "a", encoding="utf-8") as fp:
                fp.write(text)
    except Exception:
        pass
    try:
        print(line.rstrip("\n"), flush=True)
    except Exception:
        pass


def _prune_action_session_logs(logs_root: Path) -> None:
    import shutil

    from action_session_recorder import ACTION_SESSION_LOG_KEEP_COUNT

    keep = max(1, int(ACTION_SESSION_LOG_KEEP_COUNT))
    if not logs_root.is_dir():
        return
    subs = sorted((p for p in logs_root.iterdir() if p.is_dir()), key=lambda p: p.name, reverse=True)
    while len(subs) >= keep:
        oldest = subs.pop()
        shutil.rmtree(oldest, ignore_errors=True)


def _action_session_env() -> Tuple[Dict[str, str], Optional[Path]]:
    if not ACTION_SESSION_RECORDING_ENABLED:
        return os.environ.copy(), None
    from datetime import datetime

    logs_root = (BASE_DIR.parent / "action_session_logs").resolve()
    logs_root.mkdir(parents=True, exist_ok=True)
    _prune_action_session_logs(logs_root)
    sid = datetime.now().strftime("%Y%m%d_%H%M%S")
    session_path = (logs_root / sid).resolve()
    session_path.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["QQFARM_ACTION_SESSION_DIR"] = str(session_path)
    return env, session_path


def _subprocess_flags() -> Dict[str, int]:
    if sys.platform == "win32":
        return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
    return {}


def _subprocess_encoding() -> str:
    if sys.platform == "win32":
        return locale.getpreferredencoding(False) or "gbk"
    return "utf-8"
