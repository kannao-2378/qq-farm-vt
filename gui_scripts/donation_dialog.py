"""
试用与自愿打赏：状态 JSON 与计数逻辑（界面由 donation_dialog_qt 等实现）。
启动次数与累计使用时长分别统计、分别持久化。
状态保存在项目根目录 user_data/donation_state.json。不含敏感信息。
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict

# 首次弹出前：启动次数需「大于」下列值（即第 MIN_LAUNCH_BEFORE_TIP+1 次起才可能弹）
MIN_LAUNCH_BEFORE_TIP = 5
# 首次弹出前：累计使用时长（秒）需「大于」下列值；为 0 表示不要求时长门槛（仍单独累计）
MIN_TOTAL_USAGE_SEC_BEFORE_TIP = 0
# 累计点击「已赏」达到此次数后，不再定时弹出
YI_SHANG_STOP_AT = 3
# 累计「未赏」达到此次数后，点击「未赏」不再退出程序
WEI_SHANG_NO_EXIT_AT = 5
# 自上次点「已赏」记录时间起，间隔多久可再弹（秒）
REMINDER_SEC = 86400
# 「已赏」按钮在弹窗出现后延迟多久才可点（秒）
BUTTON_DELAY_SEC = 120

DONATION_MESSAGE = (
    "代码是作者用ai写的，金额不限，聊表心意，小人在这里跪求了。"
)

# 本会话：上次把时长写入 JSON 的 monotonic 时刻（主窗口就绪后才开始计时）
_SESSION_LAST_MONO: float | None = None


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


_STATE_DIR = _repo_root() / "user_data"
_STATE_FILE = _STATE_DIR / "donation_state.json"


def _migrate_legacy_state_if_needed() -> None:
    """若 user_data 下尚无状态文件，依次尝试从旧路径复制。"""
    if _STATE_FILE.is_file():
        return
    _STATE_DIR.mkdir(parents=True, exist_ok=True)
    root_legacy = _repo_root() / "donation_state.json"
    candidates = []
    if root_legacy.is_file():
        candidates.append(root_legacy)
    legacy_dir = os.environ.get("LOCALAPPDATA", "")
    if legacy_dir:
        candidates.append(Path(legacy_dir) / "qq-farm-vt" / "donation_state.json")
    for src in candidates:
        if not src.is_file():
            continue
        try:
            _STATE_FILE.write_bytes(src.read_bytes())
            return
        except OSError:
            continue


def _qr_image_path() -> Path:
    return _repo_root() / "assets" / "donation_qr.png"


def _normalize_state(data: Dict[str, Any]) -> Dict[str, Any]:
    lc = int(data.get("launch_count", data.get("usage_count", 0)))
    return {
        "launch_count": lc,
        "usage_count": lc,
        "total_usage_seconds": int(float(data.get("total_usage_seconds", 0))),
        "yi_shang_count": int(data.get("yi_shang_count", 0)),
        "wei_shang_count": int(data.get("wei_shang_count", 0)),
        "last_reminder_ts": data.get("last_reminder_ts"),
    }


def load_state() -> Dict[str, Any]:
    _migrate_legacy_state_if_needed()
    _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not _STATE_FILE.is_file():
        return _normalize_state(
            {
                "launch_count": 0,
                "yi_shang_count": 0,
                "wei_shang_count": 0,
                "last_reminder_ts": None,
                "total_usage_seconds": 0,
            }
        )
    try:
        raw = json.loads(_STATE_FILE.read_text(encoding="utf-8"))
        return _normalize_state(raw)
    except Exception:
        return _normalize_state(
            {
                "launch_count": 0,
                "yi_shang_count": 0,
                "wei_shang_count": 0,
                "last_reminder_ts": None,
                "total_usage_seconds": 0,
            }
        )


def save_state(state: Dict[str, Any]) -> None:
    st = dict(state)
    st["launch_count"] = int(st.get("launch_count", st.get("usage_count", 0)))
    st["usage_count"] = st["launch_count"]
    st["total_usage_seconds"] = int(float(st.get("total_usage_seconds", 0)))
    _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _STATE_FILE.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")


def _should_show(state: Dict[str, Any]) -> bool:
    """是否应弹出打赏窗（启动次数未过门槛、已赏满额、未到再提醒间隔等见常量与 README 打赏说明）。"""
    if state["yi_shang_count"] >= YI_SHANG_STOP_AT:
        return False

    launch_count = int(state.get("launch_count", state.get("usage_count", 0)))
    total_sec = int(float(state.get("total_usage_seconds", 0)))

    if launch_count <= MIN_LAUNCH_BEFORE_TIP:
        return False
    if MIN_TOTAL_USAGE_SEC_BEFORE_TIP > 0 and total_sec <= MIN_TOTAL_USAGE_SEC_BEFORE_TIP:
        return False

    ys = state["yi_shang_count"]
    last = state.get("last_reminder_ts")
    if ys == 0:
        return True
    if last is None:
        return True
    try:
        return (time.time() - float(last)) >= REMINDER_SEC
    except (TypeError, ValueError):
        return True


def should_show_reminder() -> bool:
    return _should_show(load_state())


def prepare_session() -> None:
    """进程入口调用：仅增加启动次数（与使用时长分开统计）。"""
    st = load_state()
    st["launch_count"] = int(st.get("launch_count", st.get("usage_count", 0))) + 1
    st["usage_count"] = st["launch_count"]
    save_state(st)


def start_usage_session_clock() -> None:
    """主窗口已创建后调用：从此时起用 accumulate_usage_tick 累计本会话使用时长。"""
    global _SESSION_LAST_MONO
    _SESSION_LAST_MONO = time.monotonic()


def accumulate_usage_tick() -> None:
    """由主界面定时器周期调用（如每 10s），把本会话经过的时间累加到 total_usage_seconds。"""
    global _SESSION_LAST_MONO
    if _SESSION_LAST_MONO is None:
        return
    now = time.monotonic()
    delta = max(0.0, now - _SESSION_LAST_MONO)
    _SESSION_LAST_MONO = now
    if delta < 0.5:
        return
    st = load_state()
    st["total_usage_seconds"] = int(float(st.get("total_usage_seconds", 0))) + int(round(delta))
    save_state(st)


def finalize_session_usage_on_exit() -> None:
    """应用退出前把最后一次计时片写入 JSON。"""
    global _SESSION_LAST_MONO
    if _SESSION_LAST_MONO is None:
        return
    now = time.monotonic()
    delta = max(0.0, now - _SESSION_LAST_MONO)
    _SESSION_LAST_MONO = None
    if delta < 0.5:
        return
    st = load_state()
    st["total_usage_seconds"] = int(float(st.get("total_usage_seconds", 0))) + int(round(delta))
    save_state(st)
