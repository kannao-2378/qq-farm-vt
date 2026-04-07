from dataclasses import dataclass
from typing import Dict, List, Optional

from .data_loader import load_game_config_json


@dataclass
class SeedEntry:
    seed_id: int
    plant_id: int
    fruit_id: int
    name: str
    required_level: int
    exp: float
    grow_seconds: float
    price: float
    fruit_count: float
    income: float
    net_profit: float
    exp_per_hour: float
    profit_per_hour: float
    fert_exp_per_hour: float
    fert_profit_per_hour: float


_seed_catalog_cache: Optional[List[SeedEntry]] = None


def _parse_grow_seconds(grow_phases: str, seasons: int) -> float:
    if not grow_phases:
        return 0.0
    durations: List[float] = []
    for seg in str(grow_phases).split(";"):
        seg = seg.strip()
        if not seg or ":" not in seg:
            continue
        try:
            sec_text = seg.split(":", 1)[1]
            durations.append(float(sec_text))
        except Exception:
            continue
    if not durations:
        return 0.0
    total = float(sum(durations))
    if int(seasons) != 2:
        return total
    # 对齐 gna：两季 = 总时长 + 最后两段非零阶段
    non_zero = [d for d in durations if d > 0]
    extra = sum(non_zero[-2:]) if non_zero else 0.0
    return total + float(extra)


def _parse_normal_fertilizer_reduce_sec(grow_phases: str, seasons: int) -> float:
    durations: List[float] = []
    for seg in str(grow_phases).split(";"):
        seg = seg.strip()
        if not seg or ":" not in seg:
            continue
        try:
            sec_text = seg.split(":", 1)[1]
            v = float(sec_text)
        except Exception:
            continue
        if v > 0:
            durations.append(v)
    if not durations:
        return 0.0
    max_d = max(durations)
    apply_count = 2 if int(seasons) == 2 else 1
    return float(max_d * apply_count)


def _build_seed_catalog() -> List[SeedEntry]:
    plants, items = load_game_config_json()
    if not plants or not items:
        return []

    seed_price_map: Dict[int, float] = {}
    item_price_map: Dict[int, float] = {}
    for row in items:
        try:
            item_type = int(row.get("type", 0))
            item_id = int(row.get("id", 0))
            price = float(row.get("price", 0))
        except Exception:
            continue
        if item_id > 0:
            item_price_map[item_id] = price
        if item_type == 5 and item_id > 0:
            seed_price_map[item_id] = price

    out: List[SeedEntry] = []
    for p in plants:
        try:
            seed_id = int(p.get("seed_id", 0))
            if seed_id <= 0:
                continue
            plant_id = int(p.get("id", 0))
            name = str(p.get("name", "")).strip() or "未知种子"
            required_level = int(p.get("land_level_need", 0))
            base_exp = float(p.get("exp", 0))
            seasons = int(p.get("seasons", 1))
            grow_seconds = _parse_grow_seconds(str(p.get("grow_phases", "")), seasons)
            if grow_seconds <= 0:
                continue
            fruit = p.get("fruit", {}) if isinstance(p.get("fruit", {}), dict) else {}
            fruit_id = int(fruit.get("id", 0))
            base_fruit_count = float(fruit.get("count", 0))
            price = float(seed_price_map.get(seed_id, 0.0))
            # 对齐 gna：果实价格直接用 itemInfoMap 以 fruit_id 查询，不限制 item type
            fruit_price = float(item_price_map.get(fruit_id, 0.0))
            # 对齐 gna：两季时经验与收益均按 2 倍计算
            exp = base_exp * (2.0 if seasons == 2 else 1.0)
            fruit_count = base_fruit_count * (2.0 if seasons == 2 else 1.0)
            income = fruit_count * fruit_price
            net_profit = income - price
            exp_per_hour = exp * 3600.0 / grow_seconds
            profit_per_hour = net_profit * 3600.0 / grow_seconds
            reduce_sec = _parse_normal_fertilizer_reduce_sec(str(p.get("grow_phases", "")), seasons)
            fert_seconds = max(1.0, grow_seconds - reduce_sec)
            fert_exp_per_hour = exp * 3600.0 / fert_seconds
            fert_profit_per_hour = net_profit * 3600.0 / fert_seconds
            out.append(
                SeedEntry(
                    seed_id=seed_id,
                    plant_id=plant_id,
                    fruit_id=fruit_id,
                    name=name,
                    required_level=required_level,
                    exp=exp,
                    grow_seconds=grow_seconds,
                    price=price,
                    fruit_count=fruit_count,
                    income=income,
                    net_profit=net_profit,
                    exp_per_hour=exp_per_hour,
                    profit_per_hour=profit_per_hour,
                    fert_exp_per_hour=fert_exp_per_hour,
                    fert_profit_per_hour=fert_profit_per_hour,
                )
            )
        except Exception:
            continue

    out.sort(key=lambda x: (x.required_level, -x.exp_per_hour, x.seed_id))
    return out


def get_seed_catalog(force_reload: bool = False) -> List[SeedEntry]:
    global _seed_catalog_cache
    if _seed_catalog_cache is None or force_reload:
        _seed_catalog_cache = _build_seed_catalog()
    return list(_seed_catalog_cache)


def get_level_available_seeds(level: int) -> List[str]:
    lv = max(1, int(level))
    rows = [x.name for x in get_seed_catalog() if lv >= x.required_level]
    return rows


def get_optimal_seed_for_level(level: int) -> Optional[str]:
    lv = max(1, int(level))
    candidates = [x for x in get_seed_catalog() if lv >= x.required_level]
    if not candidates:
        return None
    best = max(candidates, key=lambda x: (x.exp_per_hour, x.exp, -x.price))
    return best.name


def get_best_seed_for_level(level: int, strategy_key: str) -> Optional[str]:
    lv = max(1, int(level))
    candidates = [x for x in get_seed_catalog() if lv >= x.required_level]
    if not candidates:
        return None
    if strategy_key == "max_profit":
        best = max(candidates, key=lambda x: (x.profit_per_hour, x.net_profit, -x.price))
    elif strategy_key == "max_fert_exp":
        best = max(candidates, key=lambda x: (x.fert_exp_per_hour, x.exp_per_hour, x.exp))
    elif strategy_key == "max_fert_profit":
        best = max(candidates, key=lambda x: (x.fert_profit_per_hour, x.profit_per_hour, x.net_profit))
    else:
        best = max(candidates, key=lambda x: (x.exp_per_hour, x.exp, -x.price))
    return best.name
