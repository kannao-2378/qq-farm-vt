import threading
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from game_region_locator import (
    PATROL_STEAL_MAX_ACTION_ROUNDS,
    STEAL_UI_TEMPLATE_SCALES_FAST,
    VISIT_JUDGE_ICON_THRESHOLD,
    _diag,
    capture_game_region,
    click_friend_button_with_retry,
    click_template_on_game_frame_retry,
    ensure_visit_check_roi_cached,
    find_asset_png_root,
    find_visit_panel_close_button_png,
    find_visit_panel_judge_icon_png,
    find_visit_panel_visit_button_png,
    is_main_interface_scene,
    classify_scene_three_way,
    load_config_region,
    load_main_interface_actions_enabled,
    load_steal_feature_config,
    list_png_candidates_exact_name,
    load_visit_check_roi_relative,
    main_has_pending_work,
    recover_unknown_scene_with_close,
    run_main_interface_actions_once,
    run_steal_interface_actions_once,
    wait_after_visit_click,
    wait_for_visit_judge_icon,
    visit_judge_icon_present,
    click_visit_at_frame_xy,
    find_all_visit_button_matches,
    detect_red_box_roi_relative,
    read_image_compat,
)


def _flow_log(event: str, message: str, **fields: object) -> None:
    print(f"[friend_flow] {event}: {message}")
    _diag("friend_flow", event, message, **fields)


def _click_template_multi_threshold(
    region: Dict[str, int],
    template_path,
    thresholds: Tuple[float, ...] = (0.60, 0.56, 0.52),
) -> bool:
    for th in thresholds:
        if click_template_on_game_frame_retry(region, template_path, threshold=float(th), attempts=4, gap_sec=0.06):
            return True
    return False


def _try_return_to_main_scene(region: Dict[str, int], home_btn, close_btn) -> Tuple[bool, str]:
    # 优先点“回家”，失败再点“关闭”，避免卡在拜访/好友农场中间态。
    if _click_template_multi_threshold(region, home_btn, thresholds=(0.60, 0.56, 0.52)):
        return True, "home_clicked"
    if _click_template_multi_threshold(region, close_btn, thresholds=(0.60, 0.56, 0.52)):
        return True, "close_clicked"
    return False, "none"


def _visit_point_allowed_in_limit_roi(
    x_rel: float,
    y_rel: float,
    limit_roi: Dict[str, float],
    require_button_column: bool = True,
) -> bool:
    x1 = float(limit_roi["x1"])
    y1 = float(limit_roi["y1"])
    x2 = float(limit_roi["x2"])
    y2 = float(limit_roi["y2"])
    if not (x1 <= x_rel <= x2 and y1 <= y_rel <= y2):
        return False
    if not require_button_column:
        return True
    # 按钮通常位于限制框右半列，避免误点左侧头像/昵称区域。
    col_x = x1 + (x2 - x1) * 0.45
    return x_rel >= col_x


def _click_visit_button_by_matches(region: Dict[str, int], visit_btn_path) -> Optional[Tuple[int, int]]:
    frame = capture_game_region()
    limit_roi = _load_visit_button_limit_roi()
    for th in (0.56, 0.52, 0.48):
        matches = find_all_visit_button_matches(frame, visit_btn_path, threshold=th)
        if not matches:
            continue
        if limit_roi:
            fh, fw = frame.shape[:2]
            filtered = []
            for fx0, fy0, sc in matches:
                x_rel = float(fx0) / float(max(1, fw))
                y_rel = float(fy0) / float(max(1, fh))
                if float(sc) < 0.60:
                    continue
                if _visit_point_allowed_in_limit_roi(x_rel, y_rel, limit_roi, require_button_column=True):
                    filtered.append((fx0, fy0, sc))
            matches = filtered
            if not matches:
                _flow_log("visit_button_roi_filtered_empty", "拜访按钮命中均在限制区域外，已丢弃", threshold=th)
                continue
        # 同一行优先右侧按钮（x 更大），避免误点个人信息区域。
        matches.sort(key=lambda m: (m[1], -m[0], -m[2]))
        fx, fy, score = matches[0]
        _flow_log("visit_button_fallback_match", "使用拜访按钮列表兜底点击", threshold=th, score=round(float(score), 4), frame_xy=(fx, fy))
        if click_visit_at_frame_xy(region, fx, fy, stop_event=None):
            return (int(fx), int(fy))
        return None
    return None


def _load_visit_button_limit_roi() -> Dict[str, float]:
    name = "拜访界面-限制拜访按钮区域.png"
    candidates = list_png_candidates_exact_name(name)
    for p in candidates:
        img = read_image_compat(str(p))
        if img is None or img.size == 0:
            continue
        roi = detect_red_box_roi_relative(img)
        if roi:
            return roi
    # 未配置限制图时，回退全屏（不限制）
    return {"x1": 0.0, "y1": 0.0, "x2": 1.0, "y2": 1.0}


