import json
import subprocess
import sys
from datetime import datetime
import threading
import time
import tkinter as tk
import ctypes
import random
from tkinter import messagebox
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import cv2
import mss
import numpy as np
import pyautogui
from PIL import Image, ImageDraw, ImageFont

try:
    from task_click_stats import record_friend_action, record_main_action
except ImportError:

    def record_main_action(_action_name: str) -> None:
        return None

    def record_friend_action(_action_name: str) -> None:
        return None


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
# 窗口定位参考、主界面/偷菜/拜访等模板统一放在 assets/yinyong/；图标与收款码等仍在 assets/ 根目录
ASSETS_ROOT = PROJECT_DIR / "assets"
ASSETS_DIR = ASSETS_ROOT / "yinyong"
CONFIG_PATH = SCRIPT_DIR / "config.json"


def search_roots() -> List[Path]:
    return [ASSETS_DIR] if ASSETS_DIR.is_dir() else []


def any_assets_root_exists() -> bool:
    return ASSETS_DIR.is_dir()


def assets_glob_flat_png() -> List[Path]:
    if not ASSETS_DIR.is_dir():
        return []
    return sorted(ASSETS_DIR.glob("*.png"))


def assets_rglob_png() -> List[Path]:
    if not ASSETS_DIR.is_dir():
        return []
    return sorted(ASSETS_DIR.rglob("*.png"))


def assets_iter_subdirs() -> List[Path]:
    if not ASSETS_DIR.is_dir():
        return []
    return sorted((d for d in ASSETS_DIR.iterdir() if d.is_dir()), key=lambda d: d.name)


def resolve_asset_png_path(name: str) -> Optional[Path]:
    p = ASSETS_DIR / name
    if p.is_file():
        return p
    base = Path(name).name
    for q in ASSETS_DIR.rglob("*.png"):
        if q.name == base:
            return q
    return None


def list_png_candidates_exact_name(filename: str) -> List[Path]:
    """root/filename 与递归同名 png（与旧 assets 根目录行为一致，仅根改为 yinyong）。"""
    out: List[Path] = []
    if not ASSETS_DIR.is_dir():
        return out
    p = ASSETS_DIR / filename
    if p.is_file():
        out.append(p)
    out.extend(sorted(q for q in ASSETS_DIR.rglob("*.png") if q.name == filename))
    seen: set[str] = set()
    uniq: List[Path] = []
    for q in out:
        k = str(q.resolve())
        if k not in seen:
            seen.add(k)
            uniq.append(q)
    return uniq


DEFAULT_REGION_KEY = "game_region"

# 为 False 时暂停写入 logs/debug_clicks（好友按钮匹配 hit/miss 调试图）
FRIEND_CLICK_DEBUG_IMAGES_ENABLED = False

# 主界面 / 好友农场 按钮条缓存：避免每轮对「按钮区域确认样图」重复多尺度匹配导致 CPU 常驻偏高
_main_button_band_cache: Optional[Dict[str, float]] = None
_main_button_band_cache_wh: Optional[Tuple[int, int]] = None
_steal_button_band_cache: Optional[Dict[str, float]] = None
_steal_button_band_cache_wh: Optional[Tuple[int, int]] = None
_image_cache: Dict[str, Tuple[float, int, np.ndarray]] = {}
_template_gray_cache: Dict[Tuple[str, float], Tuple[float, int, np.ndarray]] = {}


def invalidate_button_band_caches() -> None:
    global _main_button_band_cache, _main_button_band_cache_wh
    global _steal_button_band_cache, _steal_button_band_cache_wh
    _main_button_band_cache = None
    _main_button_band_cache_wh = None
    _steal_button_band_cache = None
    _steal_button_band_cache_wh = None


VISIT_LIST_ZONE_COUNT = 4
VISIT_ROW_Y_TOLERANCE_PX = 30
VISIT_NAME_ROW_HALF_HEIGHT = 40
# 样图里「一区检查」红框常略低，首行判断图标落在二区才被扫到：仅对一区检查区向上扩（相对弹窗高度）
VISIT_ZONE0_INSPECT_EXPAND_TOP_REL = 0.05
# 「一区有判断图标、二区无则关拜访窗」易在分区/首行偏移时误判，默认关闭；需原逻辑可改 True
VISIT_ZONE12_AUTO_CLOSE_ENABLED = False
# 主界面：历史兼容保留（当前主界面/好友农场流程默认不再依赖 OCR 校验）。
MAIN_TEMPLATE_OCR_BYPASS_SCORE = 0.68
# 主界面判定：当画面能匹配此模板（阈值 0.7）才认为当前是主界面
MAIN_INTERFACE_SCENE_TEMPLATE_NAME = "主界面-判定是否为主界面.png"
MAIN_INTERFACE_SCENE_THRESHOLD = 0.7
# 当「按钮检测区域」样图红框识别失败时，使用该相对区域作为稳态回退（对应样图底部一键条）
DEFAULT_MAIN_ACTION_BAR_ROI_REL = {"x1": 0.10, "y1": 0.62, "x2": 0.82, "y2": 0.80}
# 好友农场一键按钮：底部条带/异色易导致整图匹配差，用更宽尺度 + 上半部模板回退
STEAL_UI_TEMPLATE_SCALES = [0.66, 0.74, 0.82, 0.9, 1.0, 1.1, 1.22]
# 巡查内好友农场：少尺度以压耗时（目标单段尽量 ~0.5s 量级，仍受截图与 CPU 限制）
STEAL_UI_TEMPLATE_SCALES_FAST = [0.78, 0.92, 1.0, 1.1]
STEAL_UI_MATCH_THRESHOLD = 0.35
STEAL_SCENE_TEMPLATE_CANDIDATES = [
    "偷菜界面-判定是否为好友农场界面.png",
    "偷菜界面-判定是否为偷菜界面.png",
]
STEAL_ACTION_TEMPLATE_FIXED_MAPPING: List[Tuple[str, str]] = [
    ("摘取", "偷菜界面-一键摘取.png"),
    ("浇水", "偷菜界面-一键浇水.png"),
    ("除虫", "偷菜界面-一键除虫.png"),
    ("除草", "偷菜界面-一键除草.png"),
]
# 主界面巡查模板匹配少尺度（默认 5 档 → 3 档）
PATROL_TEMPLATE_SCALES = [0.88, 1.0, 1.12]
PATROL_MAIN_MAX_ACTION_ROUNDS = 2
PATROL_STEAL_MAX_ACTION_ROUNDS = 2
# 「还有待办」跟跑主界面最多额外几轮（每轮仍要截图+匹配）
PATROL_MAIN_PENDING_MAX_EXTRA_PASSES = 1
VISIT_JUDGE_ICON_THRESHOLD = 0.55
VISIT_CHECK_ROI_EXPAND = 0.12
# 巡查「间隔」默认可为 0；但拜访弹窗/转场必须有时间出现，否则首帧就判「无判断图标」并关窗（表现为点好友后不动）
#
# 耗时（约，与机器/UI 有关）——
# 1) 点「好友」→ 点「拜访」：
#    - 先固定等待 max(AFTER_FRIEND_CLICK_MIN_SETTLE_SEC, AFTER_FRIEND_CLICK_SETTLE_SEC)，默认至少 0.22s；
#    - 再轮询「判断图标」直至出现或超时 max(VISIT_PANEL_JUDGE_MIN_WAIT_SEC, friend_iv×3)，默认至少等满 3s 才放弃；
#      轮询步长 max(VISIT_POLL_MIN_SEC, VISIT_PANEL_JUDGE_POLL_SEC)，默认 0.08s；
#    - 认出列表后选行并点拜访几乎无额外 sleep。
#    → 顺利时：约 0.22s + 若干次 0.08s（图标一出现就往下走）；最慢约 0.22 + 3s 仍未认出则关窗。
# 2) 好友农场内（已进农场）→ 点「回家」：
#    - 点「拜访」后 wait_after_visit_click：直到认出农场/封号或超时 max(VISIT_OUTCOME_MIN_WAIT_SEC, friend_iv×2)，默认至少 5s；
#    - 再 FRIEND_FARM_AFTER_VISIT_SETTLE_SEC（默认 0）；
#    - 偷菜循环每成功一轮后 interruptible_sleep(friend_iv)，config 为 0 则无；
#    - 最后 click 回家重试间隔 0。
#    → 进农场后若无可偷任务，通常很快点回家；有多轮偷菜则叠加每轮操作 + friend_iv。
VISIT_PANEL_JUDGE_MIN_WAIT_SEC = 3.0
VISIT_OUTCOME_MIN_WAIT_SEC = 5.0
AFTER_FRIEND_CLICK_MIN_SETTLE_SEC = 0.22
VISIT_POLL_MIN_SEC = 0.12
FRIEND_FARM_AFTER_VISIT_SETTLE_SEC = 0.0
VISIT_TO_FARM_POLL_SEC = 0.0
VISIT_PANEL_JUDGE_POLL_SEC = 0.0
# 低功耗保护：巡查循环最小间隔（秒）
PATROL_MIN_MAIN_INTERVAL_SEC = 0.6
PATROL_MIN_FRIEND_INTERVAL_SEC = 0.8
PATROL_MIN_CYCLE_GAP_SEC = 0.12
# 主界面巡查：模板匹配阈值（「是否有待办」与「点击」用同一阈值，避免除草等漏判后直接进好友）
MAIN_INTERFACE_PATROL_TEMPLATE_THRESHOLD = 0.35
AFTER_FRIEND_CLICK_SETTLE_SEC = 0.0
FRIEND_FARM_AFTER_HOME_CLICK_SEC = 0.0

# ---- 时间一览（秒；config 可改 main/friend 间隔；其余多为代码常量）----
# main_iv = max(0, config main_patrol_interval_sec)     主界面两轮连点之间
# friend_iv = max(0, config friend_patrol_interval_sec) 好友流程里多处间隔
# 点好友后固定等待：max(AFTER_FRIEND_CLICK_MIN_SETTLE_SEC, AFTER_FRIEND_CLICK_SETTLE_SEC) → 默认 0.22
# 等拜访列表判断图标：最长 max(VISIT_PANEL_JUDGE_MIN_WAIT_SEC, friend_iv*3) → 默认至少 3；轮询步长 max(VISIT_POLL_MIN_SEC, VISIT_PANEL_JUDGE_POLL_SEC) → 默认 0.08
# 点拜访后进农场/封号：最长 max(VISIT_OUTCOME_MIN_WAIT_SEC, friend_iv*2) → 默认至少 5；轮询步长同上底 0.08
# 进农场后偷菜轮间隔：friend_iv（0 则无）；FRIEND_FARM_AFTER_VISIT_SETTLE_SEC / FRIEND_FARM_AFTER_HOME_CLICK_SEC 默认 0
# 无游戏区时：interruptible_sleep(0) 仅让出；异常后同理
# ---------------------------------------------------------------------------

def _diag(category: str, event: str, message: str = "", level: str = "info", **fields: Any) -> None:
    try:
        from diagnostic_logging import log_diagnostic

        log_diagnostic(category, event, message, level=level, **fields)
    except Exception:
        pass


def _spawn_diagnostic_subprocesses(out_list: List[subprocess.Popen]) -> None:
    """可选：后台启动同目录下的辅助脚本（无窗口）。仓库默认不附带子脚本；诊断写入由 diagnostic_logging 完成。"""
    script_dir = Path(__file__).resolve().parent
    py = sys.executable
    names: List[str] = []
    creationflags = 0
    if sys.platform == "win32":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    for name in names:
        path = script_dir / name
        if not path.exists():
            _diag("app", "diag_child_skip", f"未找到子脚本: {name}", level="warn", path=str(path))
            continue
        try:
            kwargs: Dict[str, Any] = {
                "cwd": str(script_dir),
                "stdin": subprocess.DEVNULL,
                "stdout": subprocess.DEVNULL,
                "stderr": subprocess.DEVNULL,
            }
            if sys.platform == "win32" and creationflags:
                kwargs["creationflags"] = creationflags
            else:
                kwargs["start_new_session"] = True
            p = subprocess.Popen([py, str(path)], **kwargs)
            out_list.append(p)
            _diag("app", "diag_child_spawned", name, level="info", pid=p.pid, script=str(path))
        except Exception as exc:
            _diag(
                "app",
                "diag_child_fail",
                str(exc),
                level="warn",
                script=name,
                exc_type=type(exc).__name__,
            )


def _shutdown_diagnostic_subprocesses(procs: List[subprocess.Popen], delay_sec: float = 0.0) -> None:
    """主界面已关闭后结束诊断子进程。"""
    if delay_sec > 0:
        time.sleep(delay_sec)
    for p in procs:
        try:
            if p.poll() is None:
                p.terminate()
        except Exception:
            pass
    if delay_sec > 0:
        time.sleep(0.25)
    for p in procs:
        try:
            if p.poll() is None:
                p.kill()
        except Exception:
            pass


def _diag_init() -> None:
    try:
        from diagnostic_logging import init_diagnostic_logging, log_diagnostic

        p = init_diagnostic_logging(PROJECT_DIR / "logs")
        log_diagnostic("app", "diag_log_ready", f"诊断日志文件: {p}", level="info")
    except Exception as exc:
        try:
            from diagnostic_logging import log_diagnostic

            log_diagnostic("app", "diag_init_failed", str(exc), level="warn")
        except Exception:
            pass


def visit_list_zone_pixel_ranges(
    list_height: int,
    boundaries_rel: Optional[List[float]],
    default_zone_count: int = VISIT_LIST_ZONE_COUNT,
) -> List[Tuple[int, int]]:
    """
    将拜访列表 ROI 的高度按配置切成多段；boundaries_rel 为 0~1 的单调边界，长度 = 区数+1。
    缺省为 default_zone_count 等分。返回 [(y0,y1), ...] 像素行区间（相对列表子图）。
    """
    lh = int(list_height)
    if lh < 2:
        return []
    if boundaries_rel and isinstance(boundaries_rel, list) and len(boundaries_rel) >= 3:
        br = [max(0.0, min(1.0, float(x))) for x in boundaries_rel]
        br.sort()
        br[0] = 0.0
        br[-1] = 1.0
        ranges: List[Tuple[int, int]] = []
        for i in range(len(br) - 1):
            y0 = int(br[i] * lh)
            y1 = int(br[i + 1] * lh)
            y1 = max(y0 + 1, min(lh, y1))
            ranges.append((y0, y1))
        if ranges:
            return ranges
    n = max(1, min(8, int(default_zone_count)))
    return [(i * lh // n, max(i * lh // n + 1, (i + 1) * lh // n)) for i in range(n)]
FEATURES_KEY = "features"
MAIN_INTERFACE_KEY = "main_interface_actions"
STEAL_FEATURE_KEY = "steal_friend_actions"
_rapidocr_engine = None


def save_config_region(region: Dict[str, int]) -> None:
    data = {}
    if CONFIG_PATH.exists():
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))

    data[DEFAULT_REGION_KEY] = region
    CONFIG_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    invalidate_button_band_caches()


def load_config_region() -> Optional[Dict[str, int]]:
    if not CONFIG_PATH.exists():
        return None
    data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    return data.get(DEFAULT_REGION_KEY)


def load_config_all() -> Dict:
    if not CONFIG_PATH.exists():
        return {}
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def save_config_all(data: Dict) -> None:
    CONFIG_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def ocr_extract_text(crop_bgr: np.ndarray) -> str:
    if crop_bgr is None or crop_bgr.size == 0:
        return ""
    try:
        engine = get_rapidocr_engine()
        if engine:
            result, _ = engine(crop_bgr)
            if result:
                return "".join(r[1] for r in result).strip()
    except Exception:
        pass
    try:
        import pytesseract  # type: ignore

        return str(pytesseract.image_to_string(crop_bgr, lang="chi_sim")).strip()
    except Exception:
        return ""


def load_main_interface_actions_enabled() -> Dict[str, bool]:
    data = load_config_all()
    raw = data.get(FEATURES_KEY, {}).get(MAIN_INTERFACE_KEY, {}).get("actions", {})
    defaults = {"收获": False, "浇水": False, "除虫": False, "除草": False}
    for k in defaults:
        if k in raw:
            defaults[k] = bool(raw[k])
    return defaults


def save_main_interface_actions_enabled(actions_enabled: Dict[str, bool]) -> None:
    data = load_config_all()
    data.setdefault(FEATURES_KEY, {})
    data[FEATURES_KEY].setdefault(MAIN_INTERFACE_KEY, {})
    data[FEATURES_KEY][MAIN_INTERFACE_KEY]["actions"] = {
        "收获": bool(actions_enabled.get("收获", False)),
        "浇水": bool(actions_enabled.get("浇水", False)),
        "除虫": bool(actions_enabled.get("除虫", False)),
        "除草": bool(actions_enabled.get("除草", False)),
    }
    save_config_all(data)


def find_main_interface_scene_template_png() -> Optional[Path]:
    d = get_sample_confirm_dir()
    if d:
        p = d / MAIN_INTERFACE_SCENE_TEMPLATE_NAME
        if p.is_file():
            return p
    # 兜底：允许用户放在 yinyong 根目录
    for p in assets_glob_flat_png():
        if p.name == MAIN_INTERFACE_SCENE_TEMPLATE_NAME:
            return p
    return None


def is_main_interface_scene(frame_bgr: np.ndarray, threshold: float = MAIN_INTERFACE_SCENE_THRESHOLD) -> bool:
    tpl = find_main_interface_scene_template_png()
    if tpl is None:
        return False
    m = detect_template_multi_scale(
        frame_bgr,
        tpl,
        threshold=float(threshold),
        scales=PATROL_TEMPLATE_SCALES,
    )
    return m is not None


def load_steal_feature_config() -> Dict:
    data = load_config_all()
    block = data.get(FEATURES_KEY, {}).get(STEAL_FEATURE_KEY, {})
    actions = block.get("actions", {})
    return {
        "master_enabled": bool(block.get("master_enabled", False)),
        "actions": {
            "摘取": bool(actions.get("摘取", False)),
            "浇水": bool(actions.get("浇水", False)),
            "除虫": bool(actions.get("除虫", False)),
            "除草": bool(actions.get("除草", False)),
        },
        "main_patrol_interval_sec": float(block.get("main_patrol_interval_sec", 0.0)),
        "friend_patrol_interval_sec": float(block.get("friend_patrol_interval_sec", 0.0)),
        "main_patrol_threshold": float(block.get("main_patrol_threshold", MAIN_INTERFACE_PATROL_TEMPLATE_THRESHOLD)),
        "friend_patrol_threshold": float(block.get("friend_patrol_threshold", STEAL_UI_MATCH_THRESHOLD)),
        "friend_list_scroll_steps": int(block.get("friend_list_scroll_steps", 0)),
        "visit_zone_boundaries_relative": block.get("visit_zone_boundaries_relative"),
    }


