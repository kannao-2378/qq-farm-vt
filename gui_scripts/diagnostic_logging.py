"""
主程序（game_region_locator.py）通过 import 本模块完成「写日志」：追加 JSON Lines 到文件。
不负责弹窗；日志文件写入项目根 logs/，由主程序内本模块完成。

默认文件：<项目根>/logs/diagnostic_YYYYMMDD.jsonl（相对本文件解析，不依赖当前工作目录）
"""

from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

_lock = threading.Lock()
_log_path: Optional[Path] = None
_enabled = True


def set_diagnostic_enabled(on: bool) -> None:
    global _enabled
    _enabled = bool(on)


def _default_logs_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "logs"


def init_diagnostic_logging(log_dir: str | Path | None = None) -> Path:
    """初始化当日日志文件路径（可多次调用，仍指向同一天文件）。"""
    global _log_path
    d = Path(log_dir) if log_dir is not None else _default_logs_dir()
    d.mkdir(parents=True, exist_ok=True)
    day = datetime.now().strftime("%Y%m%d")
    _log_path = d / f"diagnostic_{day}.jsonl"
    return _log_path


def current_log_path() -> Optional[Path]:
    return _log_path


def _json_safe(obj: Any) -> Any:
    try:
        json.dumps(obj)
        return obj
    except (TypeError, ValueError):
        return str(obj)


def log_diagnostic(
    category: str,
    event: str,
    message: str = "",
    level: str = "info",
    **fields: Any,
) -> None:
    """
    写入一行 JSON。category：大模块，如 gui / patrol / steal / region。
    event：具体步骤，如 start_patrol / friend_click / visit_outcome。
    level：info | warn | error
    """
    if not _enabled:
        return
    path = _log_path
    if path is None:
        path = init_diagnostic_logging()

    record: Dict[str, Any] = {
        "ts": datetime.now().isoformat(timespec="milliseconds"),
        "level": level,
        "category": category,
        "event": event,
        "message": message or "",
    }
    for k, v in fields.items():
        record[k] = _json_safe(v)

    line = json.dumps(record, ensure_ascii=False) + "\n"
    with _lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(line)
