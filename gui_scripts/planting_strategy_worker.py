import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from seed_calc.catalog import get_best_seed_for_level, get_level_available_seeds, get_optimal_seed_for_level
from seed_calc.data_loader import locate_game_config_dir


CONFIG_PATH = Path(__file__).resolve().parent / "planting_strategy_config.json"

STRATEGY_LEVEL_OPTIMAL = "根据当前等级筛选经验最优种子"
STRATEGY_PROFIT_OPTIMAL = "根据当前等级筛选利润最优种子"
STRATEGY_FERT_EXP_OPTIMAL = "根据当前等级筛选普肥经验最优种子"
STRATEGY_FERT_PROFIT_OPTIMAL = "根据当前等级筛选普肥利润最优种子"
STRATEGY_MANUAL = "自由选择种子"

STRATEGY_LABEL_TO_KEY: Dict[str, str] = {
    STRATEGY_LEVEL_OPTIMAL: "max_exp",
    STRATEGY_PROFIT_OPTIMAL: "max_profit",
    STRATEGY_FERT_EXP_OPTIMAL: "max_fert_exp",
    STRATEGY_FERT_PROFIT_OPTIMAL: "max_fert_profit",
    STRATEGY_MANUAL: "manual",
}

STRATEGY_OPTIONS: List[str] = [
    STRATEGY_LEVEL_OPTIMAL,
    STRATEGY_PROFIT_OPTIMAL,
    STRATEGY_FERT_EXP_OPTIMAL,
    STRATEGY_FERT_PROFIT_OPTIMAL,
    STRATEGY_MANUAL,
]

_LEVEL_CAP = 300


def load_planting_strategy_config() -> Dict[str, object]:
    if not CONFIG_PATH.exists():
        return {
            "strategy": STRATEGY_LEVEL_OPTIMAL,
            "manual_seed": "",
            "locked_seed": "",
            "mock_level": 1,
        }
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("invalid config")
        lv = int(data.get("mock_level", 1))
        lv = min(_LEVEL_CAP, max(1, lv))
        return {
            "strategy": str(data.get("strategy", STRATEGY_LEVEL_OPTIMAL)),
            "manual_seed": str(data.get("manual_seed", "")),
            "locked_seed": str(data.get("locked_seed", "")),
            "mock_level": lv,
        }
    except Exception:
        return {
            "strategy": STRATEGY_LEVEL_OPTIMAL,
            "manual_seed": "",
            "locked_seed": "",
            "mock_level": 1,
        }


def save_planting_strategy_config(
    strategy: str,
    manual_seed: str,
    locked_seed: str,
    mock_level: int,
) -> None:
    lv = min(_LEVEL_CAP, max(1, int(mock_level)))
    payload = {
        "strategy": str(strategy),
        "manual_seed": str(manual_seed),
        "locked_seed": str(locked_seed),
        "mock_level": lv,
    }
    CONFIG_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def get_current_level() -> int:
    cfg = load_planting_strategy_config()
    return int(cfg.get("mock_level", 1))


def resolve_seed_by_strategy(strategy: str, manual_seed: str, level: int) -> str:
    key = STRATEGY_LABEL_TO_KEY.get(strategy, "max_exp")
    if key == "manual":
        available = get_level_available_seeds(level)
        if manual_seed in available:
            return manual_seed
        return available[0] if available else ""
    best = get_best_seed_for_level(level, key)
    return best or ""


def get_strategy_key(strategy_label: str) -> str:
    return STRATEGY_LABEL_TO_KEY.get(strategy_label, "max_exp")


def get_strategy_best_seed(level: int, strategy_label: str) -> Optional[str]:
    key = get_strategy_key(strategy_label)
    if key == "manual":
        return None
    return get_best_seed_for_level(level, key) or get_optimal_seed_for_level(level)


def main() -> int:
    parser = argparse.ArgumentParser(description="种植策略脚本（种子/等级计算）。")
    parser.add_argument("--show", action="store_true", help="输出当前策略与选种结果。")
    parser.add_argument("--check-data", action="store_true", help="检查种子配置来源路径。")
    args = parser.parse_args()
    if args.check_data:
        p = locate_game_config_dir()
        print(f"game_config_dir={p if p else 'NOT_FOUND'}")
        return 0
    if not args.show:
        return 0
    cfg = load_planting_strategy_config()
    level = get_current_level()
    seed = resolve_seed_by_strategy(
        strategy=str(cfg.get("strategy", STRATEGY_LEVEL_OPTIMAL)),
        manual_seed=str(cfg.get("manual_seed", "")),
        level=level,
    )
    print(f"level={level}, strategy={cfg.get('strategy')}, seed={seed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