def save_steal_feature_config(
    master_enabled: bool,
    actions: Dict[str, bool],
    main_interval: float,
    friend_interval: float,
    main_threshold: float = MAIN_INTERFACE_PATROL_TEMPLATE_THRESHOLD,
    friend_threshold: float = STEAL_UI_MATCH_THRESHOLD,
    friend_list_scroll_steps: int = 0,
) -> None:
    data = load_config_all()
    data.setdefault(FEATURES_KEY, {})
    prev = dict(data[FEATURES_KEY].get(STEAL_FEATURE_KEY, {}))
    prev.update(
        {
            "master_enabled": bool(master_enabled),
            "actions": {
                "摘取": bool(actions.get("摘取", False)),
                "浇水": bool(actions.get("浇水", False)),
                "除虫": bool(actions.get("除虫", False)),
                "除草": bool(actions.get("除草", False)),
            },
            "main_patrol_interval_sec": float(main_interval),
            "friend_patrol_interval_sec": float(friend_interval),
            "main_patrol_threshold": max(0.0, min(1.0, float(main_threshold))),
            "friend_patrol_threshold": max(0.0, min(1.0, float(friend_threshold))),
            "friend_list_scroll_steps": max(0, int(friend_list_scroll_steps)),
        }
    )
    data[FEATURES_KEY][STEAL_FEATURE_KEY] = prev
    save_config_all(data)


def load_visit_check_roi_relative() -> Optional[Dict[str, float]]:
    data = load_config_all()
    roi = data.get(FEATURES_KEY, {}).get(STEAL_FEATURE_KEY, {}).get("visit_check_roi_relative")
    if not roi or not isinstance(roi, dict):
        return None
    needed = ("x1", "y1", "x2", "y2")
    if not all(k in roi for k in needed):
        return None
    return {k: float(roi[k]) for k in needed}


def save_visit_check_roi_relative(roi: Dict[str, float]) -> None:
    data = load_config_all()
    data.setdefault(FEATURES_KEY, {})
    data[FEATURES_KEY].setdefault(STEAL_FEATURE_KEY, {})
    data[FEATURES_KEY][STEAL_FEATURE_KEY]["visit_check_roi_relative"] = roi
    save_config_all(data)


def interruptible_sleep(stop_event: Optional[threading.Event], total_sec: float, slice_sec: float = 0.05) -> bool:
    """
    将睡眠拆成小段，便于「停止巡查」尽快生效。
    返回 True 表示 stop_event 已置位，巡查线程应立刻退出。
    """
    if total_sec <= 0:
        return bool(stop_event and stop_event.is_set())
    if stop_event is None:
        time.sleep(total_sec)
        return False
    elapsed = 0.0
    while elapsed < total_sec - 1e-9:
        if stop_event.is_set():
            return True
        chunk = min(slice_sec, total_sec - elapsed)
        time.sleep(chunk)
        elapsed += chunk
    return stop_event.is_set()


def capture_fullscreen_bgr() -> np.ndarray:
    with mss.mss() as sct:
        monitor = sct.monitors[0]
        shot = sct.grab(monitor)
        frame = np.array(shot)[:, :, :3]
    return frame


def get_default_reference_image() -> Optional[Path]:
    """自动定位用参考图：优先固定文件名，避免误用目录里按字母排序的第一张小按钮图。"""
    if not any_assets_root_exists():
        return None
    for name in (
        "窗口定位参考.png",
        "游戏窗口参考.png",
        "window_reference.png",
        "game_region_ref.png",
        "reference.png",
    ):
        p = resolve_asset_png_path(name)
        if p is not None:
            return p
    candidates = assets_glob_flat_png()
    if not candidates:
        candidates = assets_rglob_png()
    if not candidates:
        return None
    return candidates[0]


def read_image_compat(path: str) -> Optional[np.ndarray]:
    # cv2.imread can fail on some Windows unicode paths; use imdecode fallback.
    # Cache decoded templates to reduce repeated disk IO + decode cost.
    try:
        st = Path(path).stat()
        mtime = float(st.st_mtime)
        size = int(st.st_size)
    except Exception:
        mtime = -1.0
        size = -1
    cached = _image_cache.get(path)
    if cached and cached[0] == mtime and cached[1] == size:
        return cached[2]
    data = np.fromfile(path, dtype=np.uint8)
    if data.size == 0:
        return None
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if img is None:
        return None
    _image_cache[path] = (mtime, size, img)
    return img


def _get_template_gray_cached(template_path: Path, template_height_frac: Optional[float]) -> Optional[np.ndarray]:
    key = (str(template_path), float(template_height_frac) if template_height_frac is not None else 1.0)
    try:
        st = template_path.stat()
        mtime = float(st.st_mtime)
        size = int(st.st_size)
    except Exception:
        mtime = -1.0
        size = -1
    cached = _template_gray_cache.get(key)
    if cached and cached[0] == mtime and cached[1] == size:
        return cached[2]
    tpl = read_image_compat(str(template_path))
    if tpl is None:
        return None
    if template_height_frac is not None and 0 < template_height_frac < 1.0:
        hh = int(tpl.shape[0] * float(template_height_frac))
        hh = max(4, min(hh, tpl.shape[0]))
        tpl = tpl[:hh, :, :]
    tpl_gray = cv2.cvtColor(tpl, cv2.COLOR_BGR2GRAY)
    _template_gray_cache[key] = (mtime, size, tpl_gray)
    return tpl_gray


def hide_console_on_windows() -> None:
    try:
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 0)
    except Exception:
        # Non-Windows or restricted environment: ignore.
        pass


def draw_text_zh(
    canvas: np.ndarray,
    text: str,
    origin: Tuple[int, int],
    font_size: int = 24,
    color: Tuple[int, int, int] = (255, 255, 255),
) -> None:
    # Use PIL to render Chinese text; OpenCV putText cannot render CJK reliably.
    rgb = cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB)
    image = Image.fromarray(rgb)
    draw = ImageDraw.Draw(image)
    font = None
    for font_path in ["C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf", "C:/Windows/Fonts/simsun.ttc"]:
        if Path(font_path).exists():
            font = ImageFont.truetype(font_path, font_size)
            break
    if font is None:
        font = ImageFont.load_default()
    draw.text(origin, text, font=font, fill=(color[2], color[1], color[0]))
    canvas[:, :] = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)


def measure_text_zh(text: str, font_size: int = 24) -> Tuple[int, int]:
    font = None
    for font_path in ["C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf", "C:/Windows/Fonts/simsun.ttc"]:
        if Path(font_path).exists():
            font = ImageFont.truetype(font_path, font_size)
            break
    if font is None:
        font = ImageFont.load_default()
    box = font.getbbox(text)
    return int(box[2] - box[0]), int(box[3] - box[1])


def validate_region(region: Dict[str, int]) -> bool:
    return (
        region["x"] >= 0
        and region["y"] >= 0
        and region["w"] >= 320
        and region["h"] >= 200
    )


def center_to_region(center: Tuple[int, int], width: int, height: int, screen_w: int, screen_h: int) -> Dict[str, int]:
    cx, cy = center
    x = max(0, int(cx - width / 2))
    y = max(0, int(cy - height / 2))

    if x + width > screen_w:
        x = max(0, screen_w - width)
    if y + height > screen_h:
        y = max(0, screen_h - height)

    return {"x": x, "y": y, "w": width, "h": height}


