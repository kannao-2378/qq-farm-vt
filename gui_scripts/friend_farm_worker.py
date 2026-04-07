import argparse
import os
import sys
import time
from datetime import datetime

if "--help" not in sys.argv and "-h" not in sys.argv:
    _sd = os.environ.get("QQFARM_ACTION_SESSION_DIR", "").strip()
    if _sd:
        import action_session_recorder

        action_session_recorder.install(_sd)

from game_region_locator import (
    MAIN_INTERFACE_PATROL_TEMPLATE_THRESHOLD,
    PATROL_MIN_FRIEND_INTERVAL_SEC,
    STEAL_UI_MATCH_THRESHOLD,
    _diag,
    _diag_init,
    load_steal_feature_config,
)
from friend_farm_flow import execute_friend_farm_once


def _now() -> str:
    return datetime.now().strftime("%H:%M:%S")


def main() -> int:
    parser = argparse.ArgumentParser(description="仅执行好友农场动作（摘取/浇水/除虫/除草）。")
    parser.add_argument("--once", action="store_true", help="只执行一次。")
    parser.add_argument("--interval", type=float, default=None, help="循环间隔秒数；不填则读取 config 的 friend_patrol_interval_sec。")
    parser.add_argument("--threshold", type=float, default=None, help="好友农场模板阈值；不填则每轮读取 config 的 friend_patrol_threshold。")
    parser.add_argument("--run-main-first", type=int, default=1, help="1=先执行主界面任务再执行好友农场；0=仅执行好友农场。")
    args = parser.parse_args()

    try:
        return _main_body(args)
    finally:
        try:
            import action_session_recorder

            action_session_recorder.finalize_if_active()
        except Exception:
            pass


def _main_body(args: argparse.Namespace) -> int:
    _diag_init()
    cfg = load_steal_feature_config()
    interval_raw = float(cfg.get("friend_patrol_interval_sec", 0.0)) if args.interval is None else max(0.0, args.interval)
    interval = max(0.0, interval_raw) if args.once else max(PATROL_MIN_FRIEND_INTERVAL_SEC, interval_raw)

    if not bool(cfg.get("master_enabled", False)):
        msg = "偷菜总开关关闭，脚本结束。"
        print(f"[{_now()}] {msg}")
        _diag("friend_worker", "master_disabled", msg, level="warn")
        return 1

    actions = dict(cfg.get("actions", {}))
    if not any(actions.values()):
        msg = "好友农场动作全未勾选，脚本结束。"
        print(f"[{_now()}] {msg}")
        _diag("friend_worker", "no_actions_enabled", msg, level="warn")
        return 1

    _diag("friend_worker", "start", "好友农场脚本启动", interval_sec=interval, actions={k: v for k, v in actions.items() if v})
    print(f"[{_now()}] 好友农场脚本启动，间隔={interval}s，动作={','.join([k for k, v in actions.items() if v])}")

    while True:
        try:
            cfg_now = load_steal_feature_config()
            friend_threshold_now = (
                float(args.threshold)
                if args.threshold is not None
                else float(cfg_now.get("friend_patrol_threshold", STEAL_UI_MATCH_THRESHOLD))
            )
            main_threshold_now = float(cfg_now.get("main_patrol_threshold", MAIN_INTERFACE_PATROL_TEMPLATE_THRESHOLD))
            res = execute_friend_farm_once(
                friend_threshold=friend_threshold_now,
                main_threshold=main_threshold_now,
                run_main_first=bool(int(args.run_main_first)),
            )
            status = str(res.get("status", "unknown"))
            reason = str(res.get("reason", "") or "")
            message = str(res.get("message", ""))
            if reason:
                print(f"[{_now()}] {status}/{reason}: {message}")
            else:
                print(f"[{_now()}] {status}: {message}")
            _diag(
                "friend_worker",
                "run_once",
                message,
                status=status,
                reason=reason or None,
                threshold=friend_threshold_now,
                main_threshold=main_threshold_now,
            )
        except Exception as exc:
            print(f"[{_now()}] error: {type(exc).__name__}: {exc}")
            _diag("friend_worker", "exception", str(exc), level="error", exc_type=type(exc).__name__)
            if args.once:
                return 1

        if args.once:
            break
        time.sleep(interval)

    _diag("friend_worker", "stop", "好友农场脚本结束")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