def execute_friend_farm_once(
    friend_threshold: float = 0.62,
    main_threshold: float = 0.65,
    run_main_first: bool = True,
) -> Dict[str, str]:
    region = load_config_region()
    if not region:
        return {"status": "error", "reason": "region_missing", "message": "未设置游戏窗口。"}

    cfg = load_steal_feature_config()
    if not bool(cfg.get("master_enabled", False)):
        return {"status": "skipped", "reason": "steal_disabled", "message": "未启用偷菜功能。"}
    steal_actions = dict(cfg.get("actions", {}))
    if not any(steal_actions.values()):
        return {"status": "skipped", "reason": "no_steal_actions", "message": "偷菜动作未勾选。"}

    friend_btn = find_asset_png_root("主界面", "好友")
    judge_icon = find_visit_panel_judge_icon_png() or find_asset_png_root("拜访界面", "判断", "图标")
    visit_btn = find_visit_panel_visit_button_png()
    close_btn = find_visit_panel_close_button_png() or find_asset_png_root("拜访界面", "×")
    home_btn = find_asset_png_root("偷菜界面", "回家")
    if not friend_btn:
        return {"status": "error", "reason": "template_missing", "message": "缺少模板：主界面-好友按钮.png"}
    if not judge_icon:
        return {"status": "error", "reason": "template_missing", "message": "缺少模板：拜访界面-判断图标.png"}
    if not visit_btn:
        return {"status": "error", "reason": "template_missing", "message": "缺少模板：拜访界面-拜访按钮.png"}
    if not close_btn:
        return {"status": "error", "reason": "template_missing", "message": "缺少模板：拜访界面-×按钮.png"}
    if not home_btn:
        return {"status": "error", "reason": "template_missing", "message": "缺少模板：偷菜界面-回家按钮.png"}

    stop_event = threading.Event()
    frame = capture_game_region()
    scene = classify_scene_three_way(frame, visit_btn_path=visit_btn, home_btn_path=home_btn)
    if scene == "unknown":
        _flow_log("scene_unknown", "当前界面不属于主/拜访/好友农场，进入恢复流程")
        scene = recover_unknown_scene_with_close(
            region,
            close_btn_path=close_btn,
            visit_btn_path=visit_btn,
            home_btn_path=home_btn,
            stop_event=stop_event,
            settle_sec=1.0,
            after_close_sec=0.2,
            max_rounds=20,
        )
    recover_round = 0
    while scene != "main" and recover_round < 4:
        if scene == "visit":
            _flow_log("scene_visit_recover", "当前处于拜访界面，先点击关闭按钮")
            _click_template_multi_threshold(region, close_btn, thresholds=(0.60, 0.56, 0.52))
            time.sleep(0.2)
        elif scene == "steal":
            _flow_log("scene_steal_recover", "当前处于好友农场，先执行偷菜动作再回家")
            run_steal_interface_actions_once(
                actions_enabled=steal_actions,
                threshold=float(friend_threshold),
                max_action_rounds=PATROL_STEAL_MAX_ACTION_ROUNDS,
                steal_scales=STEAL_UI_TEMPLATE_SCALES_FAST,
                stop_event=stop_event,
            )
            _click_template_multi_threshold(region, home_btn, thresholds=(0.60, 0.56, 0.52))
            time.sleep(0.2)
        else:
            scene = recover_unknown_scene_with_close(
                region,
                close_btn_path=close_btn,
                visit_btn_path=visit_btn,
                home_btn_path=home_btn,
                stop_event=stop_event,
                settle_sec=1.0,
                after_close_sec=0.2,
                max_rounds=20,
            )
            recover_round += 1
            continue
        frame = capture_game_region()
        scene = classify_scene_three_way(frame, visit_btn_path=visit_btn, home_btn_path=home_btn)
        recover_round += 1
    if scene != "main":
        return {"status": "skipped", "reason": "not_main_interface", "message": "当前非主界面，跳过好友农场流程。"}

    if run_main_first:
        main_actions = load_main_interface_actions_enabled()
        main_res = run_main_interface_actions_once(
            actions_enabled=main_actions,
            threshold=float(main_threshold),
        )
        _flow_log("main_once", str(main_res.get("message", "")), status=main_res.get("status"))

        frame_after_main = capture_game_region()
        if not is_main_interface_scene(frame_after_main):
            return {"status": "skipped", "reason": "left_main_after_main_tasks", "message": "主界面任务后已不在主界面，跳过拜访流程。"}

        main_msg = str(main_res.get("message", "") or "")
        main_clicked = "已执行点击" in main_msg
        has_main_pending = main_has_pending_work(main_actions, threshold=float(main_threshold), require_ocr=False)
        if has_main_pending:
            # 无论本轮是否有点击，都做严格复核；仅当严格复核通过才拦截好友流程。
            strict_threshold = min(0.70, max(float(main_threshold) + 0.12, 0.56))
            strict_pending = main_has_pending_work(
                main_actions,
                threshold=float(strict_threshold),
                require_ocr=False,
            )
            if not strict_pending:
                _flow_log(
                    "main_pending_false_positive",
                    "主界面待办复核未通过，放行好友流程",
                    loose_threshold=round(float(main_threshold), 3),
                    strict_threshold=round(float(strict_threshold), 3),
                    main_clicked=main_clicked,
                )
                has_main_pending = False
            else:
                _flow_log(
                    "main_pending_confirmed",
                    "主界面待办复核通过，继续拦截好友流程",
                    loose_threshold=round(float(main_threshold), 3),
                    strict_threshold=round(float(strict_threshold), 3),
                    main_clicked=main_clicked,
                )
        if has_main_pending:
            return {"status": "skipped", "reason": "main_pending", "message": "仍有主界面任务，跳过拜访流程。"}

    if not click_friend_button_with_retry(region, friend_btn, stop_event=stop_event):
        return {"status": "skipped", "reason": "friend_button_miss", "message": "未命中主界面好友按钮。"}
    _flow_log("friend_clicked", "已点击主界面好友按钮，开始判定拜访界面判断图标")

    ensure_visit_check_roi_cached()
    roi_rel = load_visit_check_roi_relative()
    if not roi_rel:
        _flow_log("visit_roi_fallback", "拜访检查 ROI 缺失，改用整幅游戏区判定")

    # 显式轮询判定：先 ROI，再整幅补判，确保“有判断就点拜访、无判断就点关闭”。
    wait_for_visit_judge_icon(
        roi_rel,
        judge_icon,
        stop_event,
        max_wait_sec=0.0,
        poll_sec=0.12,
        threshold=VISIT_JUDGE_ICON_THRESHOLD,
    )
    has_judge = False
    last_roi_hit = False
    last_full_hit = False
    deadline = time.time() + 3.2
    while time.time() < deadline and not stop_event.is_set():
        frame_check = capture_game_region()
        roi_hit = visit_judge_icon_present(
            frame_check,
            roi_rel,
            judge_icon,
            threshold=VISIT_JUDGE_ICON_THRESHOLD,
        )
        full_hit = visit_judge_icon_present(frame_check, None, judge_icon, threshold=0.48)
        last_roi_hit = bool(roi_hit)
        last_full_hit = bool(full_hit)
        if roi_hit or full_hit:
            has_judge = True
            break
        time.sleep(0.12)
    if not has_judge:
        close_ok = _click_template_multi_threshold(region, close_btn)
        _flow_log(
            "visit_judge_absent",
            "未命中判断图标，执行关闭按钮",
            roi_hit=last_roi_hit,
            full_hit=last_full_hit,
            close_clicked=close_ok,
        )
        if close_ok:
            return {"status": "skipped", "reason": "visit_judge_not_found", "message": "未命中判断图标，已点击关闭按钮返回主界面。"}
        return {"status": "skipped", "reason": "visit_judge_not_found_close_miss", "message": "未命中判断图标，且未命中关闭按钮。"}

    # 拜访面板刚出现时按钮位置会有轻微抖动，短暂停留后再做一次分支判定更稳。
    time.sleep(0.3)
    frame_recheck = capture_game_region()
    recheck_has_judge = visit_judge_icon_present(
        frame_recheck,
        roi_rel,
        judge_icon,
        threshold=VISIT_JUDGE_ICON_THRESHOLD,
    ) or visit_judge_icon_present(frame_recheck, None, judge_icon, threshold=0.48)
    if not recheck_has_judge:
        close_ok = _click_template_multi_threshold(region, close_btn)
        _flow_log("visit_judge_lost_after_delay", "延迟复检未命中判断图标，执行关闭按钮", close_clicked=close_ok)
        if close_ok:
            return {"status": "skipped", "reason": "visit_judge_lost_after_delay", "message": "延迟复检未命中判断图标，已点击关闭按钮。"}
        return {"status": "skipped", "reason": "visit_judge_lost_after_delay_close_miss", "message": "延迟复检未命中判断图标，且未命中关闭按钮。"}

    _flow_log("visit_judge_present", "已命中判断图标，准备点击拜访按钮")
    clicked_visit_xy: Optional[Tuple[int, int]] = None
    # 统一策略：只在“限制区域”内选最上方可点拜访按钮，避免行配对抖动导致一会儿点第一行、一会儿点第二行。
    clicked_visit_xy = _click_visit_button_by_matches(region, visit_btn)
    if not clicked_visit_xy:
        _flow_log("visit_button_miss", "判断图标已命中，但限制区域内未命中拜访按钮")
        return {"status": "skipped", "reason": "visit_button_miss_in_limit_roi", "message": "判断图标已命中，但限制区域内未命中拜访按钮。"}
    _flow_log("visit_button_clicked", "已点击拜访按钮（固定最上方策略）", frame_xy=clicked_visit_xy)

    outcome = wait_after_visit_click(
        roi_rel=roi_rel,
        judge_path=judge_icon,
        home_btn=home_btn,
        close_btn=close_btn,
        stop_event=stop_event,
        max_wait_sec=7.0,
        poll_sec=0.12,
    )
    if outcome in ("still_panel", "unknown"):
        _flow_log("visit_retry", f"首次拜访后状态={outcome}，尝试二次点击拜访按钮")
        retry_clicked = False
        if clicked_visit_xy is not None:
            retry_clicked = click_visit_at_frame_xy(region, clicked_visit_xy[0], clicked_visit_xy[1], stop_event)
            _flow_log("visit_retry_click_same_target", "二次点击锁定同一拜访位置", frame_xy=clicked_visit_xy, clicked=retry_clicked)
        if retry_clicked:
            outcome_retry = wait_after_visit_click(
                roi_rel=roi_rel,
                judge_path=judge_icon,
                home_btn=home_btn,
                close_btn=close_btn,
                stop_event=stop_event,
                max_wait_sec=6.0,
                poll_sec=0.12,
            )
            _flow_log("visit_retry_outcome", "二次点击拜访后的状态", outcome=outcome_retry)
            outcome = outcome_retry
    if outcome != "farm":
        back_ok, back_way = _try_return_to_main_scene(region, home_btn, close_btn)
        scene_main = is_main_interface_scene(capture_game_region())
        if scene_main:
            return {
                "status": "skipped",
                "reason": f"visit_outcome_{outcome}",
                "message": f"点击拜访后回到主界面或未生效（outcome={outcome}, return={back_way if back_ok else 'none'}）。",
            }
        return {
            "status": "skipped",
            "reason": f"visit_outcome_{outcome}",
            "message": f"点击拜访后未进入好友农场（outcome={outcome}, return={back_way if back_ok else 'none'}）。",
        }

    # 进入好友农场后按钮条会有短暂动画/稳定期，直接首帧点击容易出现“第一下无效”。
    time.sleep(0.22)
    steal_res = run_steal_interface_actions_once(
        actions_enabled=steal_actions,
        threshold=float(friend_threshold),
        max_action_rounds=PATROL_STEAL_MAX_ACTION_ROUNDS,
        steal_scales=STEAL_UI_TEMPLATE_SCALES_FAST,
    )
    steal_status = str(steal_res.get("status", ""))
    steal_reason = str(steal_res.get("reason", "") or "")
    if steal_status == "skipped" and steal_reason == "not_friend_farm":
        # 拜访后出现灰区状态：优先回家，失败再关闭，避免后续循环一直不在主界面。
        back_ok, back_way = _try_return_to_main_scene(region, home_btn, close_btn)
        scene_main = is_main_interface_scene(capture_game_region())
        _flow_log(
            "visit_false_farm_detected",
            "拜访后未进入好友农场（run_steal 再判为非好友农场）",
            steal_message=str(steal_res.get("message", "")),
            recover_clicked=back_ok,
            recover_way=back_way,
            scene_main=scene_main,
        )
        if back_ok and scene_main:
            return {
                "status": "done",
                "reason": "no_task_returned_main",
                "message": "好友农场无可执行任务，已返回主界面。",
            }
        return {
            "status": "skipped",
            "reason": "visit_false_farm_detected",
            "message": f"拜访后未进入好友农场：{steal_res.get('message', '')}（recover={back_way if back_ok else 'none'}）",
        }
    home_ok = click_template_on_game_frame_retry(region, home_btn, threshold=0.52, attempts=5, gap_sec=0.06)
    if not home_ok:
        return {
            "status": "done",
            "reason": "home_button_miss",
            "message": f"{steal_res.get('message', '')}；好友农场任务后未命中回家按钮。",
        }
    return {
        "status": "done",
        "reason": str(steal_res.get("reason", "") or "ok"),
        "message": f"{steal_res.get('message', '')}；已点击回家按钮。",
    }