def locate_by_reference(
    screen_bgr: np.ndarray,
    reference_path: str,
    threshold: float = 0.7,
    expected_region_size: Tuple[int, int] = (1280, 720),
    auto_region_mode: str = "match",
) -> Tuple[Optional[Dict[str, int]], float]:
    """
    在整屏截图里用参考图定位游戏客户端区域。
    主场景：窗口被拖动、缩放、换屏、重开或从最小化恢复后，反复「重锁」截图范围，而不必每次手动画框。
    """
    ref = read_image_compat(reference_path)
    if ref is None:
        raise FileNotFoundError(f"Cannot read reference image: {reference_path}")

    screen_gray = cv2.cvtColor(screen_bgr, cv2.COLOR_BGR2GRAY)
    ref_gray = cv2.cvtColor(ref, cv2.COLOR_BGR2GRAY)

    best_score = -1.0
    best_center = None
    best_rect = None
    # 含较小尺度：参考图为整窗大图时，必须缩到比屏幕小才能 matchTemplate；原仅 0.75 起易「全盘跳过」→ best 永远为空
    scales = [0.38, 0.48, 0.58, 0.68, 0.78, 0.88, 1.0, 1.12, 1.24, 1.36]
    sw, sh = int(screen_gray.shape[1]), int(screen_gray.shape[0])

    for scale in scales:
        tw = max(16, int(round(ref_gray.shape[1] * scale)))
        th = max(16, int(round(ref_gray.shape[0] * scale)))
        # 须严格小于画布：原用 >= 会在「模板宽刚好等于屏宽」时误跳过；OpenCV 允许 tw==sw 时仍可得 1 列结果
        if tw > sw or th > sh:
            continue

        resized = cv2.resize(ref_gray, (tw, th), interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC)
        result = cv2.matchTemplate(screen_gray, resized, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)

        if max_val > best_score:
            best_score = float(max_val)
            best_center = (max_loc[0] + tw // 2, max_loc[1] + th // 2)
            best_rect = (max_loc[0], max_loc[1], tw, th)

    if best_center is None or best_score < threshold:
        return None, best_score

    screen_h, screen_w = screen_bgr.shape[:2]

    if auto_region_mode == "match":
        if best_rect is None:
            return None, best_score
        x, y, w, h = best_rect
        region = {"x": int(x), "y": int(y), "w": int(w), "h": int(h)}
    else:
        region = center_to_region(best_center, expected_region_size[0], expected_region_size[1], screen_w, screen_h)

    # 参考图多为标题栏/角标等小图时，match 得到的矩形只是模板大小，会小于 validate_region 下限，
    # 此前会被误判为「定位失败」。换窗口、重开客户端后重读区域时同样踩坑。
    # 回退：以匹配中心为锚点，用期望宽高框出整窗（与 --auto-region-mode fixed 一致）。
    if not validate_region(region):
        region = center_to_region(best_center, expected_region_size[0], expected_region_size[1], screen_w, screen_h)

    if not validate_region(region):
        return None, best_score
    return region, best_score


def manual_select_region(screen_bgr: np.ndarray) -> Dict[str, int]:
    base_frame = screen_bgr.copy()
    window_name = "手动框取游戏窗口"
    state = {
        "drawing": False,
        "start": None,
        "rect": None,  # (x, y, w, h)
        "confirm_btn": None,  # (x1, y1, x2, y2)
        "retry_btn": None,
        "cancel_btn": None,
        "confirmed": False,
        "cancelled": False,
        "cursor": (0, 0),
    }

    def clamp(val: int, lo: int, hi: int) -> int:
        return max(lo, min(hi, val))

    def rect_from_points(p1: Tuple[int, int], p2: Tuple[int, int]) -> Tuple[int, int, int, int]:
        x1 = min(p1[0], p2[0])
        y1 = min(p1[1], p2[1])
        x2 = max(p1[0], p2[0])
        y2 = max(p1[1], p2[1])
        return x1, y1, x2 - x1, y2 - y1

    def point_in_btn(px: int, py: int, btn: Optional[Tuple[int, int, int, int]]) -> bool:
        if not btn:
            return False
        x1, y1, x2, y2 = btn
        return x1 <= px <= x2 and y1 <= py <= y2

    def draw_button(canvas: np.ndarray, btn: Tuple[int, int, int, int], text: str, color: Tuple[int, int, int]) -> None:
        x1, y1, x2, y2 = btn
        cv2.rectangle(canvas, (x1, y1), (x2, y2), color, -1)
        cv2.rectangle(canvas, (x1, y1), (x2, y2), (30, 30, 30), 1)
        tw, th = measure_text_zh(text, font_size=22)
        tx = x1 + max(6, (x2 - x1 - tw) // 2)
        ty = y1 + max(2, (y2 - y1 - th) // 2 - 2)
        draw_text_zh(canvas, text, (tx, ty), font_size=22, color=(255, 255, 255))

    def layout_buttons(rect: Tuple[int, int, int, int], img_w: int, img_h: int) -> Tuple[Tuple[int, int, int, int], Tuple[int, int, int, int], Tuple[int, int, int, int]]:
        x, y, w, h = rect
        bw, bh, gap = 96, 40, 8
        total_w = bw * 3 + gap * 2
        bx = clamp(x + w + 10, 10, max(10, img_w - total_w - 10))
        by = clamp(y, 10, max(10, img_h - bh - 10))
        confirm = (bx, by, bx + bw, by + bh)
        retry = (bx + bw + gap, by, bx + bw * 2 + gap, by + bh)
        cancel = (bx + bw * 2 + gap * 2, by, bx + bw * 3 + gap * 2, by + bh)
        return confirm, retry, cancel

    def draw_magnifier(canvas: np.ndarray, cursor: Tuple[int, int]) -> None:
        cx, cy = cursor
        h, w = canvas.shape[:2]
        half = 20
        zoom = 4
        x1 = clamp(cx - half, 0, w - 1)
        y1 = clamp(cy - half, 0, h - 1)
        x2 = clamp(cx + half, 0, w - 1)
        y2 = clamp(cy + half, 0, h - 1)
        if x2 <= x1 or y2 <= y1:
            return

        patch = canvas[y1:y2, x1:x2]
        mag = cv2.resize(patch, ((x2 - x1) * zoom, (y2 - y1) * zoom), interpolation=cv2.INTER_NEAREST)
        mh, mw = mag.shape[:2]
        ox, oy = 30, 60
        ox2 = min(w - 10, ox + mw)
        oy2 = min(h - 10, oy + mh)
        mag = mag[: oy2 - oy, : ox2 - ox]
        canvas[oy:oy2, ox:ox2] = mag
        cv2.rectangle(canvas, (ox, oy), (ox2, oy2), (0, 255, 255), 2)
        cv2.line(canvas, (ox + (ox2 - ox) // 2, oy), (ox + (ox2 - ox) // 2, oy2), (0, 255, 255), 1)
        cv2.line(canvas, (ox, oy + (oy2 - oy) // 2), (ox2, oy + (oy2 - oy) // 2), (0, 255, 255), 1)
        draw_text_zh(canvas, "放大镜", (ox, oy - 32), font_size=24, color=(0, 255, 255))

    def redraw(mx: Optional[int] = None, my: Optional[int] = None) -> None:
        canvas = base_frame.copy()
        draw_text_zh(canvas, "拖拽框选窗口，点击 确认/重选/取消，按 ESC 取消", (14, 8), font_size=28, color=(10, 220, 10))

        active_rect = state["rect"]
        if state["drawing"] and state["start"] is not None and mx is not None and my is not None:
            active_rect = rect_from_points(state["start"], (mx, my))

        if active_rect:
            x, y, w, h = active_rect
            cv2.rectangle(canvas, (x, y), (x + w, y + h), (0, 220, 255), 2)
            cv2.putText(
                canvas,
                f"{w}x{h}",
                (x, max(20, y - 8)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (0, 220, 255),
                2,
                cv2.LINE_AA,
            )
            confirm, retry, cancel = layout_buttons(active_rect, canvas.shape[1], canvas.shape[0])
            state["confirm_btn"], state["retry_btn"], state["cancel_btn"] = confirm, retry, cancel
            draw_button(canvas, confirm, "确认", (30, 150, 40))
            draw_button(canvas, retry, "重选", (180, 120, 10))
            draw_button(canvas, cancel, "取消", (150, 30, 30))
        else:
            state["confirm_btn"] = None
            state["retry_btn"] = None
            state["cancel_btn"] = None

        draw_magnifier(canvas, state["cursor"])
        cv2.imshow(window_name, canvas)

    def on_mouse(event: int, x: int, y: int, flags: int, param: object) -> None:
        _ = flags, param
        if event == cv2.EVENT_LBUTTONDOWN:
            if point_in_btn(x, y, state["confirm_btn"]) and state["rect"] is not None:
                state["confirmed"] = True
                return
            if point_in_btn(x, y, state["retry_btn"]):
                state["rect"] = None
                redraw(x, y)
                return
            if point_in_btn(x, y, state["cancel_btn"]):
                state["cancelled"] = True
                return
            state["drawing"] = True
            state["start"] = (x, y)
        elif event == cv2.EVENT_MOUSEMOVE:
            state["cursor"] = (x, y)
            if state["drawing"]:
                # live frame is redrawn in main loop
                return
        elif event == cv2.EVENT_LBUTTONUP:
            if state["drawing"] and state["start"] is not None:
                state["drawing"] = False
                state["rect"] = rect_from_points(state["start"], (x, y))
                state["start"] = None
                state["cursor"] = (x, y)

    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    cv2.setWindowProperty(window_name, cv2.WND_PROP_TOPMOST, 1)
    cv2.setWindowProperty(window_name, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
    cv2.setMouseCallback(window_name, on_mouse)
    redraw()

    while True:
        redraw(state["cursor"][0], state["cursor"][1])
        key = cv2.waitKey(30) & 0xFF
        if key == 27:  # ESC
            state["cancelled"] = True
        if state["cancelled"]:
            cv2.destroyWindow(window_name)
            raise RuntimeError("Manual selection cancelled.")
        if state["confirmed"]:
            cv2.destroyWindow(window_name)
            if not state["rect"]:
                raise ValueError("No region selected.")
            x, y, w, h = state["rect"]
            region = {"x": int(x), "y": int(y), "w": int(w), "h": int(h)}
            if not validate_region(region):
                raise ValueError(f"Invalid region selected: {region}")
            return region


def acquire_game_region_auto(
    reference_image: str,
    threshold: float = 0.7,
    expected_region_size: Tuple[int, int] = (1280, 720),
    auto_region_mode: str = "match",
) -> Dict[str, int]:
    """
    自动锁定游戏区域并写入配置。
    为「窗口位置/大小经常变」设计的常规操作：点一次即可在全屏里用参考图重新对齐；手动框选仅用于首次或自动失败。
    """
    screen_bgr = capture_fullscreen_bgr()

    # 同一画面下逐级放宽阈值，避免界面略糊/缩放导致单次 0.7 永远过不去
    th_sequence: List[float] = [float(threshold)]
    for t in (0.62, 0.55, 0.48, 0.42):
        if t >= th_sequence[-1] - 1e-6:
            continue
        if any(abs(t - x) < 1e-9 for x in th_sequence):
            continue
        th_sequence.append(t)

    last_score = -1.0
    region: Optional[Dict[str, int]] = None
    used_th = float(threshold)
    for th in th_sequence:
        used_th = th
        region, last_score = locate_by_reference(
            screen_bgr=screen_bgr,
            reference_path=reference_image,
            threshold=th,
            expected_region_size=expected_region_size,
            auto_region_mode=auto_region_mode,
        )
        if region:
            break

    if not region:
        ref_name = Path(reference_image).name
        if last_score < 0:
            hint = (
                "程序在截图里无法用参考图做任何尺度匹配（常为参考图比整屏还大，或 yinyong 里默认图不对）。"
                "请换一张较小的特征图（如标题条一角）存为 assets/yinyong/窗口定位参考.png。"
            )
        elif last_score < 0.35:
            hint = (
                "相似度很低：游戏是否被最小化/挡在后面？请把游戏窗口完整露在当前桌面再试，"
                "或换与当前界面一致的参考图。"
            )
        else:
            hint = (
                f"最高相似度 {last_score:.3f}，已依次尝试阈值 {th_sequence}。"
                "可命令行加 --threshold 0.5 再试，或截取与现在窗口一致的小块 UI 作参考图。"
            )
        raise RuntimeError(
            f"未在屏幕中找到与参考图「{ref_name}」足够吻合的区域（最高相似度 {last_score:.3f}，末次阈值 {used_th:g}）。{hint}"
        )

    save_config_region(region)
    print(f"[AUTO] Match score: {last_score:.3f} (threshold tried down to {used_th:g})")
    print(f"[AUTO] Region saved: {region}")
    return region


def acquire_game_region_manual() -> Dict[str, int]:
    """全屏上手动画框游戏区域；用于首次配置或自动锁定无法识别时。"""
    screen_bgr = capture_fullscreen_bgr()
    region = manual_select_region(screen_bgr)
    save_config_region(region)
    print(f"[MANUAL] Region saved: {region}")
    return region


def capture_game_region() -> np.ndarray:
    region = load_config_region()
    if not region:
        raise RuntimeError("No game region in config. Run acquire first.")

    with mss.mss() as sct:
        shot = sct.grab(
            {
                "left": region["x"],
                "top": region["y"],
                "width": region["w"],
                "height": region["h"],
            }
        )
    return np.array(shot)[:, :, :3]


def save_preview(path: str = str(ASSETS_ROOT / "game_preview.png")) -> Dict[str, int]:
    region = load_config_region()
    if not region:
        raise RuntimeError("No game region in config. Please acquire region first.")
    img = capture_game_region()
    cv2.imwrite(path, img)
    return region


def _band_to_pixel_rect(
    band: Optional[Dict[str, float]], frame_shape: Tuple[int, ...]
) -> Optional[Tuple[int, int, int, int]]:
    if not band:
        return None
    h, w = frame_shape[:2]
    x1 = int(max(0, min(w - 1, float(band["x1"]) * w)))
    y1 = int(max(0, min(h - 1, float(band["y1"]) * h)))
    x2 = int(max(x1 + 1, min(w, float(band["x2"]) * w)))
    y2 = int(max(y1 + 1, min(h, float(band["y2"]) * h)))
    return x1, y1, x2, y2


def _save_friend_click_debug_image(
    frame_bgr: np.ndarray,
    stage: str,
    source: str,
    threshold: float,
    template_name: str,
    click_xy: Optional[Tuple[int, int]] = None,
    score: Optional[float] = None,
    roi_rect: Optional[Tuple[int, int, int, int]] = None,
) -> Optional[str]:
    if not FRIEND_CLICK_DEBUG_IMAGES_ENABLED:
        return None
    try:
        img = frame_bgr.copy()
        if roi_rect is not None:
            x1, y1, x2, y2 = roi_rect
            cv2.rectangle(img, (x1, y1), (x2, y2), (255, 140, 0), 2)
        if click_xy is not None:
            cx, cy = int(click_xy[0]), int(click_xy[1])
            cv2.circle(img, (cx, cy), 10, (0, 0, 255), 2)
            cv2.line(img, (cx - 12, cy), (cx + 12, cy), (0, 0, 255), 2)
            cv2.line(img, (cx, cy - 12), (cx, cy + 12), (0, 0, 255), 2)
        lines = [
            f"stage={stage} source={source}",
            f"threshold={threshold:.3f}",
            f"score={score:.3f}" if score is not None else "score=n/a",
            f"template={template_name}",
        ]
        y = 26
        for line in lines:
            cv2.putText(img, line, (12, y), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (0, 255, 255), 2, cv2.LINE_AA)
            y += 26
        out_dir = PROJECT_DIR / "logs" / "debug_clicks"
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        out_path = out_dir / f"friend_{stage}_{stamp}.png"
        ok = cv2.imwrite(str(out_path), img)
        if not ok:
            return None
        return str(out_path)
    except Exception:
        return None


def detect_template_center(frame_bgr: np.ndarray, template_path: Path, threshold: float = 0.72) -> Optional[Tuple[int, int, float]]:
    tpl = read_image_compat(str(template_path))
    if tpl is None:
        return None
    src_gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
    tpl_gray = cv2.cvtColor(tpl, cv2.COLOR_BGR2GRAY)
    if tpl_gray.shape[0] >= src_gray.shape[0] or tpl_gray.shape[1] >= src_gray.shape[1]:
        return None
    result = cv2.matchTemplate(src_gray, tpl_gray, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(result)
    if float(max_val) < threshold:
        return None
    cx = int(max_loc[0] + tpl_gray.shape[1] / 2)
    cy = int(max_loc[1] + tpl_gray.shape[0] / 2)
    return cx, cy, float(max_val)


def detect_template_multi_scale(
    frame_bgr: np.ndarray,
    template_path: Path,
    threshold: float = 0.7,
    scales: Optional[List[float]] = None,
    template_height_frac: Optional[float] = None,
) -> Optional[Tuple[int, int, float]]:
    tpl_gray = _get_template_gray_cached(template_path, template_height_frac)
    if tpl_gray is None:
        return None
    src_gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
    if scales is None:
        scales = [0.75, 0.85, 1.0, 1.15, 1.3]

    best = None
    best_score = -1.0
    for scale in scales:
        tw = max(12, int(tpl_gray.shape[1] * scale))
        th = max(12, int(tpl_gray.shape[0] * scale))
        if tw >= src_gray.shape[1] or th >= src_gray.shape[0]:
            continue
        resized = cv2.resize(tpl_gray, (tw, th), interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC)
        result = cv2.matchTemplate(src_gray, resized, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)
        if float(max_val) > best_score:
            best_score = float(max_val)
            best = (int(max_loc[0] + tw / 2), int(max_loc[1] + th / 2), best_score)
    if not best or best_score < threshold:
        # 背景鲁棒兜底：按钮半透明时，土地/篱笆等底纹会拖低灰度匹配分，改用边缘特征再匹配一次。
        # 仅对按钮类模板启用，避免影响场景类模板的判定稳定性。
        n = template_path.name
        button_like = ("一键" in n) or ("按钮" in n)
        if not button_like:
            return None
        src_edge = cv2.Canny(cv2.GaussianBlur(src_gray, (3, 3), 0), 60, 160)
        tpl_edge_base = cv2.Canny(cv2.GaussianBlur(tpl_gray, (3, 3), 0), 60, 160)
        if int(np.count_nonzero(src_edge)) < 40 or int(np.count_nonzero(tpl_edge_base)) < 20:
            return None
        edge_best = None
        edge_best_score = -1.0
        for scale in scales:
            tw = max(12, int(tpl_edge_base.shape[1] * scale))
            th = max(12, int(tpl_edge_base.shape[0] * scale))
            if tw >= src_edge.shape[1] or th >= src_edge.shape[0]:
                continue
            resized = cv2.resize(
                tpl_edge_base,
                (tw, th),
                interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC,
            )
            result = cv2.matchTemplate(src_edge, resized, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(result)
            if float(max_val) > edge_best_score:
                edge_best_score = float(max_val)
                edge_best = (int(max_loc[0] + tw / 2), int(max_loc[1] + th / 2), edge_best_score)
        edge_threshold = max(0.46, float(threshold) - 0.12)
        if not edge_best or edge_best_score < edge_threshold:
            return None
        return edge_best
    return best


def detect_template_multi_scale_steal_ui(
    frame_bgr: np.ndarray,
    template_path: Path,
    base_threshold: float = STEAL_UI_MATCH_THRESHOLD,
    scales: Optional[List[float]] = None,
) -> Optional[Tuple[int, int, float]]:
    """
    好友农场「一键」按钮：底部条带/异色时整图匹配易失败，用更宽尺度 + 仅用模板上半部回退匹配。
    scales 默认全量；巡查可传 STEAL_UI_TEMPLATE_SCALES_FAST 降延迟。
    """
    sc = scales if scales is not None else STEAL_UI_TEMPLATE_SCALES
    m = detect_template_multi_scale(
        frame_bgr, template_path, threshold=base_threshold, scales=sc
    )
    if m:
        return m
    t2 = max(0.52, base_threshold - 0.06)
    m = detect_template_multi_scale(
        frame_bgr,
        template_path,
        threshold=t2,
        scales=sc,
        template_height_frac=0.78,
    )
    if m:
        return m
    t3 = max(0.48, base_threshold - 0.11)
    return detect_template_multi_scale(
        frame_bgr,
        template_path,
        threshold=t3,
        scales=sc,
        template_height_frac=0.64,
    )


def get_main_action_templates() -> List[Tuple[str, Path]]:
    # Prefer user-provided Chinese template names.
    keyword_map = [
        ("收获", ["收获", "摘取"]),
        ("浇水", ["浇水"]),
        ("除虫", ["除虫"]),
        ("除草", ["除草"]),
    ]
    paths = assets_glob_flat_png()
    found: List[Tuple[str, Path]] = []
    for action_name, keywords in keyword_map:
        picked = None
        for p in paths:
            name = p.name
            if "主界面" not in name:
                continue
            if any(k in name for k in keywords):
                picked = p
                break
        if picked:
            found.append((action_name, picked))
    return found


def _union_relative_bands(
    a: Dict[str, float], b: Dict[str, float]
) -> Dict[str, float]:
    return {
        "x1": max(0.0, min(float(a["x1"]), float(b["x1"]))),
        "y1": max(0.0, min(float(a["y1"]), float(b["y1"]))),
        "x2": min(1.0, max(float(a["x2"]), float(b["x2"]))),
        "y2": min(1.0, max(float(a["y2"]), float(b["y2"]))),
    }


def _calibrate_main_button_band_from_template_samples() -> Optional[Dict[str, float]]:
    """用确认样图里主界面一键模板命中点推算条带（排除「仅红框检测区域」图）。"""
    sample_dirs = [
        d for d in assets_iter_subdirs() if "主界面按钮区域确认样图" in d.name
    ]
    if not sample_dirs:
        return None
    templates = get_main_action_templates()
    if not templates:
        return None
    sample_pngs = sorted(sample_dirs[0].glob("*.png"))
    if not sample_pngs:
        return None

    min_x, min_y = 1.0, 1.0
    max_x, max_y = 0.0, 0.0
    hits = 0
    for sample in sample_pngs:
        if not _is_template_calibration_sample_png(sample):
            continue
        img = read_image_compat(str(sample))
        if img is None:
            continue
        h, w = img.shape[:2]
        for _, t in templates:
            match = detect_template_multi_scale(img, t, threshold=0.58)
            if not match:
                continue
            cx, cy, _ = match
            min_x = min(min_x, cx / w)
            max_x = max(max_x, cx / w)
            min_y = min(min_y, cy / h)
            max_y = max(max_y, cy / h)
            hits += 1
    if hits == 0:
        return None

    reg = load_config_region()
    gw = max(1, int(reg["w"])) if reg else 960
    gh = max(1, int(reg["h"])) if reg else 540
    pad_x = min(0.12, 5.0 / float(gw))
    pad_y = min(0.15, 5.0 / float(gh))
    return {
        "x1": max(0.0, min_x - pad_x),
        "y1": max(0.0, min_y - pad_y),
        "x2": min(1.0, max_x + pad_x),
        "y2": min(1.0, max_y + pad_y),
    }


def locate_button_band_relative() -> Optional[Dict[str, float]]:
    z = locate_action_bar_band_from_detection_zone_sample()
    t = _calibrate_main_button_band_from_template_samples()
    if z is not None and t is not None:
        return _union_relative_bands(z, t)
    if z is not None:
        return z
    return t


def default_steal_action_band_relative() -> Dict[str, float]:
    """无「偷菜界面按钮区域确认样图」时：监控窗口底部约 30%（一键条常见位置）。"""
    return {"x1": 0.0, "y1": 0.70, "x2": 1.0, "y2": 1.0}


def locate_steal_button_band_relative() -> Optional[Dict[str, float]]:
    # 好友农场按钮区域优先由样图红框推导，失败时走稳态回退 ROI。
    if not any_assets_root_exists():
        return None
    sample_pngs: List[Path] = []
    for root in search_roots():
        sample_pngs.extend(
            sorted(
                [
                    p
                    for p in root.glob("*.png")
                    if ("偷菜" in p.name or "好友农场" in p.name) and "红框" in p.name
                ]
            )
        )
        for d in root.iterdir():
            if not d.is_dir():
                continue
            if "偷菜" not in d.name and "好友农场" not in d.name:
                continue
            if "红框" in d.name or "按钮" in d.name or "区域" in d.name or "样图" in d.name:
                sample_pngs.extend(sorted(d.glob("*.png")))
    for p in sorted(sample_pngs):
        if "红框" not in p.name:
            continue
        img = read_image_compat(str(p))
        if img is None or img.size == 0:
            continue
        r = detect_red_box_roi_relative(img)
        if not r:
            continue
        reg = load_config_region()
        gw = max(1, int(reg["w"])) if reg else img.shape[1]
        gh = max(1, int(reg["h"])) if reg else img.shape[0]
        return _pad_relative_band_for_game_window(r, gw, gh)
    return None


def locate_button_band_relative_cached() -> Optional[Dict[str, float]]:
    global _main_button_band_cache, _main_button_band_cache_wh
    reg = load_config_region()
    wh = (int(reg["w"]), int(reg["h"])) if reg else (0, 0)
    if _main_button_band_cache is not None and _main_button_band_cache_wh == wh:
        return _main_button_band_cache
    band = locate_button_band_relative()
    _main_button_band_cache = band
    _main_button_band_cache_wh = wh
    return band


def locate_steal_button_band_relative_cached() -> Dict[str, float]:
    global _steal_button_band_cache, _steal_button_band_cache_wh
    reg = load_config_region()
    wh = (int(reg["w"]), int(reg["h"])) if reg else (0, 0)
    if _steal_button_band_cache is not None and _steal_button_band_cache_wh == wh:
        return _steal_button_band_cache
    band = locate_steal_button_band_relative()
    if band is None:
        band = default_steal_action_band_relative()
    _steal_button_band_cache = band
    _steal_button_band_cache_wh = wh
    return band


def crop_by_relative_band(frame: np.ndarray, band: Optional[Dict[str, float]]) -> Tuple[np.ndarray, int, int]:
    if not band:
        return frame, 0, 0
    h, w = frame.shape[:2]
    x1 = int(max(0, min(w - 1, band["x1"] * w)))
    y1 = int(max(0, min(h - 1, band["y1"] * h)))
    x2 = int(max(x1 + 1, min(w, band["x2"] * w)))
    y2 = int(max(y1 + 1, min(h, band["y2"] * h)))
    return frame[y1:y2, x1:x2], x1, y1


def get_rapidocr_engine():
    global _rapidocr_engine
    if _rapidocr_engine is None:
        try:
            from rapidocr_onnxruntime import RapidOCR  # type: ignore

            _rapidocr_engine = RapidOCR()
        except Exception:
            _rapidocr_engine = False  # type: ignore
    if _rapidocr_engine is False:
        return None
    return _rapidocr_engine


def ocr_matches_action(crop_bgr: np.ndarray, expected_action: str) -> bool:
    try:
        engine = get_rapidocr_engine()
        if engine is None:
            raise RuntimeError("no rapidocr")
        result, _ = engine(crop_bgr)
        text = "".join([r[1] for r in result]) if result else ""
        if expected_action in text:
            return True
        if expected_action == "摘取" and ("偷" in text or "摘" in text):
            return True
        if expected_action == "收获" and "摘" in text:
            return True
        # 除草/除虫/浇水：OCR 常识别成半边字或近形字，放宽匹配以免误判「无待办」而跳过主界面
        if expected_action == "除草" and (
            "除草" in text or "草" in text or ("除" in text and "草" in text)
        ):
            return True
        if expected_action == "除虫" and (
            "除虫" in text
            or "虫害" in text
            or "虫" in text
            or "害" in text
            or ("除" in text and "虫" in text)
        ):
            return True
        if expected_action == "浇水" and ("浇水" in text or "浇" in text):
            return True
        return False
    except Exception:
        try:
            import pytesseract  # type: ignore

            txt = pytesseract.image_to_string(crop_bgr, lang="chi_sim")
            if expected_action in txt:
                return True
            if expected_action == "摘取" and ("偷" in txt or "摘" in txt):
                return True
            if expected_action == "收获" and "摘" in txt:
                return True
            if expected_action == "除草" and (
                "除草" in txt or "草" in txt or ("除" in txt and "草" in txt)
            ):
                return True
            if expected_action == "除虫" and (
                "除虫" in txt
                or "虫害" in txt
                or "虫" in txt
                or "害" in txt
                or ("除" in txt and "虫" in txt)
            ):
                return True
            if expected_action == "浇水" and ("浇水" in txt or "浇" in txt):
                return True
            return False
        except Exception:
            return True


def run_main_interface_actions_once(
    actions_enabled: Dict[str, bool],
    threshold: float = 0.7,
    ocr_enabled: bool = False,
    stop_event: Optional[threading.Event] = None,
    max_action_rounds: int = 6,
    template_scales: Optional[List[float]] = None,
) -> Dict[str, str]:
    enabled_actions = [k for k, v in actions_enabled.items() if v]
    if not enabled_actions:
        return {"status": "skipped", "message": "未勾选任何动作（收获/浇水/除虫/除草），已跳过点击操作。"}

    region = load_config_region()
    if not region:
        return {"status": "error", "message": "未设置游戏窗口，请先执行自动读取或手动框取。"}
    try:
        frame_scene = capture_game_region()
    except Exception as exc:
        return {"status": "error", "message": f"截图失败：{exc}"}
    if find_main_interface_scene_template_png() is None:
        return {"status": "error", "message": f"缺少主界面判定模板：{MAIN_INTERFACE_SCENE_TEMPLATE_NAME}"}
    if not is_main_interface_scene(frame_scene, threshold=MAIN_INTERFACE_SCENE_THRESHOLD):
        _diag("main_worker", "not_main_interface_scene", "当前不在主界面，已跳过主界面任务", level="warn")
        return {"status": "skipped", "message": "当前不在主界面（主界面判定模板未命中），已跳过主界面任务。"}

    templates = [(name, path) for name, path in get_main_action_templates() if actions_enabled.get(name, False)]
    if not templates:
        return {
            "status": "error",
            "message": "已勾选的动作未找到模板图，请确认 assets/yinyong 下有对应“主界面-一键*.png”。",
        }

    band_cached = locate_action_bar_band_from_detection_zone_sample()
    if band_cached is None:
        return {"status": "error", "message": "未找到主界面按钮检测红框区域（主界面-按钮检测区域.png）。"}
    bands_to_try: List[Optional[Dict[str, float]]] = [band_cached]
    clicked = []
    for band in bands_to_try:
        if clicked:
            break
        rounds = max(1, int(max_action_rounds))
        for _round in range(rounds):
            if stop_event and stop_event.is_set():
                return {"status": "stopped", "message": "已停止。"}
            frame = capture_game_region()
            roi, offset_x, offset_y = crop_by_relative_band(frame, band)
            round_hit = 0
            shuffled = templates[:]
            random.shuffle(shuffled)
            for action_name, template_path in shuffled:
                if stop_event and stop_event.is_set():
                    return {"status": "stopped", "message": "已停止。"}
                match = detect_template_multi_scale(
                    roi, template_path, threshold=threshold, scales=template_scales
                )
                if not match:
                    continue
                local_x, local_y, score = match
                if ocr_enabled:
                    rx1 = max(0, local_x - 80)
                    ry1 = max(0, local_y - 34)
                    rx2 = min(roi.shape[1], local_x + 80)
                    ry2 = min(roi.shape[0], local_y + 38)
                    if rx2 > rx1 and ry2 > ry1:
                        text_crop = roi[ry1:ry2, rx1:rx2]
                        if not ocr_matches_action(text_crop, action_name):
                            if score < MAIN_TEMPLATE_OCR_BYPASS_SCORE:
                                continue
                screen_x = region["x"] + offset_x + local_x
                screen_y = region["y"] + offset_y + local_y
                if stop_event and stop_event.is_set():
                    return {"status": "stopped", "message": "已停止。"}
                pyautogui.click(screen_x, screen_y)
                record_main_action(action_name)
                clicked.append(f"{action_name}({score:.2f})")
                round_hit += 1
            if round_hit == 0:
                break

    if not clicked:
        return {"status": "done", "message": "功能已启用，但未检测到可点击按钮（或模板图未准备）。"}
    return {"status": "done", "message": f"已执行点击：{', '.join(clicked)}"}


def find_asset_png(*must_contain: str) -> Optional[Path]:
    for root in search_roots():
        for p in root.rglob("*.png"):
            if all(k in p.name for k in must_contain):
                return p
    return None


def find_asset_png_root(*must_contain: str) -> Optional[Path]:
    for root in search_roots():
        for p in root.glob("*.png"):
            if all(k in p.name for k in must_contain):
                return p
    return None


def find_visit_panel_visit_button_png() -> Optional[Path]:
    """
    拜访按钮模板。不可用 (拜访界面, 拜访, 按钮) 模糊匹配：
    「拜访」是「拜访界面」子串，会误命中 拜访界面-x按钮.png，导致用 × 图去点、直接关掉面板。
    """
    for p in assets_glob_flat_png():
        n = p.name
        if "拜访界面" in n and "拜访按钮" in n:
            return p
    return None


def find_visit_panel_close_button_png() -> Optional[Path]:
    """关闭拜访弹窗的 × / x 按钮模板，排除拜访按钮与判断图标。"""
    candidates: List[Path] = []
    for p in assets_glob_flat_png():
        n = p.name
        if "拜访界面" not in n:
            continue
        if "拜访按钮" in n or "判断" in n or "拜访区域" in n or "红框" in n:
            continue
        if "×" in n or "✕" in n:
            candidates.append(p)
        elif "x" in n.lower() and "按钮" in n:
            candidates.append(p)
    if not candidates:
        return None
    candidates.sort(key=lambda x: (0 if "×" in x.name or "✕" in x.name else 1, x.name))
    return candidates[0]


def find_visit_panel_judge_icon_png() -> Optional[Path]:
    for p in assets_glob_flat_png():
        n = p.name
        if "拜访界面" in n and "判断" in n and "图标" in n:
            return p
    return None


def _find_asset_png_by_exact_name(name: str) -> Optional[Path]:
    return resolve_asset_png_path(name)


def find_steal_scene_judge_roi_sample_png() -> Optional[Path]:
    # 红框样图：偷菜界面-判定为偷菜界面区域.png
    return _find_asset_png_by_exact_name("偷菜界面-判定为偷菜界面区域.png")


def find_visit_panel_scene_judge_roi_sample_png() -> Optional[Path]:
    # 红框样图：拜访界面-拜访界面判定.png
    return _find_asset_png_by_exact_name("拜访界面-拜访界面判定.png")


def find_steal_task_click_limit_roi_sample_png() -> Optional[Path]:
    # 红框样图：偷菜界面-任务执行限制区域.png
    return _find_asset_png_by_exact_name("偷菜界面-任务执行限制区域.png")


def _load_red_box_roi_from_sample(sample_png: Optional[Path]) -> Optional[Dict[str, float]]:
    if sample_png is None or not sample_png.is_file():
        return None
    img = read_image_compat(str(sample_png))
    if img is None or img.size == 0:
        return None
    return detect_red_box_roi_relative(img)


def load_steal_scene_judge_roi_relative() -> Optional[Dict[str, float]]:
    return _load_red_box_roi_from_sample(find_steal_scene_judge_roi_sample_png())


def load_visit_panel_scene_judge_roi_relative() -> Optional[Dict[str, float]]:
    return _load_red_box_roi_from_sample(find_visit_panel_scene_judge_roi_sample_png())


def load_steal_task_click_limit_roi_relative() -> Optional[Dict[str, float]]:
    return _load_red_box_roi_from_sample(find_steal_task_click_limit_roi_sample_png())


def _point_in_relative_roi(x_rel: float, y_rel: float, roi: Dict[str, float], margin: float = 0.0) -> bool:
    x1 = max(0.0, float(roi["x1"]) - float(margin))
    y1 = max(0.0, float(roi["y1"]) - float(margin))
    x2 = min(1.0, float(roi["x2"]) + float(margin))
    y2 = min(1.0, float(roi["y2"]) + float(margin))
    return x1 <= float(x_rel) <= x2 and y1 <= float(y_rel) <= y2


def steal_scene_present_by_home_button(
    frame_bgr: np.ndarray,
    home_btn_path: Path,
    threshold: float = 0.52,
) -> Tuple[bool, float]:
    roi_rel = load_steal_scene_judge_roi_relative()
    if roi_rel:
        roi, _ox, _oy = crop_by_relative_band(frame_bgr, expand_relative_roi(roi_rel, margin=0.06))
        if roi.size > 0:
            score = _best_steal_template_score(roi, home_btn_path, scales=STEAL_UI_TEMPLATE_SCALES_FAST)
            return score >= float(threshold), score
    score_full = _best_steal_template_score(frame_bgr, home_btn_path, scales=STEAL_UI_TEMPLATE_SCALES_FAST)
    return score_full >= float(threshold), score_full


def visit_panel_present_by_visit_button(
    frame_bgr: np.ndarray,
    visit_btn_path: Path,
    threshold: float = 0.5,
) -> Tuple[bool, float]:
    roi_rel = load_visit_panel_scene_judge_roi_relative()
    if roi_rel:
        roi, _ox, _oy = crop_by_relative_band(frame_bgr, expand_relative_roi(roi_rel, margin=0.06))
        if roi.size > 0:
            score = _best_steal_template_score(roi, visit_btn_path, scales=STEAL_UI_TEMPLATE_SCALES_FAST)
            return score >= float(threshold), score
    score_full = _best_steal_template_score(frame_bgr, visit_btn_path, scales=STEAL_UI_TEMPLATE_SCALES_FAST)
    return score_full >= float(threshold), score_full


def classify_scene_three_way(
    frame_bgr: np.ndarray,
    visit_btn_path: Optional[Path],
    home_btn_path: Optional[Path],
) -> str:
    if is_main_interface_scene(frame_bgr, threshold=MAIN_INTERFACE_SCENE_THRESHOLD):
        return "main"
    is_steal, steal_sc = (False, 0.0)
    is_visit, visit_sc = (False, 0.0)
    if home_btn_path is not None:
        is_steal, steal_sc = steal_scene_present_by_home_button(frame_bgr, home_btn_path, threshold=0.52)
    if visit_btn_path is not None:
        is_visit, visit_sc = visit_panel_present_by_visit_button(frame_bgr, visit_btn_path, threshold=0.5)
    # 两者都过阈值时：分数高者优先；同分优先 steal（避免农场界面被拜访按钮假阳性抢走）。
    # 仅 visit 先判时，农场里易把其它按钮误当「拜访」→ 误判 visit → 点 ×；故 steal 至少要不弱于 visit 才判农场。
    if is_steal and is_visit:
        return "steal" if float(steal_sc) >= float(visit_sc) else "visit"
    if is_steal:
        return "steal"
    if is_visit:
        return "visit"
    return "unknown"


def recover_unknown_scene_with_close(
    region: Dict[str, int],
    close_btn_path: Optional[Path],
    visit_btn_path: Optional[Path],
    home_btn_path: Optional[Path],
    stop_event: Optional[threading.Event] = None,
    settle_sec: float = 1.0,
    after_close_sec: float = 0.2,
    max_rounds: int = 20,
) -> str:
    if interruptible_sleep(stop_event, max(0.0, float(settle_sec))):
        return "unknown"
    rounds = max(1, int(max_rounds))
    for _ in range(rounds):
        if stop_event and stop_event.is_set():
            return "unknown"
        frame = capture_game_region()
        scene = classify_scene_three_way(frame, visit_btn_path=visit_btn_path, home_btn_path=home_btn_path)
        if scene != "unknown":
            return scene
        if close_btn_path is not None:
            click_template_on_game_frame_retry(
                region,
                close_btn_path,
                threshold=0.48,
                attempts=1,
                gap_sec=0.02,
            )
        if interruptible_sleep(stop_event, max(0.0, float(after_close_sec))):
            return "unknown"
    return "unknown"


def find_all_template_matches(
    frame_bgr: np.ndarray,
    template_path: Path,
    threshold: float = 0.52,
    min_distance: int = 32,
    max_matches: int = 40,
) -> List[Tuple[int, int, float]]:
    tpl = read_image_compat(str(template_path))
    if tpl is None:
        return []
    gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
    tgray = cv2.cvtColor(tpl, cv2.COLOR_BGR2GRAY)
    th, tw = tgray.shape[:2]
    if th >= gray.shape[0] or tw >= gray.shape[1]:
        return []
    res = cv2.matchTemplate(gray, tgray, cv2.TM_CCOEFF_NORMED)
    work = res.copy()
    md = max(20, min(min_distance, tw // 2, th // 2))
    matches: List[Tuple[int, int, float]] = []
    for _ in range(max_matches):
        _, max_val, _, max_loc = cv2.minMaxLoc(work)
        if float(max_val) < threshold:
            break
        cx = int(max_loc[0] + tw // 2)
        cy = int(max_loc[1] + th // 2)
        matches.append((cx, cy, float(max_val)))
        xa = max(0, max_loc[0] - md)
        ya = max(0, max_loc[1] - md)
        xb = min(work.shape[1], max_loc[0] + tw + md)
        yb = min(work.shape[0], max_loc[1] + th + md)
        work[ya:yb, xa:xb] = 0.0
    matches.sort(key=lambda m: (m[1], m[0]))
    return matches


def find_all_visit_button_matches(
    frame_bgr: np.ndarray,
    template_path: Path,
    threshold: float = 0.52,
    min_distance: int = 32,
    max_matches: int = 22,
) -> List[Tuple[int, int, float]]:
    return find_all_template_matches(
        frame_bgr, template_path, threshold, min_distance, max_matches=max_matches
    )


def find_all_judge_icon_matches(
    frame_bgr: np.ndarray,
    template_path: Path,
    threshold: float = 0.52,
    min_distance: int = 24,
    max_matches: int = 22,
) -> List[Tuple[int, int, float]]:
    return find_all_template_matches(
        frame_bgr, template_path, threshold, min_distance, max_matches=max_matches
    )


def get_sample_confirm_dir() -> Optional[Path]:
    for d in assets_iter_subdirs():
        if "主界面按钮区域确认样图" in d.name:
            return d
    return None


# 仅用于从红框推算「一键按钮」监视区域（相对游戏窗口）；不参与实况模板匹配
MAIN_UI_BUTTON_DETECTION_ZONE_SAMPLE_NAME = "主界面-按钮检测区域.png"


def main_ui_button_detection_zone_sample_path() -> Optional[Path]:
    d = get_sample_confirm_dir()
    if not d:
        return None
    p = d / MAIN_UI_BUTTON_DETECTION_ZONE_SAMPLE_NAME
    return p if p.is_file() else None


def _pad_relative_band_for_game_window(
    r: Dict[str, float], gw: int, gh: int
) -> Dict[str, float]:
    pad_x = min(0.12, 5.0 / float(max(1, gw)))
    pad_y = min(0.15, 5.0 / float(max(1, gh)))
    return {
        "x1": max(0.0, float(r["x1"]) - pad_x),
        "y1": max(0.0, float(r["y1"]) - pad_y),
        "x2": min(1.0, float(r["x2"]) + pad_x),
        "y2": min(1.0, float(r["y2"]) + pad_y),
    }


def locate_action_bar_band_from_detection_zone_sample() -> Optional[Dict[str, float]]:
    """
    从 assets/yinyong/主界面按钮区域确认样图/主界面-按钮检测区域.png 中识别红色矩形，得到相对条带。
    主界面巡查与好友农场一键均优先用此区域做检测裁剪；该图不做模板精准匹配。
    """
    path = main_ui_button_detection_zone_sample_path()
    if path is None:
        return None
    img = read_image_compat(str(path))
    if img is None or img.size == 0:
        return None
    ih, iw = img.shape[:2]
    boxes = detect_red_boxes_multi_relative_sorted(
        img, max_boxes=12, min_area_px=200
    )
    boxes = [b for b in boxes if _relative_rect_area(b) < 0.86]
    r: Optional[Dict[str, float]] = None
    if boxes:
        boxes = [b for b in boxes if _relative_rect_area(b) >= 0.002]
    if boxes:
        # 先选“像一键条”的宽条框：横向占比较大、且位于画面下半部。
        wide = []
        for b in boxes:
            wrel = float(b["x2"]) - float(b["x1"])
            hrel = float(b["y2"]) - float(b["y1"])
            if wrel >= 0.22 and 0.03 <= hrel <= 0.28 and float(b["y1"]) >= 0.45:
                wide.append(b)
        if wide:
            r = max(wide, key=lambda b: (_relative_rect_area(b), b["y1"]))
        else:
            r = dict(DEFAULT_MAIN_ACTION_BAR_ROI_REL)
    if r is None:
        r = detect_red_box_roi_relative(img)
    if r is None:
        r = dict(DEFAULT_MAIN_ACTION_BAR_ROI_REL)
    if r is None:
        return None
    reg = load_config_region()
    gw = max(1, int(reg["w"])) if reg else max(1, iw)
    gh = max(1, int(reg["h"])) if reg else max(1, ih)
    return _pad_relative_band_for_game_window(r, gw, gh)


def _is_template_calibration_sample_png(path: Path) -> bool:
    """排除「仅用于红框推区域」的样图，避免参与主界面模板校准循环。"""
    n = path.name
    if n == MAIN_UI_BUTTON_DETECTION_ZONE_SAMPLE_NAME:
        return False
    if "按钮检测区域" in n:
        return False
    return True


def _relative_rect_area(r: Dict[str, float]) -> float:
    return max(0.0, float(r["x2"]) - float(r["x1"])) * max(0.0, float(r["y2"]) - float(r["y1"]))


def detect_red_boxes_multi_relative_sorted(
    sample_bgr: np.ndarray,
    max_boxes: int = 12,
    min_area_px: int = 350,
) -> List[Dict[str, float]]:
    """
    从样图中识别多个红色矩形框，按从上到下、从左到右排序；用于一区～四区样图。
    会过滤掉面积过大的外框（整图描边）。
    """
    hsv = cv2.cvtColor(sample_bgr, cv2.COLOR_BGR2HSV)
    mask1 = cv2.inRange(hsv, (0, 60, 40), (15, 255, 255))
    mask2 = cv2.inRange(hsv, (165, 60, 40), (180, 255, 255))
    mask = cv2.bitwise_or(mask1, mask2)
    mask = cv2.dilate(mask, np.ones((5, 5), np.uint8), iterations=2)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    H, W = sample_bgr.shape[:2]
    raw: List[Tuple[int, int, int, int, float]] = []
    for c in contours:
        area = cv2.contourArea(c)
        if area < min_area_px:
            continue
        x, y, w, h = cv2.boundingRect(c)
        if w < 10 or h < 10:
            continue
        raw.append((x, y, w, h, float(area)))
    raw.sort(key=lambda t: (t[1], t[0]))
    out: List[Dict[str, float]] = []
    for x, y, w, h, _ in raw[: max_boxes * 2]:
        rel = {
            "x1": max(0.0, x / W),
            "y1": max(0.0, y / H),
            "x2": min(1.0, (x + w) / W),
            "y2": min(1.0, (y + h) / H),
        }
        if _relative_rect_area(rel) >= 0.88:
            continue
        out.append(rel)
    out.sort(key=lambda r: (r["y1"], r["x1"]))
    return out[:max_boxes]


def detect_red_box_roi_relative(sample_bgr: np.ndarray) -> Optional[Dict[str, float]]:
    """
    从「拜访界面-拜访区域-红框区域为检查区域」类样图里，用红色轮廓取出矩形范围，得到相对坐标。
    该图不参与与游戏画面的模板匹配；实况中是否可拜访只匹配「拜访界面-判断图标」模板。
    """
    hsv = cv2.cvtColor(sample_bgr, cv2.COLOR_BGR2HSV)
    mask1 = cv2.inRange(hsv, (0, 60, 40), (15, 255, 255))
    mask2 = cv2.inRange(hsv, (165, 60, 40), (180, 255, 255))
    mask = cv2.bitwise_or(mask1, mask2)
    mask = cv2.dilate(mask, np.ones((3, 3), np.uint8), iterations=2)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    best = None
    best_area = 0
    H, W = sample_bgr.shape[:2]
    for c in contours:
        area = cv2.contourArea(c)
        if area < 200:
            continue
        x, y, w, h = cv2.boundingRect(c)
        if w < 15 or h < 15:
            continue
        if w * h > best_area:
            best_area = w * h
            best = (x, y, w, h)
    if not best:
        return None
    x, y, w, h = best
    return {
        "x1": max(0.0, x / W),
        "y1": max(0.0, y / H),
        "x2": min(1.0, (x + w) / W),
        "y2": min(1.0, (y + h) / H),
    }


def find_visit_red_sample_path() -> Optional[Path]:
    """样图：拜访界面-拜访区域-红框区域为检查区域.png（仅用于从红框推 ROI，不做实况匹配）。"""
    sample_dir = get_sample_confirm_dir()
    if not sample_dir:
        return None
    for p in sample_dir.glob("*.png"):
        if "拜访" in p.name and "拜访区域" in p.name and "红框" in p.name:
            return p
    return None


def ensure_visit_check_roi_cached() -> Optional[Dict[str, float]]:
    """
    若存在红框样图，每次调用都会从该图重新推算检查区并写入 config（你替换 PNG 后无需手改 JSON）。
    若样图缺失或红框识别失败，则沿用 config 里已保存的 visit_check_roi_relative。
    """
    red_sample = find_visit_red_sample_path()
    if red_sample and red_sample.exists():
        img = read_image_compat(str(red_sample))
        if img is not None:
            roi = detect_red_box_roi_relative(img)
            if roi:
                save_visit_check_roi_relative(roi)
                return roi
    return load_visit_check_roi_relative()


def find_visit_panel_whole_sample_png() -> Optional[Path]:
    d = get_sample_confirm_dir()
    if not d:
        return None
    for p in d.glob("*.png"):
        if "拜访界面" in p.name and "整个界面" in p.name:
            return p
    return None


def find_visit_zones_inspect_sample_png() -> Optional[Path]:
    d = get_sample_confirm_dir()
    if not d:
        return None
    for p in d.glob("*.png"):
        n = p.name
        if "拜访界面" in n and "一区" in n and "四区" in n and "检查区域" in n:
            return p
    return None


def find_visit_zones_name_sample_png() -> Optional[Path]:
    d = get_sample_confirm_dir()
    if not d:
        return None
    for p in d.glob("*.png"):
        if "拜访界面" in p.name and "好友名字区域" in p.name:
            return p
    return None


def save_visit_zones_layout_to_config(
    panel_roi: Optional[Dict[str, float]],
    zones_inspect: List[Dict[str, float]],
    zones_name: List[Dict[str, float]],
    ref_w: int,
    ref_h: int,
) -> None:
    data = load_config_all()
    data.setdefault(FEATURES_KEY, {})
    data[FEATURES_KEY].setdefault(STEAL_FEATURE_KEY, {})
    prev = dict(data[FEATURES_KEY][STEAL_FEATURE_KEY])
    if panel_roi:
        prev["visit_panel_roi_relative"] = panel_roi
    prev["visit_zones_inspect_relative"] = zones_inspect
    prev["visit_zones_name_relative"] = zones_name
    prev["visit_layout_ref_size"] = {"w": int(ref_w), "h": int(ref_h)}
    data[FEATURES_KEY][STEAL_FEATURE_KEY] = prev
    save_config_all(data)


def load_visit_panel_roi_relative() -> Optional[Dict[str, float]]:
    data = load_config_all()
    roi = data.get(FEATURES_KEY, {}).get(STEAL_FEATURE_KEY, {}).get("visit_panel_roi_relative")
    if not roi or not isinstance(roi, dict):
        return None
    needed = ("x1", "y1", "x2", "y2")
    if not all(k in roi for k in needed):
        return None
    return {k: float(roi[k]) for k in needed}


def load_visit_zones_inspect_relative() -> Optional[List[Dict[str, float]]]:
    data = load_config_all()
    raw = data.get(FEATURES_KEY, {}).get(STEAL_FEATURE_KEY, {}).get("visit_zones_inspect_relative")
    if not raw or not isinstance(raw, list) or len(raw) < 2:
        return None
    out: List[Dict[str, float]] = []
    for item in raw:
        if not isinstance(item, dict):
            return None
        if not all(k in item for k in ("x1", "y1", "x2", "y2")):
            return None
        out.append({k: float(item[k]) for k in ("x1", "y1", "x2", "y2")})
    return out


def load_visit_zones_name_relative() -> Optional[List[Dict[str, float]]]:
    data = load_config_all()
    raw = data.get(FEATURES_KEY, {}).get(STEAL_FEATURE_KEY, {}).get("visit_zones_name_relative")
    if not raw or not isinstance(raw, list) or len(raw) < 2:
        return None
    out: List[Dict[str, float]] = []
    for item in raw:
        if not isinstance(item, dict):
            return None
        if not all(k in item for k in ("x1", "y1", "x2", "y2")):
            return None
        out.append({k: float(item[k]) for k in ("x1", "y1", "x2", "y2")})
    return out


def ensure_visit_zones_from_user_samples() -> None:
    """
    从确认样图目录读取：
    - 拜访界面-整个界面.png → 拜访弹窗整体红框 → visit_panel_roi_relative
    - 拜访界面-一区至四区-红框区域为检查区域*.png → 四区检查红框（从上到下）
    - 拜访界面-一区至四区-红框区域为好友名字区域*.png → 四区名字红框
    三张图会缩放到与「整个界面」同尺寸后再取框；要求样图与游戏截图分辨率一致。
    """
    p_whole = find_visit_panel_whole_sample_png()
    p_z = find_visit_zones_inspect_sample_png()
    p_n = find_visit_zones_name_sample_png()
    if not p_whole or not p_z or not p_n:
        return
    whole = read_image_compat(str(p_whole))
    z_img = read_image_compat(str(p_z))
    n_img = read_image_compat(str(p_n))
    if whole is None or z_img is None or n_img is None:
        return
    H, W = whole.shape[:2]
    if H < 16 or W < 16:
        return
    if z_img.shape[:2] != (H, W):
        z_img = cv2.resize(z_img, (W, H), interpolation=cv2.INTER_LINEAR)
    if n_img.shape[:2] != (H, W):
        n_img = cv2.resize(n_img, (W, H), interpolation=cv2.INTER_LINEAR)
    panel_roi = detect_red_box_roi_relative(whole)
    boxes_z = detect_red_boxes_multi_relative_sorted(z_img, max_boxes=16, min_area_px=300)
    boxes_z.sort(key=lambda r: (r["y1"], r["x1"]))
    boxes_z = boxes_z[:4]
    boxes_n = detect_red_boxes_multi_relative_sorted(n_img, max_boxes=16, min_area_px=300)
    boxes_n.sort(key=lambda r: (r["y1"], r["x1"]))
    boxes_n = boxes_n[:4]
    if len(boxes_z) < 4 or len(boxes_n) < 4:
        return
    save_visit_zones_layout_to_config(panel_roi, boxes_z, boxes_n, W, H)


def count_judge_icons_per_zone(
    frame_bgr: np.ndarray,
    panel_roi_rel: Dict[str, float],
    zones_inspect: List[Dict[str, float]],
    judge_path: Path,
    threshold: float = VISIT_JUDGE_ICON_THRESHOLD,
) -> List[int]:
    panel, _px, _py = crop_by_relative_band(frame_bgr, panel_roi_rel)
    if panel.size == 0:
        return [0] * max(4, len(zones_inspect))
    counts: List[int] = []
    for zrel in zones_inspect[:4]:
        zimg, _, _ = crop_by_relative_band(panel, zrel)
        if zimg.size == 0:
            counts.append(0)
            continue
        judges = find_all_judge_icon_matches(zimg, judge_path, threshold=threshold, min_distance=16)
        counts.append(len(judges))
    return counts


def get_steal_action_templates() -> List[Tuple[str, Path]]:
    found: List[Tuple[str, Path]] = []
    for action_name, filename in STEAL_ACTION_TEMPLATE_FIXED_MAPPING:
        p = resolve_asset_png_path(filename)
        if p is not None:
            found.append((action_name, p))
    return found


def click_template_on_game_frame(
    frame_bgr: np.ndarray,
    region: Dict[str, int],
    template_path: Path,
    threshold: float = 0.65,
) -> bool:
    match = detect_template_multi_scale(frame_bgr, template_path, threshold=threshold)
    if not match:
        return False
    lx, ly, _score = match
    pyautogui.click(region["x"] + lx, region["y"] + ly)
    return True


def click_template_on_game_frame_retry(
    region: Dict[str, int],
    template_path: Path,
    threshold: float = 0.55,
    attempts: int = 4,
    gap_sec: float = 0.0,
) -> bool:
    """截最新游戏画面多次尝试点击（弹窗动画后模板更易匹配）。"""
    for _ in range(attempts):
        frame = capture_game_region()
        if click_template_on_game_frame(frame, region, template_path, threshold=threshold):
            return True
        time.sleep(gap_sec)
    return False


def click_friend_button_with_retry(
    region: Dict[str, int],
    friend_btn_path: Path,
    stop_event: Optional[threading.Event] = None,
) -> bool:
    """
    好友按钮更容易受主界面动效影响，采用分级阈值 + 多次截帧重试，
    避免「主界面无任务时本应去拜访，但首帧未匹配导致整轮跳过」。
    """
    last_frame: Optional[np.ndarray] = None
    last_th = 0.0
    for th, attempts, gap in (
        (0.66, 3, 0.05),
        (0.63, 4, 0.06),
        (0.60, 4, 0.07),
    ):
        for _ in range(attempts):
            if stop_event and stop_event.is_set():
                return False
            frame = capture_game_region()
            last_frame = frame
            last_th = float(th)
            # 先走全屏严格匹配，避免误点。
            m_full = detect_template_multi_scale(
                frame, friend_btn_path, threshold=th, scales=PATROL_TEMPLATE_SCALES
            )
            if m_full:
                lx, ly, score = m_full
                pyautogui.click(region["x"] + lx, region["y"] + ly)
                dbg = _save_friend_click_debug_image(
                    frame,
                    stage="hit",
                    source="full",
                    threshold=th,
                    template_name=friend_btn_path.name,
                    click_xy=(lx, ly),
                    score=score,
                )
                _diag(
                    "patrol",
                    "friend_click_match",
                    "好友按钮匹配成功（全图）",
                    source="full",
                    threshold=th,
                    score=round(float(score), 4),
                    click_xy=(int(lx), int(ly)),
                    debug_image=dbg,
                )
                return True
            # 再在主界面按钮条区域做一次稍低阈值兜底，兼顾弱对比/轻微缩放。
            band = locate_button_band_relative_cached()
            roi, ox, oy = crop_by_relative_band(frame, band)
            if roi.size > 0:
                roi_th = max(0.57, th - 0.04)
                m = detect_template_multi_scale(
                    roi, friend_btn_path, threshold=roi_th, scales=PATROL_TEMPLATE_SCALES
                )
                if m:
                    lx, ly, score = m
                    pyautogui.click(region["x"] + ox + lx, region["y"] + oy + ly)
                    dbg = _save_friend_click_debug_image(
                        frame,
                        stage="hit",
                        source="band",
                        threshold=roi_th,
                        template_name=friend_btn_path.name,
                        click_xy=(ox + lx, oy + ly),
                        score=score,
                        roi_rect=_band_to_pixel_rect(band, frame.shape),
                    )
                    _diag(
                        "patrol",
                        "friend_click_match",
                        "好友按钮匹配成功（按钮条区域）",
                        source="band",
                        threshold=roi_th,
                        score=round(float(score), 4),
                        click_xy=(int(ox + lx), int(oy + ly)),
                        debug_image=dbg,
                    )
                    return True
            if interruptible_sleep(stop_event, gap):
                return False
    if last_frame is not None:
        band = locate_button_band_relative_cached()
        dbg = _save_friend_click_debug_image(
            last_frame,
            stage="miss",
            source="none",
            threshold=last_th,
            template_name=friend_btn_path.name,
            roi_rect=_band_to_pixel_rect(band, last_frame.shape),
        )
        _diag(
            "patrol",
            "friend_click_miss_debug",
            "好友按钮未命中，已保存调试图",
            threshold=last_th,
            debug_image=dbg,
        )
    return False


def expand_relative_roi(roi: Optional[Dict[str, float]], margin: float = VISIT_CHECK_ROI_EXPAND) -> Optional[Dict[str, float]]:
    """红框只做大致范围时，向外扩一圈，减少「框偏一点就完全认不到」。"""
    if not roi:
        return None
    return {
        "x1": max(0.0, float(roi["x1"]) - margin),
        "y1": max(0.0, float(roi["y1"]) - margin),
        "x2": min(1.0, float(roi["x2"]) + margin),
        "y2": min(1.0, float(roi["y2"]) + margin),
    }


def visit_judge_icon_present(frame_bgr: np.ndarray, roi_rel: Optional[Dict[str, float]], judge_path: Path, threshold: float = VISIT_JUDGE_ICON_THRESHOLD) -> bool:
    """
    roi_rel 来自红框样图推出来的「检查区」，只缩小搜索范围，不与实况做模板匹配。
    是否可拜访仅由「拜访界面-判断图标」在实况截图上匹配决定。
    会先对检查区做 expand；若裁剪比模板还小，则仅在判断图标这一步用整幅游戏区搜一次。
    """
    roi_rel_use = expand_relative_roi(roi_rel) if roi_rel else None
    roi, _ox, _oy = crop_by_relative_band(frame_bgr, roi_rel_use)
    if roi.size == 0:
        return False

    tpl = read_image_compat(str(judge_path))
    if tpl is not None and (roi.shape[0] < tpl.shape[0] or roi.shape[1] < tpl.shape[1]):
        roi = frame_bgr

    m = detect_template_multi_scale(roi, judge_path, threshold=threshold)
    return m is not None


def visit_panel_present_strict(
    frame_bgr: np.ndarray,
    roi_rel: Optional[Dict[str, float]],
    judge_path: Path,
    close_btn_path: Optional[Path] = None,
) -> bool:
    """
    更严格判断「当前是否是拜访窗口」：
    - 优先：在「拜访界面-拜访界面判定.png」红框区域里匹配「拜访按钮」
    - 先在检查区识别多个判断图标（避免单点误检）
    - 若提供关闭按钮模板，还要求能匹配到关闭按钮
    """
    visit_btn = find_visit_panel_visit_button_png()
    if visit_btn is not None:
        present_by_btn, _score = visit_panel_present_by_visit_button(frame_bgr, visit_btn, threshold=0.5)
        if present_by_btn:
            return True
    roi_rel_use = expand_relative_roi(roi_rel) if roi_rel else None
    roi, _ox, _oy = crop_by_relative_band(frame_bgr, roi_rel_use)
    if roi.size == 0:
        return False
    judges = find_all_judge_icon_matches(
        roi, judge_path, threshold=max(0.56, VISIT_JUDGE_ICON_THRESHOLD + 0.02), min_distance=18, max_matches=12
    )
    if len(judges) < 2:
        return False
    if close_btn_path is None:
        return True
    return detect_template_multi_scale(frame_bgr, close_btn_path, threshold=0.5) is not None


def wait_for_visit_judge_icon(
    roi_rel: Optional[Dict[str, float]],
    judge_path: Path,
    stop_event: threading.Event,
    max_wait_sec: float = 8.0,
    poll_sec: float = 0.35,
    threshold: float = VISIT_JUDGE_ICON_THRESHOLD,
) -> Tuple[np.ndarray, bool]:
    """
    点好友后轮询判断图标；max_wait_sec 为 0 时仍至少截一帧再判定。
    末次在整幅游戏区用略低阈值补搜（红框仅作范围参考）。
    """
    deadline = time.time() + max(0.0, float(max_wait_sec))
    poll_use = max(float(VISIT_POLL_MIN_SEC), float(poll_sec))
    last_frame: Optional[np.ndarray] = None
    while not stop_event.is_set():
        last_frame = capture_game_region()
        if visit_judge_icon_present(last_frame, roi_rel, judge_path, threshold=threshold):
            return last_frame, True
        if time.time() >= deadline:
            break
        if interruptible_sleep(stop_event, poll_use):
            if last_frame is None:
                last_frame = capture_game_region()
            return last_frame, False
    if last_frame is None:
        last_frame = capture_game_region()
    # 检查区内始终未命中：整幅游戏窗口再用略低阈值补搜一次判断图标（红框只作范围参考，避免 ROI 偏差漏检）
    if visit_judge_icon_present(last_frame, None, judge_path, threshold=0.48):
        return last_frame, True
    return last_frame, False


def _visit_zone_inspect_rel_for_index(
    zones_inspect: List[Dict[str, float]], zone_idx: int
) -> Dict[str, float]:
    z = zones_inspect[zone_idx]
    if zone_idx != 0 or VISIT_ZONE0_INSPECT_EXPAND_TOP_REL <= 0:
        return {k: float(z[k]) for k in ("x1", "y1", "x2", "y2")}
    return {
        "x1": float(z["x1"]),
        "y1": max(0.0, float(z["y1"]) - float(VISIT_ZONE0_INSPECT_EXPAND_TOP_REL)),
        "x2": float(z["x2"]),
        "y2": float(z["y2"]),
    }


def _pick_next_visit_using_panel_zones(
    frame_bgr: np.ndarray,
    panel_roi_rel: Dict[str, float],
    zones_inspect: List[Dict[str, float]],
    zones_name: List[Dict[str, float]],
    judge_path: Path,
    visit_btn_path: Path,
    stop_event: Optional[threading.Event],
    row_y_tolerance: int,
) -> Optional[Tuple[int, int, str, np.ndarray]]:
    panel, px, py = crop_by_relative_band(frame_bgr, panel_roi_rel)
    if panel.size == 0:
        return None
    ph, pw = panel.shape[:2]
    visits_all = find_all_visit_button_matches(panel, visit_btn_path, threshold=0.5)
    j_thresh = VISIT_JUDGE_ICON_THRESHOLD
    # 先收集所有「判断图标+拜访」配对，再按行 Y 从上到下排序，避免按分区顺序误优先点到下面某行（如第 4 行）
    picked: List[Tuple[int, int, int, str, np.ndarray]] = []
    used_visit_keys: set = set()
    for zone_idx in range(min(4, len(zones_inspect), len(zones_name))):
        if stop_event and stop_event.is_set():
            return None
        zrel = _visit_zone_inspect_rel_for_index(zones_inspect, zone_idx)
        zone_img, zx, zy = crop_by_relative_band(panel, zrel)
        if zone_img.size == 0:
            continue
        judges = find_all_judge_icon_matches(zone_img, judge_path, threshold=j_thresh, min_distance=20)
        judges.sort(key=lambda m: (m[1], m[0]))
        nrel = zones_name[zone_idx]
        nj1 = int(nrel["y1"] * ph)
        nj2 = int(nrel["y2"] * ph)
        ni1 = int(nrel["x1"] * pw)
        ni2 = int(nrel["x2"] * pw)
        for jx, jy_loc, _ in judges:
            jy_panel = zy + jy_loc
            best: Optional[Tuple[int, int]] = None
            best_d = row_y_tolerance + 1
            for vx, vy, _s in visits_all:
                d = abs(vy - jy_panel)
                if d < best_d:
                    best_d = d
                    best = (vx, vy)
            if best is None or best_d > row_y_tolerance:
                continue
            vx, vy = best
            vkey = (vx // 6, vy // 6)
            if vkey in used_visit_keys:
                continue
            row_anchor_y = int(round((float(jy_panel) + float(vy)) / 2.0))
            row_half = VISIT_NAME_ROW_HALF_HEIGHT
            ry1 = max(nj1, row_anchor_y - row_half)
            ry2 = min(nj2, row_anchor_y + row_half)
            # 名字红框与行锚无交集时（样图一区名字框略低），退回按行锚在整窗高度裁条带，避免首行整行被跳过
            if ry2 <= ry1:
                ry1 = max(0, row_anchor_y - row_half)
                ry2 = min(ph, row_anchor_y + row_half)
            if ry2 <= ry1 or ni2 <= ni1:
                continue
            name_img = panel[ry1:ry2, ni1:ni2]
            if name_img.size == 0:
                continue
            name = f"__anon_z{zone_idx}_{row_anchor_y}"
            used_visit_keys.add(vkey)
            picked.append((vy, px + vx, py + vy, name, name_img.copy()))
    if not picked:
        return None
    picked.sort(key=lambda t: t[0])
    _vy, fx, fy, name, strip = picked[0]
    return (fx, fy, name, strip)


def pick_next_visit_candidate_zoned(
    frame_bgr: np.ndarray,
    roi_rel: Optional[Dict[str, float]],
    judge_path: Path,
    visit_btn_path: Path,
    stop_event: Optional[threading.Event],
    num_zones: int = VISIT_LIST_ZONE_COUNT,
    row_y_tolerance: int = VISIT_ROW_Y_TOLERANCE_PX,
    zone_boundaries_relative: Optional[List[float]] = None,
) -> Optional[Tuple[int, int, str, np.ndarray]]:
    """
    若 config 中已有 visit_panel_roi_relative + 四区检查/名字红框（由样图自动生成），
    则在拜访弹窗内按一区→四区扫描；否则使用 visit_check_roi 扩展带 + 纵向等分。
    """
    zones_inspect = load_visit_zones_inspect_relative()
    zones_name = load_visit_zones_name_relative()
    panel_roi = load_visit_panel_roi_relative()
    if (
        panel_roi
        and zones_inspect
        and len(zones_inspect) >= 4
        and zones_name
        and len(zones_name) >= 4
    ):
        hit = _pick_next_visit_using_panel_zones(
            frame_bgr,
            panel_roi,
            zones_inspect,
            zones_name,
            judge_path,
            visit_btn_path,
            stop_event,
            row_y_tolerance,
        )
        if hit is not None:
            return hit
        return None
    list_band = expand_relative_roi(roi_rel) if roi_rel else None
    if not list_band:
        list_band = {"x1": 0.0, "y1": 0.0, "x2": 1.0, "y2": 1.0}
    list_roi, ox, oy = crop_by_relative_band(frame_bgr, list_band)
    if list_roi.size == 0:
        return None
    lh, _lw = list_roi.shape[:2]
    zone_ranges = visit_list_zone_pixel_ranges(lh, zone_boundaries_relative, num_zones)
    visits_all = find_all_visit_button_matches(list_roi, visit_btn_path, threshold=0.5)
    j_thresh = VISIT_JUDGE_ICON_THRESHOLD
    picked_list: List[Tuple[int, int, int, str, np.ndarray]] = []
    used_visit_keys_l: set = set()
    for zone_idx, (y0, y1) in enumerate(zone_ranges):
        if stop_event and stop_event.is_set():
            return None
        if zone_idx == 0 and VISIT_ZONE0_INSPECT_EXPAND_TOP_REL > 0:
            y0 = max(
                0,
                y0 - int(round(lh * float(VISIT_ZONE0_INSPECT_EXPAND_TOP_REL))),
            )
        zone_img = list_roi[y0:y1, :]
        if zone_img.size == 0:
            continue
        judges = find_all_judge_icon_matches(zone_img, judge_path, threshold=j_thresh, min_distance=20)
        judges.sort(key=lambda m: (m[1], m[0]))
        for jx, jy_loc, _ in judges:
            jy = y0 + jy_loc
            best: Optional[Tuple[int, int]] = None
            best_d = row_y_tolerance + 1
            for vx, vy, _s in visits_all:
                d = abs(vy - jy)
                if d < best_d:
                    best_d = d
                    best = (vx, vy)
            if best is None or best_d > row_y_tolerance:
                continue
            vx, vy = best
            vkey = (vx // 6, vy // 6)
            if vkey in used_visit_keys_l:
                continue
            row_anchor_y = int(round((float(jy) + float(vy)) / 2.0))
            row_half = VISIT_NAME_ROW_HALF_HEIGHT
            y1n = max(0, row_anchor_y - row_half)
            y2n = min(lh, row_anchor_y + row_half)
            x_right = min(jx, vx)
            x2n = max(0, x_right - 4)
            if x2n < 16:
                continue
            name_img = list_roi[y1n:y2n, 0:x2n]
            name = f"__anon_z{zone_idx}_{row_anchor_y}"
            used_visit_keys_l.add(vkey)
            picked_list.append((vy, ox + vx, oy + vy, name, name_img.copy()))
    if not picked_list:
        return None
    picked_list.sort(key=lambda t: t[0])
    _vy, fx, fy, name, strip = picked_list[0]
    return (fx, fy, name, strip)


def click_visit_at_frame_xy(
    region: Dict[str, int],
    fx: int,
    fy: int,
    stop_event: Optional[threading.Event] = None,
) -> bool:
    if stop_event and stop_event.is_set():
        return False
    pyautogui.click(region["x"] + int(fx), region["y"] + int(fy))
    return True


def wait_after_visit_click(
    roi_rel: Optional[Dict[str, float]],
    judge_path: Path,
    home_btn: Path,
    close_btn: Optional[Path],
    stop_event: threading.Event,
    max_wait_sec: float = 6.0,
    poll_sec: float = 0.35,
) -> str:
    """
    点击拜访后：出现偷菜「回家」→ farm；用户停止 → stopped；
    超时后仍像拜访列表 → still_panel；否则 unknown。
    """
    deadline = time.time() + max(0.0, float(max_wait_sec))
    poll_use = max(float(VISIT_POLL_MIN_SEC), float(poll_sec))
    while not stop_event.is_set():
        frame = capture_game_region()
        in_steal_scene, _home_score = steal_scene_present_by_home_button(frame, home_btn, threshold=0.52)
        if in_steal_scene:
            return "farm"
        if time.time() >= deadline:
            break
        if interruptible_sleep(stop_event, poll_use):
            return "stopped"
    frame = capture_game_region()
    in_steal_scene, _home_score = steal_scene_present_by_home_button(frame, home_btn, threshold=0.52)
    if in_steal_scene:
        return "farm"
    if visit_panel_present_strict(frame, roi_rel, judge_path, close_btn_path=close_btn):
        return "still_panel"
    return "unknown"


def action_pending_in_frame(
    frame_bgr: np.ndarray,
    templates: List[Tuple[str, Path]],
    actions_enabled: Dict[str, bool],
    band: Optional[Dict[str, float]],
    threshold: float = 0.62,
    require_ocr: bool = True,
    use_steal_ui_match: bool = False,
    template_scales: Optional[List[float]] = None,
    steal_scales: Optional[List[float]] = None,
) -> bool:
    roi, _ox, _oy = crop_by_relative_band(frame_bgr, band)
    for action_name, template_path in templates:
        if not actions_enabled.get(action_name, False):
            continue
        if use_steal_ui_match:
            m = detect_template_multi_scale_steal_ui(
                roi, template_path, base_threshold=threshold, scales=steal_scales
            )
        else:
            m = detect_template_multi_scale(
                roi, template_path, threshold=threshold, scales=template_scales
            )
        if not m:
            continue
        lx, ly, _s = m
        if not require_ocr:
            return True
        rx1 = max(0, lx - 80)
        ry1 = max(0, ly - 30)
        rx2 = min(roi.shape[1], lx + 80)
        ry2 = min(roi.shape[0], ly + 30)
        if rx2 <= rx1 or ry2 <= ry1:
            continue
        if ocr_matches_action(roi[ry1:ry2, rx1:rx2], action_name):
            return True
    return False


def main_has_pending_work(
    actions_enabled: Dict[str, bool],
    threshold: float = 0.62,
    require_ocr: bool = True,
    template_scales: Optional[List[float]] = None,
) -> bool:
    if not any(actions_enabled.values()):
        return False
    try:
        frame = capture_game_region()
    except Exception:
        return False
    templates = [(n, p) for n, p in get_main_action_templates() if actions_enabled.get(n, False)]
    if not templates:
        return False
    band = locate_button_band_relative_cached()
    if action_pending_in_frame(
        frame,
        templates,
        actions_enabled,
        band,
        threshold,
        require_ocr=require_ocr,
        template_scales=template_scales,
    ):
        return True
    if band is not None and action_pending_in_frame(
        frame,
        templates,
        actions_enabled,
        None,
        threshold,
        require_ocr=require_ocr,
        template_scales=template_scales,
    ):
        return True
    return False


def steal_friend_has_pending_work(
    actions_enabled: Dict[str, bool], threshold: float = STEAL_UI_MATCH_THRESHOLD
) -> bool:
    if not any(actions_enabled.values()):
        return False
    try:
        frame = capture_game_region()
    except Exception:
        return False
    templates = [(n, p) for n, p in get_steal_action_templates() if actions_enabled.get(n, False)]
    if not templates:
        return False
    band = locate_steal_button_band_relative_cached()
    if action_pending_in_frame(
        frame,
        templates,
        actions_enabled,
        band=band,
        threshold=threshold,
        require_ocr=False,
        use_steal_ui_match=True,
        steal_scales=STEAL_UI_TEMPLATE_SCALES_FAST,
    ):
        return True
    return action_pending_in_frame(
        frame,
        templates,
        actions_enabled,
        band=None,
        threshold=threshold,
        require_ocr=False,
        use_steal_ui_match=True,
        steal_scales=STEAL_UI_TEMPLATE_SCALES_FAST,
    )


def find_steal_scene_template_png() -> Optional[Path]:
    for filename in STEAL_SCENE_TEMPLATE_CANDIDATES:
        p = resolve_asset_png_path(filename)
        if p is not None:
            return p
    return None


def _missing_steal_template_names(actions_enabled: Dict[str, bool]) -> List[str]:
    existing = {name for name, _ in get_steal_action_templates()}
    missing: List[str] = []
    for action_name, filename in STEAL_ACTION_TEMPLATE_FIXED_MAPPING:
        if not actions_enabled.get(action_name, False):
            continue
        if action_name not in existing:
            missing.append(filename)
    return missing


def _steal_roi_is_valid(roi_bgr: np.ndarray) -> bool:
    if roi_bgr is None or roi_bgr.size == 0:
        return False
    h, w = roi_bgr.shape[:2]
    return h >= 24 and w >= 24


def _best_steal_template_score(
    roi_bgr: np.ndarray,
    template_path: Path,
    scales: Optional[List[float]] = None,
) -> float:
    m = detect_template_multi_scale(
        roi_bgr,
        template_path,
        threshold=0.0,
        scales=scales if scales is not None else STEAL_UI_TEMPLATE_SCALES_FAST,
    )
    if not m:
        return 0.0
    return float(m[2])


def _friend_farm_scene_present(
    frame_bgr: np.ndarray,
    roi_bgr: np.ndarray,
    templates: List[Tuple[str, Path]],
    threshold: float,
) -> Tuple[bool, float]:
    home_btn = find_asset_png_root("偷菜界面", "回家")
    if home_btn is not None:
        # 新判定优先：在「偷菜界面-判定为偷菜界面区域.png」红框内命中回家按钮即视为偷菜界面。
        in_scene, home_score = steal_scene_present_by_home_button(
            frame_bgr,
            home_btn,
            threshold=max(0.48, float(threshold)),
        )
        if in_scene:
            return True, home_score
    scene_tpl = find_steal_scene_template_png()
    if scene_tpl is not None:
        score = _best_steal_template_score(roi_bgr, scene_tpl, scales=STEAL_UI_TEMPLATE_SCALES_FAST)
        return score >= float(threshold), score
    best = 0.0
    for _name, template_path in templates:
        best = max(best, _best_steal_template_score(roi_bgr, template_path, scales=STEAL_UI_TEMPLATE_SCALES_FAST))
    return best >= float(threshold), best


def run_steal_interface_actions_once(
    actions_enabled: Dict[str, bool],
    threshold: float = STEAL_UI_MATCH_THRESHOLD,
    stop_event: Optional[threading.Event] = None,
    max_action_rounds: int = 6,
    steal_scales: Optional[List[float]] = None,
) -> Dict[str, str]:
    enabled_actions = [k for k, v in actions_enabled.items() if v]
    if not enabled_actions:
        return {"status": "skipped", "message": "未勾选偷菜农场动作。"}

    region = load_config_region()
    if not region:
        return {"status": "error", "message": "未设置游戏窗口。"}

    templates = [(name, path) for name, path in get_steal_action_templates() if actions_enabled.get(name, False)]
    if not templates:
        missing = _missing_steal_template_names(actions_enabled)
        return {
            "status": "skipped",
            "reason": "template_missing",
            "message": f"模板缺失：{','.join(missing) if missing else '偷菜界面-一键*.png'}",
        }

    band_cached = locate_steal_button_band_relative_cached()
    frame_scene = capture_game_region()
    roi_scene, _sx, _sy = crop_by_relative_band(frame_scene, band_cached)
    if not _steal_roi_is_valid(roi_scene):
        return {
            "status": "skipped",
            "reason": "roi_invalid",
            "message": "ROI无效：好友农场识别区域为空或过小。",
        }
    scene_ok, scene_score = _friend_farm_scene_present(
        frame_scene,
        roi_scene,
        templates,
        threshold=float(threshold),
    )
    if not scene_ok:
        return {
            "status": "skipped",
            "reason": "not_friend_farm",
            "message": f"非好友农场：命中分不足（best={scene_score:.3f}, threshold={float(threshold):.3f}）。",
        }

    clicked = []
    clicked_actions: set = set()
    best_miss_score = 0.0
    filtered_out_by_limit = 0
    filtered_out_by_score = 0
    filtered_out_by_raw_score = 0
    filtered_samples: List[str] = []
    # 每个任务最多点击一次，但允许同轮继续尝试其它任务。
    min_click_score = max(0.54, float(threshold) + 0.05)
    limit_roi = load_steal_task_click_limit_roi_relative()
    click_gap_sec = 0.12
    first_click_pre_delay_sec = 0.10
    rounds = max(1, int(max_action_rounds))
    for _round in range(rounds):
        if stop_event and stop_event.is_set():
            return {"status": "stopped", "message": "已停止。"}
        frame = capture_game_region()
        roi, offset_x, offset_y = crop_by_relative_band(frame, band_cached)
        if not _steal_roi_is_valid(roi):
            return {
                "status": "skipped",
                "reason": "roi_invalid",
                "message": "ROI无效：好友农场按钮区域为空或过小。",
            }
        round_hit = 0
        shuffled = templates[:]
        random.shuffle(shuffled)
        for action_name, template_path in shuffled:
            if stop_event and stop_event.is_set():
                return {"status": "stopped", "message": "已停止。"}
            if action_name in clicked_actions:
                continue
            raw_score = _best_steal_template_score(
                roi,
                template_path,
                scales=steal_scales if steal_scales is not None else STEAL_UI_TEMPLATE_SCALES_FAST,
            )
            best_miss_score = max(best_miss_score, raw_score)
            match = detect_template_multi_scale_steal_ui(
                roi, template_path, base_threshold=threshold, scales=steal_scales
            )
            if not match:
                filtered_out_by_raw_score += 1
                if len(filtered_samples) < 12:
                    filtered_samples.append(f"{action_name}:no_match(raw={raw_score:.3f})")
                continue
            local_x, local_y, score = match
            if float(score) < float(min_click_score):
                filtered_out_by_score += 1
                if len(filtered_samples) < 12:
                    filtered_samples.append(f"{action_name}:click={score:.3f}<click_min={min_click_score:.3f}")
                continue
            if limit_roi:
                fh, fw = frame.shape[:2]
                fx = int(offset_x + local_x)
                fy = int(offset_y + local_y)
                x_rel = float(fx) / float(max(1, fw))
                y_rel = float(fy) / float(max(1, fh))
                if not _point_in_relative_roi(x_rel, y_rel, limit_roi, margin=0.01):
                    filtered_out_by_limit += 1
                    if len(filtered_samples) < 12:
                        filtered_samples.append(
                            f"{action_name}:outside_limit(score={score:.3f},x={x_rel:.3f},y={y_rel:.3f})"
                        )
                    continue
            # 好友农场动作点击：以图像匹配为准，不再做 OCR 二次门禁，避免背景变化导致漏点。
            if stop_event and stop_event.is_set():
                return {"status": "stopped", "message": "已停止。"}
            if not clicked and interruptible_sleep(stop_event, first_click_pre_delay_sec):
                return {"status": "stopped", "message": "已停止。"}
            pyautogui.click(region["x"] + offset_x + local_x, region["y"] + offset_y + local_y)
            record_friend_action(action_name)
            clicked.append(f"{action_name}({score:.2f})")
            clicked_actions.add(action_name)
            round_hit += 1
            # 防止同一帧连续连点导致坐标漂移（误点到头像区）：每次点击后短停并重抓当前画面。
            if interruptible_sleep(stop_event, click_gap_sec):
                return {"status": "stopped", "message": "已停止。"}
            frame = capture_game_region()
            roi, offset_x, offset_y = crop_by_relative_band(frame, band_cached)
            if not _steal_roi_is_valid(roi):
                return {
                    "status": "skipped",
                    "reason": "roi_invalid",
                    "message": "ROI无效：好友农场按钮区域为空或过小。",
                }
        if round_hit == 0:
            break

    if not clicked:
        if filtered_samples:
            _diag(
                "steal_worker",
                "click_filtered_samples",
                "偷菜点击候选被过滤",
                raw_filtered=filtered_out_by_raw_score,
                click_filtered=filtered_out_by_score,
                limit_filtered=filtered_out_by_limit,
                samples=" | ".join(filtered_samples),
            )
        if filtered_out_by_raw_score > 0:
            return {
                "status": "skipped",
                "reason": "no_valid_match",
                "message": (
                    f"未找到可执行模板命中（filtered={filtered_out_by_raw_score}），已跳过点击。"
                ),
            }
        if filtered_out_by_score > 0:
            return {
                "status": "skipped",
                "reason": "score_below_click_floor",
                "message": (
                    f"命中分低于点击下限（min_click_score={min_click_score:.3f}, "
                    f"filtered={filtered_out_by_score}），已跳过点击。"
                ),
            }
        if filtered_out_by_limit > 0:
            return {
                "status": "skipped",
                "reason": "click_outside_limit_roi",
                "message": f"命中点均在任务限制区域外（filtered={filtered_out_by_limit}），已跳过点击。",
            }
        return {
            "status": "skipped",
            "reason": "score_below_threshold",
            "message": (
                f"命中分不足：无可点击按钮（best={best_miss_score:.3f}, "
                f"threshold={float(threshold):.3f}）。"
            ),
        }
    if filtered_samples:
        _diag(
            "steal_worker",
            "click_filtered_samples",
            "偷菜点击候选被过滤（本轮仍有成功点击）",
            raw_filtered=filtered_out_by_raw_score,
            click_filtered=filtered_out_by_score,
            limit_filtered=filtered_out_by_limit,
            samples=" | ".join(filtered_samples),
        )
    return {"status": "done", "message": f"偷菜农场点击：{', '.join(clicked)}"}


def patrol_loop_worker(
    stop_event: threading.Event,
    status_callback,
    session_start_monotonic: Optional[float] = None,
) -> None:
    def quit_patrol() -> None:
        _diag("patrol", "quit", "巡查线程结束或用户停止", level="info")
        status_callback("巡查已停止。")

    t_sess = float(session_start_monotonic) if session_start_monotonic is not None else time.monotonic()
    first_action_recorded = False

    def record_first_action(phase: str) -> None:
        nonlocal first_action_recorded
        if first_action_recorded:
            return
        first_action_recorded = True
        el = round(time.monotonic() - t_sess, 3)
        _diag(
            "timing",
            "first_action_after_start_patrol",
            "从开始自动巡查到首次操作",
            elapsed_sec=el,
            phase=phase,
        )
        try:
            status_callback(f"计时：约 {el}s 后首次操作（{phase}），各阶段见 logs/diagnostic_*.jsonl")
        except Exception:
            pass

    _diag(
        "timing",
        "patrol_worker_started",
        "巡查线程已启动",
        thread_delay_sec=round(time.monotonic() - t_sess, 4),
    )

    th_main = MAIN_INTERFACE_PATROL_TEMPLATE_THRESHOLD

    while not stop_event.is_set():
        try:
            t_cycle = time.monotonic()
            _diag(
                "timing",
                "cycle_begin",
                elapsed_since_session_sec=round(t_cycle - t_sess, 3),
            )
            region = load_config_region()
            if not region:
                _diag("patrol", "no_region", "未设置游戏窗口，等待", level="warn")
                status_callback("巡查暂停：未设置游戏窗口。")
                if interruptible_sleep(stop_event, PATROL_MIN_CYCLE_GAP_SEC):
                    quit_patrol()
                    return
                continue

            cfg = load_steal_feature_config()
            main_iv = max(PATROL_MIN_MAIN_INTERVAL_SEC, float(cfg["main_patrol_interval_sec"]))
            friend_iv = max(PATROL_MIN_FRIEND_INTERVAL_SEC, float(cfg["friend_patrol_interval_sec"]))
            main_actions = load_main_interface_actions_enabled()
            steal_on = cfg["master_enabled"]
            steal_actions = cfg["actions"]
            _diag(
                "patrol",
                "cycle_begin",
                "新一轮巡查",
                main_interval_sec=main_iv,
                friend_interval_sec=friend_iv,
                steal_master=steal_on,
                main_actions_on={k: v for k, v in main_actions.items() if v},
                steal_actions_on={k: v for k, v in steal_actions.items() if v},
            )

            # 只要勾了主界面动作，每轮至少执行一次（不依赖「有待办」预判，避免未勾选偷菜时整轮不点主界面）
            if any(main_actions.values()):
                t_ma = time.monotonic()
                r0 = run_main_interface_actions_once(
                    main_actions,
                    threshold=th_main,
                    ocr_enabled=False,
                    stop_event=stop_event,
                    max_action_rounds=PATROL_MAIN_MAX_ACTION_ROUNDS,
                    template_scales=PATROL_TEMPLATE_SCALES,
                )
                _diag(
                    "timing",
                    "main_actions_round1",
                    duration_sec=round(time.monotonic() - t_ma, 3),
                    since_cycle_sec=round(time.monotonic() - t_cycle, 3),
                )
                _diag(
                    "patrol",
                    "main_actions_once",
                    str(r0.get("message", "")),
                    status=r0.get("status"),
                )
                if r0.get("status") == "stopped":
                    quit_patrol()
                    return
                if "已执行点击" in str(r0.get("message", "")):
                    record_first_action("主界面一键")
                _pending_pass = 0
                while (
                    not stop_event.is_set()
                    and _pending_pass < PATROL_MAIN_PENDING_MAX_EXTRA_PASSES
                    and main_has_pending_work(
                        main_actions,
                        threshold=th_main,
                        require_ocr=False,
                        template_scales=PATROL_TEMPLATE_SCALES,
                    )
                ):
                    if interruptible_sleep(stop_event, main_iv):
                        quit_patrol()
                        return
                    t_mf = time.monotonic()
                    r = run_main_interface_actions_once(
                        main_actions,
                        threshold=th_main,
                        ocr_enabled=False,
                        stop_event=stop_event,
                        max_action_rounds=PATROL_MAIN_MAX_ACTION_ROUNDS,
                        template_scales=PATROL_TEMPLATE_SCALES,
                    )
                    _pending_pass += 1
                    _diag(
                        "timing",
                        "main_actions_followup_pass",
                        duration_sec=round(time.monotonic() - t_mf, 3),
                    )
                    _diag(
                        "patrol",
                        "main_actions_followup",
                        str(r.get("message", "")),
                        status=r.get("status"),
                    )
                    if r.get("status") == "stopped":
                        quit_patrol()
                        return
                    if "已执行点击" in str(r.get("message", "")):
                        record_first_action("主界面一键")

            if steal_on and any(steal_actions.values()):
                friend_btn = find_asset_png_root("主界面", "好友")
                visit_icon = find_visit_panel_judge_icon_png() or find_asset_png_root("拜访界面", "判断", "图标")
                visit_btn = find_visit_panel_visit_button_png()
                close_btn = find_visit_panel_close_button_png() or (
                    find_asset_png_root("拜访界面", "×") or find_asset_png_root("拜访界面", "x")
                )
                home_btn = find_asset_png_root("偷菜界面", "回家")

                if not friend_btn or not visit_icon or not visit_btn or not close_btn or not home_btn:
                    _diag(
                        "patrol",
                        "steal_assets_missing",
                        "缺少好友/拜访/回家等素材，跳过偷菜",
                        level="warn",
                        has_friend_btn=friend_btn is not None,
                        has_visit_icon=visit_icon is not None,
                        has_visit_btn=visit_btn is not None,
                        has_close_btn=close_btn is not None,
                        has_home_btn=home_btn is not None,
                    )
                    status_callback("巡查：缺少拜访/好友相关素材，跳过偷菜流程。")
                    if interruptible_sleep(stop_event, main_iv):
                        quit_patrol()
                        return
                else:
                    ensure_visit_check_roi_cached()
                    ensure_visit_zones_from_user_samples()
                    roi_rel = load_visit_check_roi_relative()

                    if stop_event.is_set():
                        quit_patrol()
                        return
                    frame = capture_game_region()
                    # 上轮若停在拜访面板，本轮先尝试关闭，避免一直不在主界面导致好友按钮持续 miss。
                    if visit_panel_present_strict(frame, roi_rel, visit_icon, close_btn_path=close_btn):
                        _diag("patrol", "visit_panel_left_open", "检测到拜访窗口仍打开，先尝试关闭", level="warn")
                        click_template_on_game_frame_retry(
                            region, close_btn, threshold=0.48, attempts=4, gap_sec=0.04
                        )
                        if interruptible_sleep(stop_event, 0.0):
                            quit_patrol()
                            return
                        # 强约束：拜访面板仍开时，不允许继续点「好友」，避免在错误界面误命中乱点。
                        frame_after_close = capture_game_region()
                        if visit_panel_present_strict(
                            frame_after_close, roi_rel, visit_icon, close_btn_path=close_btn
                        ):
                            _diag(
                                "patrol",
                                "visit_panel_still_open_skip_friend_click",
                                "拜访窗口未成功关闭，本轮跳过好友点击",
                                level="warn",
                            )
                            status_callback("巡查：拜访窗口未关闭，已跳过本轮好友点击。")
                            if interruptible_sleep(stop_event, friend_iv):
                                quit_patrol()
                                return
                            continue
                    if not click_friend_button_with_retry(region, friend_btn, stop_event=stop_event):
                        _diag("patrol", "friend_button_miss", "当前画面未匹配到主界面好友按钮", level="warn")
                        status_callback("巡查：未匹配到好友按钮。")
                        if interruptible_sleep(stop_event, main_iv):
                            quit_patrol()
                            return
                    else:
                        _diag("patrol", "friend_button_click", "已点击好友，等待拜访弹窗")
                        record_first_action("点击好友")
                        t_settle0 = time.monotonic()
                        if interruptible_sleep(
                            stop_event,
                            max(AFTER_FRIEND_CLICK_MIN_SETTLE_SEC, float(AFTER_FRIEND_CLICK_SETTLE_SEC)),
                        ):
                            quit_patrol()
                            return
                        _diag(
                            "timing",
                            "after_friend_click_settle",
                            duration_sec=round(time.monotonic() - t_settle0, 3),
                            since_cycle_sec=round(time.monotonic() - t_cycle, 3),
                        )
                        panel_wait = max(VISIT_PANEL_JUDGE_MIN_WAIT_SEC, float(friend_iv) * 3.0)
                        t_judge = time.monotonic()
                        frame, has_judge = wait_for_visit_judge_icon(
                            roi_rel,
                            visit_icon,
                            stop_event,
                            max_wait_sec=panel_wait,
                            poll_sec=max(VISIT_POLL_MIN_SEC, float(VISIT_PANEL_JUDGE_POLL_SEC)),
                        )
                        _diag(
                            "timing",
                            "wait_visit_judge_icon",
                            duration_sec=round(time.monotonic() - t_judge, 3),
                            has_judge=has_judge,
                            since_cycle_sec=round(time.monotonic() - t_cycle, 3),
                        )
                        if stop_event.is_set():
                            quit_patrol()
                            return
                        if not has_judge:
                            _diag(
                                "patrol",
                                "visit_panel_no_judge",
                                "未在超时内识别到拜访列表判断图标",
                                level="warn",
                                panel_wait_sec=panel_wait,
                            )
                            status_callback(
                                "巡查：点好友后未在设定时间内识别到拜访列表判断图标，将关闭。"
                                "请对照 logs/debug_visit_check_roi.png / logs/debug_visit_game_full.png；"
                                "红框样图仅用于推算检查区，匹配只用判断图标模板。"
                                f"（本步至少等待 {VISIT_PANEL_JUDGE_MIN_WAIT_SEC:g}s，与巡查间隔无关；仍失败请检查判断图标模板与红框。）"
                            )
                            try:
                                dbg_dir = PROJECT_DIR / "logs"
                                dbg_dir.mkdir(parents=True, exist_ok=True)
                                er = expand_relative_roi(roi_rel)
                                roi_dbg, _, _ = crop_by_relative_band(frame, er)
                                if roi_dbg.size > 0:
                                    cv2.imwrite(str(dbg_dir / "debug_visit_check_roi.png"), roi_dbg)
                                cv2.imwrite(str(dbg_dir / "debug_visit_game_full.png"), frame)
                            except Exception:
                                pass
                        if has_judge:
                            zone12_close = False
                            frame_check_z = capture_game_region()
                            panel_r = load_visit_panel_roi_relative()
                            z_insp = load_visit_zones_inspect_relative()
                            if (
                                VISIT_ZONE12_AUTO_CLOSE_ENABLED
                                and panel_r
                                and z_insp
                                and len(z_insp) >= 2
                            ):
                                jc = count_judge_icons_per_zone(
                                    frame_check_z, panel_r, z_insp, visit_icon
                                )
                                if len(jc) >= 2 and jc[0] > 0 and jc[1] == 0:
                                    _diag(
                                        "patrol",
                                        "visit_zone12_rule_close",
                                        "一区有判断图标、二区无，关闭拜访窗口",
                                        judge_counts=jc,
                                    )
                                    status_callback(
                                        "巡查：一区有判断图标、二区无，按规则关闭拜访窗口。"
                                    )
                                    if not stop_event.is_set():
                                        fc = capture_game_region()
                                        click_template_on_game_frame(
                                            fc, region, close_btn, threshold=0.5
                                        )
                                    if interruptible_sleep(stop_event, friend_iv):
                                        quit_patrol()
                                        return
                                    zone12_close = True
                            if not zone12_close:
                                frame_list = capture_game_region()
                                t_pick = time.monotonic()
                                cand = pick_next_visit_candidate_zoned(
                                    frame_list,
                                    roi_rel,
                                    visit_icon,
                                    visit_btn,
                                    stop_event,
                                    zone_boundaries_relative=cfg.get("visit_zone_boundaries_relative"),
                                )
                                _diag(
                                    "timing",
                                    "pick_visit_candidate",
                                    duration_sec=round(time.monotonic() - t_pick, 3),
                                    found=cand is not None,
                                    since_cycle_sec=round(time.monotonic() - t_cycle, 3),
                                )
                                if stop_event.is_set():
                                    quit_patrol()
                                    return
                                if not cand:
                                    _diag(
                                        "patrol",
                                        "visit_no_candidate",
                                        "拜访列表无可用行（可能已屏蔽或未匹配）",
                                        level="warn",
                                    )
                                    status_callback(
                                        "巡查：拜访列表无可用行（未匹配到判断图标+拜访），关闭面板。"
                                    )
                                    if not stop_event.is_set():
                                        frame2 = capture_game_region()
                                        click_template_on_game_frame(
                                            frame2, region, close_btn, threshold=0.5
                                        )
                                    if interruptible_sleep(stop_event, friend_iv):
                                        quit_patrol()
                                        return
                                else:
                                    fx, fy, fname, name_strip = cand
                                    _diag(
                                        "patrol",
                                        "visit_chosen",
                                        f"选中拜访: {fname}",
                                        frame_xy=(fx, fy),
                                    )
                                    if not click_visit_at_frame_xy(region, fx, fy, stop_event):
                                        if stop_event.is_set():
                                            quit_patrol()
                                        return
                                    record_first_action("点击拜访")
                                    t_out = time.monotonic()
                                    outcome = wait_after_visit_click(
                                        roi_rel,
                                        visit_icon,
                                        home_btn,
                                        close_btn,
                                        stop_event,
                                        max_wait_sec=max(
                                            VISIT_OUTCOME_MIN_WAIT_SEC, float(friend_iv) * 2.0
                                        ),
                                        poll_sec=max(VISIT_POLL_MIN_SEC, float(VISIT_TO_FARM_POLL_SEC)),
                                    )
                                    _diag(
                                        "timing",
                                        "wait_after_visit_click",
                                        duration_sec=round(time.monotonic() - t_out, 3),
                                        outcome=outcome,
                                        since_cycle_sec=round(time.monotonic() - t_cycle, 3),
                                    )
                                    if outcome == "stopped":
                                        quit_patrol()
                                        return
                                    _diag("patrol", "after_visit_click", f"拜访后状态: {outcome}", outcome=outcome)
                                    if outcome == "farm":
                                        if interruptible_sleep(
                                            stop_event, FRIEND_FARM_AFTER_VISIT_SETTLE_SEC
                                        ):
                                            quit_patrol()
                                            return
                                        # 有任务才循环偷菜；无任务时不先空等 friend_iv，尽快点回家
                                        steal_rounds = 0
                                        while not stop_event.is_set():
                                            if not steal_friend_has_pending_work(steal_actions):
                                                break
                                            t_st = time.monotonic()
                                            r_steal = run_steal_interface_actions_once(
                                                steal_actions,
                                                stop_event=stop_event,
                                                max_action_rounds=PATROL_STEAL_MAX_ACTION_ROUNDS,
                                                steal_scales=STEAL_UI_TEMPLATE_SCALES_FAST,
                                            )
                                            _diag(
                                                "timing",
                                                "steal_farm_round",
                                                duration_sec=round(time.monotonic() - t_st, 3),
                                                round_index=steal_rounds + 1,
                                                since_cycle_sec=round(time.monotonic() - t_cycle, 3),
                                            )
                                            steal_rounds += 1
                                            _diag(
                                                "steal",
                                                "friend_farm_round",
                                                str(r_steal.get("message", "")),
                                                round_index=steal_rounds,
                                                status=r_steal.get("status"),
                                            )
                                            if "偷菜农场点击" in str(r_steal.get("message", "")):
                                                record_first_action("好友农场一键")
                                            if r_steal.get("status") == "stopped":
                                                quit_patrol()
                                                return
                                            msg_steal = str(r_steal.get("message", ""))
                                            if "无可点击" in msg_steal:
                                                break
                                            if interruptible_sleep(stop_event, friend_iv):
                                                quit_patrol()
                                                return
                                        if stop_event.is_set():
                                            quit_patrol()
                                            return
                                        _diag(
                                            "patrol",
                                            "farm_go_home",
                                            "好友农场流程结束，尝试点回家",
                                            steal_rounds_executed=steal_rounds,
                                        )
                                        t_home = time.monotonic()
                                        home_ok = click_template_on_game_frame_retry(
                                            region,
                                            home_btn,
                                            threshold=0.48,
                                            attempts=6,
                                            gap_sec=0.0,
                                        )
                                        _diag(
                                            "timing",
                                            "click_go_home_retry",
                                            duration_sec=round(time.monotonic() - t_home, 3),
                                            matched=home_ok,
                                            since_cycle_sec=round(time.monotonic() - t_cycle, 3),
                                        )
                                        if not home_ok:
                                            _diag(
                                                "patrol",
                                                "home_button_miss",
                                                "未匹配回家按钮",
                                                level="warn",
                                            )
                                            status_callback("巡查：未匹配回家按钮。")
                                        if interruptible_sleep(
                                            stop_event, FRIEND_FARM_AFTER_HOME_CLICK_SEC
                                        ):
                                            quit_patrol()
                                            return
                                    else:
                                        _diag(
                                            "patrol",
                                            "visit_unknown_outcome",
                                            f"拜访后未识别为农场/仍面板: {outcome}",
                                            level="warn",
                                            outcome=outcome,
                                        )
                                        status_callback(
                                            "巡查：点击拜访后未进入好友农场，关闭拜访窗口。"
                                        )
                                        if not stop_event.is_set():
                                            frame_bad = capture_game_region()
                                            click_template_on_game_frame(
                                                frame_bad, region, close_btn, threshold=0.5
                                            )
                                        if interruptible_sleep(stop_event, friend_iv):
                                            quit_patrol()
                                            return
                        else:
                            if not stop_event.is_set():
                                frame_close = capture_game_region()
                                click_template_on_game_frame(frame_close, region, close_btn)
                            if interruptible_sleep(stop_event, friend_iv):
                                quit_patrol()
                                return
            else:
                if interruptible_sleep(stop_event, main_iv):
                    quit_patrol()
                    return

            _diag(
                "timing",
                "cycle_end",
                cycle_wall_sec=round(time.monotonic() - t_cycle, 3),
                elapsed_since_session_sec=round(time.monotonic() - t_sess, 3),
            )
            _diag("patrol", "cycle_idle", "本轮巡查告一段落，进入下一轮间隔")
            status_callback("巡查运行中…")
            cycle_used = time.monotonic() - t_cycle
            tail_gap = max(0.0, float(PATROL_MIN_CYCLE_GAP_SEC) - float(cycle_used))
            if tail_gap > 1e-6 and interruptible_sleep(stop_event, tail_gap):
                quit_patrol()
                return
        except Exception as exc:
            _diag(
                "patrol",
                "exception",
                str(exc),
                level="error",
                exc_type=type(exc).__name__,
            )
            status_callback(f"巡查异常：{exc}")
            if interruptible_sleep(stop_event, PATROL_MIN_CYCLE_GAP_SEC):
                quit_patrol()
                return


def launch_gui(
    reference_image: Optional[str],
    threshold: float,
    expected_region_size: Tuple[int, int],
    auto_region_mode: str,
    open_diag_console_scripts: bool = True,
) -> None:
    _diag_init()
    root = tk.Tk()
    root.title("QQ Farm Region Tool")
    _diag("gui", "window_open", "图形界面已启动", level="info")
    window_w, window_h = 800, 740
    screen_w = root.winfo_screenwidth()
    screen_h = root.winfo_screenheight()
    pos_x = max(0, (screen_w - window_w) // 2)
    pos_y = max(0, (screen_h - window_h) // 2)
    root.geometry(f"{window_w}x{window_h}+{pos_x}+{pos_y}")
    root.resizable(False, False)

    status_var = tk.StringVar(value="就绪")
    action_enabled_saved = load_main_interface_actions_enabled()
    action_vars = {
        "收获": tk.BooleanVar(value=action_enabled_saved["收获"]),
        "浇水": tk.BooleanVar(value=action_enabled_saved["浇水"]),
        "除虫": tk.BooleanVar(value=action_enabled_saved["除虫"]),
        "除草": tk.BooleanVar(value=action_enabled_saved["除草"]),
    }

    header = tk.Label(root, text="游戏窗口定位工具", font=("Microsoft YaHei UI", 12, "bold"))
    header.pack(pady=(14, 8))

    hint = tk.Label(
        root,
        text="自动读取窗口与手动框选窗口为并列功能，按需点击。",
        font=("Microsoft YaHei UI", 9),
        wraplength=720,
        justify="left",
    )
    hint.pack(pady=(0, 8))

    status = tk.Label(root, textvariable=status_var, fg="#333333", wraplength=720, justify="left")
    status.pack(pady=(0, 10))

    def resolve_ref() -> str:
        if reference_image:
            return reference_image
        default_ref = get_default_reference_image()
        if not default_ref:
            raise FileNotFoundError("No PNG found in assets/yinyong/. Please add one or pass --ref.")
        return str(default_ref)

    def on_auto() -> None:
        try:
            ref = resolve_ref()
            _diag("region", "auto_locate_start", "开始自动读取游戏区域", ref_image=ref)
            region = acquire_game_region_auto(
                reference_image=ref,
                threshold=threshold,
                expected_region_size=expected_region_size,
                auto_region_mode=auto_region_mode,
            )
            _diag("region", "auto_locate_ok", "自动读取成功", region=region)
            status_var.set(f"自动读取成功: {region}")
            messagebox.showinfo("成功", f"自动读取并保存成功\n{region}")
        except Exception as exc:
            _diag("region", "auto_locate_fail", str(exc), level="error", exc_type=type(exc).__name__)
            status_var.set(f"自动读取失败: {exc}")
            messagebox.showerror("自动读取失败", str(exc))

    def on_manual() -> None:
        try:
            _diag("region", "manual_locate_start", "开始手动框选游戏区域")
            region = acquire_game_region_manual()
            _diag("region", "manual_locate_ok", "手动框取成功", region=region)
            status_var.set(f"已手动框选并保存游戏区域: {region}")
            messagebox.showinfo("成功", f"手动框选并保存成功\n{region}")
        except Exception as exc:
            _diag("region", "manual_locate_fail", str(exc), level="error", exc_type=type(exc).__name__)
            status_var.set(f"手动框取失败: {exc}")
            messagebox.showerror("手动框取失败", str(exc))

    def on_preview() -> None:
        try:
            _diag("region", "preview_save", "保存预览图")
            region = save_preview(str(ASSETS_ROOT / "game_preview.png"))
            _diag("region", "preview_ok", "预览已保存", region=region)
            status_var.set(f"已保存预览图 {ASSETS_ROOT / 'game_preview.png'}: {region}")
            messagebox.showinfo("预览已保存", f"已保存 {ASSETS_ROOT / 'game_preview.png'}\n{region}")
        except Exception as exc:
            _diag("region", "preview_fail", str(exc), level="error", exc_type=type(exc).__name__)
            status_var.set(f"预览失败: {exc}")
            messagebox.showerror("预览失败", str(exc))

    def persist_actions(*_args: object) -> None:
        save_main_interface_actions_enabled({k: v.get() for k, v in action_vars.items()})
        picked = [k for k, v in action_vars.items() if v.get()]
        status_var.set(f"主界面动作已保存：{','.join(picked) if picked else '无'}")

    for _k, var in action_vars.items():
        var.trace_add("write", persist_actions)

    steal_cfg = load_steal_feature_config()
    steal_master_var = tk.BooleanVar(value=steal_cfg["master_enabled"])
    _m = steal_cfg["master_enabled"]
    steal_action_vars = {
        "摘取": tk.BooleanVar(value=steal_cfg["actions"]["摘取"] if _m else False),
        "浇水": tk.BooleanVar(value=steal_cfg["actions"]["浇水"] if _m else False),
        "除虫": tk.BooleanVar(value=steal_cfg["actions"]["除虫"] if _m else False),
        "除草": tk.BooleanVar(value=steal_cfg["actions"]["除草"] if _m else False),
    }
    main_iv_str = tk.StringVar(value=str(steal_cfg["main_patrol_interval_sec"]))
    friend_iv_str = tk.StringVar(value=str(steal_cfg["friend_patrol_interval_sec"]))
    patrol_stop_event = threading.Event()
    patrol_thread_holder: List[Optional[threading.Thread]] = [None]
    diag_subprocs: List[subprocess.Popen] = []

    def on_exit() -> None:
        patrol_stop_event.set()
        _diag("gui", "exit_clicked", "用户退出程序，主界面即将关闭", level="info")
        root.destroy()

    def persist_steal_settings() -> None:
        try:
            mi = float(main_iv_str.get().strip())
            fi = float(friend_iv_str.get().strip())
        except ValueError:
            mi, fi = 2.0, 2.0
        acts = {k: v.get() for k, v in steal_action_vars.items()}
        if not steal_master_var.get():
            acts = {k: False for k in acts}
        save_steal_feature_config(
            steal_master_var.get(),
            acts,
            mi,
            fi,
            friend_list_scroll_steps=0,
        )

    steal_cb_widgets: List[tk.Checkbutton] = []

    def on_steal_master_change(*_args: object) -> None:
        if steal_master_var.get():
            for w in steal_cb_widgets:
                w.config(state=tk.NORMAL)
        else:
            for k, v in steal_action_vars.items():
                v.set(False)
            for w in steal_cb_widgets:
                w.config(state=tk.DISABLED)
        persist_steal_settings()
        picked = [k for k, v in steal_action_vars.items() if v.get()]
        status_var.set(f"偷菜功能：{'开' if steal_master_var.get() else '关'}；动作={','.join(picked) if picked else '无'}")

    def persist_steal_subs(*_args: object) -> None:
        if steal_master_var.get():
            persist_steal_settings()

    steal_master_var.trace_add("write", on_steal_master_change)
    for _sk, svar in steal_action_vars.items():
        svar.trace_add("write", persist_steal_subs)

    def on_run_feature_once() -> None:
        result = run_main_interface_actions_once(
            actions_enabled=load_main_interface_actions_enabled(),
            threshold=0.7,
            ocr_enabled=True,
        )
        status_var.set(result["message"])
        if result["status"] == "error":
            messagebox.showerror("执行失败", result["message"])
        else:
            messagebox.showinfo("执行结果", result["message"])

    btn_frame = tk.Frame(root)
    btn_frame.pack(pady=6)

    # 不在此用 Button 的 command=：若在别处按下、拖到「自动读取」上松开，Tk 会把 Release 交给该按钮，误触全屏匹配。
    # 仅当「在本按钮按下且在本按钮松开」时才执行；任意在其它控件松开则清除预按状态。
    _region_mouse_btns: List[tk.Button] = []

    def _global_mouseup_clear_region_arms(e: tk.Event) -> None:
        w = e.widget
        for b in _region_mouse_btns:
            if w is not b:
                setattr(b, "_region_btn_armed", False)

    def _wire_region_mouse_btn(btn: tk.Button, cb: Callable[[], None]) -> None:
        def press(_e: tk.Event) -> None:
            setattr(btn, "_region_btn_armed", True)

        def release(_e: tk.Event) -> None:
            if getattr(btn, "_region_btn_armed", False):
                cb()
            setattr(btn, "_region_btn_armed", False)

        btn.bind("<ButtonPress-1>", press)
        btn.bind("<ButtonRelease-1>", release)
        _region_mouse_btns.append(btn)

    _region_btn_kw = {"width": 16, "takefocus": False, "font": ("Microsoft YaHei UI", 9)}
    btn_auto = tk.Button(btn_frame, text="自动读取游戏区", **_region_btn_kw)
    btn_manual = tk.Button(btn_frame, text="手动框选游戏区", **_region_btn_kw)
    btn_preview = tk.Button(btn_frame, text="保存预览图", **_region_btn_kw)
    btn_exit = tk.Button(btn_frame, text="退出程序", command=on_exit, **_region_btn_kw)

    _wire_region_mouse_btn(btn_auto, on_auto)
    _wire_region_mouse_btn(btn_manual, on_manual)
    _wire_region_mouse_btn(btn_preview, on_preview)
    root.bind_all("<ButtonRelease-1>", _global_mouseup_clear_region_arms, add="+")

    btn_auto.grid(row=0, column=0, padx=6, pady=6)
    btn_manual.grid(row=0, column=1, padx=6, pady=6)
    btn_preview.grid(row=1, column=0, padx=6, pady=6)
    btn_exit.grid(row=1, column=1, padx=6, pady=6)

    body = tk.Frame(root)
    body.pack(fill="both", expand=True, padx=12, pady=(0, 6))
    body.grid_columnconfigure(0, weight=1)
    body.grid_columnconfigure(1, weight=1)

    left_col = tk.Frame(body)
    left_col.grid(row=0, column=0, sticky="nw", padx=(0, 10))
    right_col = tk.Frame(body)
    right_col.grid(row=0, column=1, sticky="nw", padx=(10, 0))

    feature_frame = tk.LabelFrame(left_col, text="主界面-收获/浇水/除虫/除草", padx=10, pady=10)
    feature_frame.pack(fill="x", pady=(0, 8))

    action_frame = tk.Frame(feature_frame)
    action_frame.grid(row=0, column=0, sticky="w", pady=(0, 8))
    tk.Checkbutton(action_frame, text="收获", variable=action_vars["收获"]).grid(row=0, column=0, padx=(0, 10), sticky="w")
    tk.Checkbutton(action_frame, text="浇水", variable=action_vars["浇水"]).grid(row=0, column=1, padx=(0, 10), sticky="w")
    tk.Checkbutton(action_frame, text="除虫", variable=action_vars["除虫"]).grid(row=0, column=2, padx=(0, 10), sticky="w")
    tk.Checkbutton(action_frame, text="除草", variable=action_vars["除草"]).grid(row=0, column=3, padx=(0, 10), sticky="w")

    btn_run_feature = tk.Button(
        feature_frame, text="执行一次（测试）", width=18, command=on_run_feature_once, takefocus=False
    )
    btn_run_feature.grid(row=1, column=0, pady=(4, 0), sticky="w")

    main_iv_row = tk.Frame(left_col)
    main_iv_row.pack(fill="x", pady=(0, 8))
    tk.Label(main_iv_row, text="我的农场巡查间隔(秒):").pack(side="left")
    tk.Entry(main_iv_row, textvariable=main_iv_str, width=6).pack(side="left", padx=(6, 0))

    steal_frame = tk.LabelFrame(right_col, text="偷菜-好友拜访与好友农场", padx=10, pady=10)
    steal_frame.pack(fill="x", pady=(0, 8))

    cb_steal_master = tk.Checkbutton(
        steal_frame,
        text="启动偷菜功能（关闭时下方动作灰显且不可选）",
        variable=steal_master_var,
    )
    cb_steal_master.grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 6))

    steal_action_row = tk.Frame(steal_frame)
    steal_action_row.grid(row=1, column=0, columnspan=4, sticky="w", pady=(0, 6))
    for idx, (label, key) in enumerate([("摘取", "摘取"), ("浇水", "浇水"), ("除虫", "除虫"), ("除草", "除草")]):
        cb = tk.Checkbutton(steal_action_row, text=label, variable=steal_action_vars[key])
        cb.grid(row=0, column=idx, padx=(0, 8), sticky="w")
        steal_cb_widgets.append(cb)

    friend_iv_row = tk.Frame(right_col)
    friend_iv_row.pack(fill="x", pady=(0, 0))
    tk.Label(friend_iv_row, text="好友农场巡查间隔(秒):").pack(side="left")
    tk.Entry(friend_iv_row, textvariable=friend_iv_str, width=6).pack(side="left", padx=(6, 0))

    patrol_btn_row = tk.Frame(root)
    patrol_btn_row.pack(fill="x", padx=14, pady=(8, 6))

    def safe_status(msg: str) -> None:
        root.after(0, lambda m=msg: status_var.set(m))

    def on_start_patrol() -> None:
        try:
            mi = float(main_iv_str.get().strip())
            fi = float(friend_iv_str.get().strip())
        except ValueError:
            _diag("gui", "patrol_start_invalid_input", "巡查间隔非数字", level="warn")
            messagebox.showerror("错误", "巡查间隔请填写数字。")
            return
        acts = {k: v.get() for k, v in steal_action_vars.items()}
        if not steal_master_var.get():
            acts = {k: False for k in acts}
        save_steal_feature_config(
            steal_master_var.get(),
            acts,
            mi,
            fi,
            friend_list_scroll_steps=0,
        )
        t = patrol_thread_holder[0]
        if t is not None and t.is_alive():
            _diag("gui", "patrol_already_running", "巡查已在运行", level="warn")
            messagebox.showinfo("提示", "巡查已在运行。")
            return
        patrol_stop_event.clear()
        _diag(
            "gui",
            "patrol_start",
            "用户启动自动巡查",
            main_interval_sec=mi,
            friend_interval_sec=fi,
            steal_master=steal_master_var.get(),
            steal_actions=acts,
        )

        sess_t0 = time.monotonic()

        def runner() -> None:
            patrol_loop_worker(
                patrol_stop_event,
                safe_status,
                session_start_monotonic=sess_t0,
            )

        th = threading.Thread(target=runner, daemon=True)
        patrol_thread_holder[0] = th
        th.start()
        status_var.set("自动巡查已启动。")

    def on_stop_patrol() -> None:
        patrol_stop_event.set()
        _diag("gui", "patrol_stop", "用户停止自动巡查（按钮或 F12）", level="info")
        status_var.set("已停止自动巡查。")

    f12_prev_down: List[bool] = [False]

    def poll_global_f12_stop() -> None:
        """巡查运行时轮询 F12（GetAsyncKeyState），游戏窗口在前台时也可停止，无需键盘钩子。"""
        if sys.platform == "win32":
            try:
                down = (ctypes.windll.user32.GetAsyncKeyState(0x7B) & 0x8000) != 0
            except Exception:
                down = False
            t = patrol_thread_holder[0]
            if t is not None and t.is_alive() and down and not f12_prev_down[0]:
                on_stop_patrol()
            f12_prev_down[0] = down
        root.after(55, poll_global_f12_stop)

    tk.Button(patrol_btn_row, text="开始自动巡查", width=14, command=on_start_patrol).pack(side="left", padx=(0, 10))
    tk.Button(patrol_btn_row, text="停止自动巡查 (F12)", width=16, command=on_stop_patrol).pack(side="left")

    def on_f12_stop(_event: object = None) -> str:
        on_stop_patrol()
        return "break"

    root.bind_all("<F12>", on_f12_stop)
    root.bind_all("<KeyPress-F12>", on_f12_stop)
    root.protocol("WM_DELETE_WINDOW", on_exit)
    poll_global_f12_stop()

    if not steal_master_var.get():
        for w in steal_cb_widgets:
            w.config(state=tk.DISABLED)

    if open_diag_console_scripts:
        _spawn_diagnostic_subprocesses(diag_subprocs)

    root.mainloop()

    _diag("app", "gui_mainloop_done", "主界面已关闭，约 1s 后结束诊断子进程", level="info")
    _shutdown_diagnostic_subprocesses(diag_subprocs, delay_sec=0.0)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="QQ 农场：锁定游戏截图区域。自动模式用于窗口常移动/改大小后反复重锁；手动模式用于首次或兜底。"
    )
    parser.add_argument(
        "--ref",
        default=None,
        help="自动锁定用的参考图路径；省略则在 assets/yinyong 中按规则选默认图（优先 窗口定位参考.png）。",
    )
    parser.add_argument("--threshold", type=float, default=0.7, help="模板匹配阈值，画面变化大时可试 0.55～0.65。")
    parser.add_argument(
        "--region-width",
        type=int,
        default=1280,
        help="期望游戏区宽度；与小参考图搭配时，自动锁定会以此尺寸在匹配中心周围框出整窗。",
    )
    parser.add_argument("--region-height", type=int, default=720, help="期望游戏区高度，含义同 --region-width。")
    parser.add_argument(
        "--auto-region-mode",
        choices=["match", "fixed"],
        default="match",
        help=(
            "match：优先用匹配到的矩形作区域，过小则自动改为以匹配中心+期望宽高框选；"
            "fixed：始终用期望宽高 centered on 匹配中心。一般保持 match 即可。"
        ),
    )
    parser.add_argument(
        "--save-preview",
        action="store_true",
        help="Save current game-region screenshot to assets/game_preview.png",
    )
    parser.add_argument(
        "--mode",
        choices=["gui", "auto", "manual"],
        default="gui",
        help="gui: show buttons; auto: run auto locate only; manual: run manual selection only.",
    )
    parser.add_argument(
        "--no-diag-consoles",
        action="store_true",
        help="GUI 模式下不尝试启动后台诊断子进程（写入仍由主程序内 diagnostic_logging 完成）。",
    )
    args = parser.parse_args()

    if args.mode == "gui":
        hide_console_on_windows()
        _diag_init()
        try:
            launch_gui(
                reference_image=args.ref,
                threshold=args.threshold,
                expected_region_size=(args.region_width, args.region_height),
                auto_region_mode=args.auto_region_mode,
                open_diag_console_scripts=not args.no_diag_consoles,
            )
        except Exception as exc:
            _diag(
                "app",
                "gui_launch_failed",
                str(exc),
                level="error",
                exc_type=type(exc).__name__,
            )
            try:
                err_root = tk.Tk()
                err_root.withdraw()
                messagebox.showerror(
                    "程序启动失败",
                    f"{type(exc).__name__}: {exc}\n\n可在文件夹地址栏输入 cmd 后执行：\npython game_region_locator.py",
                )
                err_root.destroy()
            except Exception:
                pass
            raise SystemExit(1) from exc
    elif args.mode == "auto":
        _diag_init()
        ref_path = args.ref
        if not ref_path:
            default_ref = get_default_reference_image()
            if not default_ref:
                raise FileNotFoundError(
                    "No PNG found in assets/yinyong/. Please pass --ref or add a reference PNG."
                )
            ref_path = str(default_ref)
            print(f"[AUTO] Using default reference image: {ref_path}")
        _diag("region", "cli_auto_locate", "命令行自动定位", ref_image=ref_path)
        region = acquire_game_region_auto(
            reference_image=ref_path,
            threshold=args.threshold,
            expected_region_size=(args.region_width, args.region_height),
            auto_region_mode=args.auto_region_mode,
        )
        _diag("region", "cli_auto_ok", "命令行自动定位成功", region=region)
        if args.save_preview:
            save_preview(str(ASSETS_ROOT / "game_preview.png"))
            print(f"[PREVIEW] Saved region screenshot to {ASSETS_ROOT / 'game_preview.png'} using {region}")
    else:
        _diag_init()
        _diag("region", "cli_manual_mode", "命令行：手动框取模式")
        region = acquire_game_region_manual()
        _diag("region", "cli_manual_ok", "命令行手动框取成功", region=region)
        if args.save_preview:
            save_preview(str(ASSETS_ROOT / "game_preview.png"))
            print(f"[PREVIEW] Saved region screenshot to {ASSETS_ROOT / 'game_preview.png'} using {region}")
