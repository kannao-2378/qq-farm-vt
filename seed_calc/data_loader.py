import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple


PROJECT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_LOCAL_GAME_CONFIG_DIR = PROJECT_DIR / "seed_calc" / "game_config"
DEFAULT_DESKTOP_GNA_GAME_CONFIG_DIR = Path.home() / "Desktop" / "gna" / "qq-farm-bot-main" / "core" / "src" / "gameConfig"
DEFAULT_DESKTOP_GAME_CONFIG_DIR = Path.home() / "Desktop" / "qq-farm-bot-main" / "core" / "src" / "gameConfig"


def locate_game_config_dir() -> Optional[Path]:
    for p in (
        DEFAULT_LOCAL_GAME_CONFIG_DIR,
        DEFAULT_DESKTOP_GNA_GAME_CONFIG_DIR,
        DEFAULT_DESKTOP_GAME_CONFIG_DIR,
    ):
        if (p / "Plant.json").is_file() and (p / "ItemInfo.json").is_file():
            return p
    return None


def load_game_config_json() -> Tuple[List[Dict], List[Dict]]:
    root = locate_game_config_dir()
    if root is None:
        return [], []
    try:
        plant_data = json.loads((root / "Plant.json").read_text(encoding="utf-8"))
    except Exception:
        plant_data = []
    try:
        item_data = json.loads((root / "ItemInfo.json").read_text(encoding="utf-8"))
    except Exception:
        item_data = []
    if not isinstance(plant_data, list):
        plant_data = []
    if not isinstance(item_data, list):
        item_data = []
    return plant_data, item_data
