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
    PATROL_MIN_MAIN_INTERVAL_SEC,
    PATROL_MAIN_MAX_ACTION_ROUNDS,
    PATROL_TEMPLATE_SCALES,
    _diag,
    _diag_init,
    load_main_interface_actions_enabled,
    load_steal_feature_config,
    run_main_interface_actions_once,
)


def _now() -> str:
    return datetime.now().strftime("%H:%M:%S")


def main() -> int:
    parser = argparse.ArgumentParser(description="仅执行主界面动作（收获/浇水/除虫/除草）。")
    parser.add_argument("--once", action="store_true", help="只执行一次。")
    parser.add_argument("--interval", type=float, default=None, help="循环间隔秒数；不填则读取 config 的 main_patrol_interval_sec。")
    parser.add_argument(
        "--threshold",
        type=float,
        default=None,
        help="主界面模板阈值；不填则每轮读取 config 的 main_patrol_threshold。",
    )
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
    interval_raw = float(cfg.get("main_patrol_interval_sec", 0.0)) if args.interval is None else max(0.0, args.interval)
    interval = max(0.0, interval_raw) if args.once else max(PATROL_MIN_MAIN_INTERVAL_SEC, interval_raw)
    actions = load_main_interface_actions_enabled()

    if not any(actions.values()):
        msg = "主界面动作全未勾选，脚本结束。"
        print(f"[{_now()}] {msg}")
        _diag("main_worker", "no_actions_enabled", msg, level="warn")
        return 1

    _diag("main_worker", "start", "主界面脚本启动", interval_sec=interval, actions={k: v for k, v in actions.items() if v})
    print(f"[{_now()}] 主界面脚本启动，间隔={interval}s，动作={','.join([k for k, v in actions.items() if v])}")

    while True:
        try:
            cfg_now = load_steal_feature_config()
            threshold_now = (
                float(args.threshold)
                if args.threshold is not None
                else float(cfg_now.get("main_patrol_threshold", MAIN_INTERFACE_PATROL_TEMPLATE_THRESHOLD))
            )
            res = run_main_interface_actions_once(
                actions_enabled=actions,
                threshold=threshold_now,
                ocr_enabled=False,
                max_action_rounds=PATROL_MAIN_MAX_ACTION_ROUNDS,
                template_scales=PATROL_TEMPLATE_SCALES,
            )
            print(f"[{_now()}] {res.get('status', 'unknown')}: {res.get('message', '')}")
            _diag(
                "main_worker",
                "run_once",
                str(res.get("message", "")),
                status=res.get("status"),
                threshold=threshold_now,
            )
        except Exception as exc:
            print(f"[{_now()}] error: {type(exc).__name__}: {exc}")
            _diag("main_worker", "exception", str(exc), level="error", exc_type=type(exc).__name__)
            if args.once:
                return 1

        if args.once:
            break
        time.sleep(interval)

    _diag("main_worker", "stop", "主界面脚本结束")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
