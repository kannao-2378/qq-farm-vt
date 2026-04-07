# -*- coding: utf-8 -*-
"""
一次性整理：将 assets 下文件按代码是否可能引用分为
  - assets/yinyong/  模板与样图（game_region_locator 会读）
  - assets/cs/       当前工程 Python 未引用的 PNG（如种植辅助标记图、叠加示意图）

规则与 game_region_locator 中的文件名/目录名一致；不确定的目录整夹放到 yinyong 并打印 NOTE。
根目录保留：app_icon.ico、donation_qr.png、game_preview.png、cao2.png（若存在）。

用法（项目根）: py -3 scripts/classify_assets_move.py
加 --dry-run 只打印不移动。
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
YINYONG = ASSETS / "yinyong"
CS = ASSETS / "cs"

STAY_ROOT_FILES = frozenset(
    {"app_icon.ico", "donation_qr.png", "game_preview.png", "cao2.png"}
)

# 窗口参考图文件名（与 game_region_locator.get_default_reference_image 一致）
REF_PNG_NAMES = frozenset(
    {
        "窗口定位参考.png",
        "游戏窗口参考.png",
        "window_reference.png",
        "game_region_ref.png",
        "reference.png",
    }
)


def _png_role(rel: Path) -> str:
    """返回 'yinyong' | 'cs' | 'stay'。"""
    parts = rel.parts
    path_s = "/".join(parts)
    name = rel.name

    if len(parts) == 1 and name in STAY_ROOT_FILES:
        return "stay"
    if not name.lower().endswith(".png"):
        return "stay"  # 非 png 由目录阶段或根文件阶段单独处理

    if "主界面按钮区域确认样图" in path_s:
        return "yinyong"
    if "种植" in path_s:
        return "cs"

    if name in REF_PNG_NAMES:
        return "yinyong"
    if any(k in name for k in ("主界面", "偷菜", "拜访", "好友农场")):
        return "yinyong"
    if "红框" in name and ("偷菜" in name or "好友农场" in name or "拜访" in name):
        return "yinyong"
    # 根目录 PNG：工程内未引用、仅作人工标注的叠加图（ASCII 名）
    if len(parts) == 1 and (name.startswith("planting_") and name.endswith(".png")):
        return "cs"
    # 其余根目录 PNG 一律进 yinyong（含 GBK 乱码文件名，避免误判进 cs 导致脚本找不到模板）
    if len(parts) == 1:
        return "yinyong"
    return "cs"


def _ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def _move_file(src: Path, dest: Path, dry: bool) -> None:
    _ensure_dir(dest.parent)
    if dest.exists():
        if dest.resolve() == src.resolve():
            return
        print(f"[skip exists] {dest}", file=sys.stderr)
        return
    print(f"MOVE {src} -> {dest}")
    if not dry:
        shutil.move(str(src), str(dest))


def _move_tree_merge(src_dir: Path, dest_dir: Path, dry: bool) -> None:
    """将 src_dir 合并进 dest_dir（dest 已存在时只搬文件）。"""
    if not src_dir.is_dir():
        return
    if not dest_dir.exists():
        print(f"MOVE DIR {src_dir} -> {dest_dir}")
        if not dry:
            _ensure_dir(dest_dir.parent)
            shutil.move(str(src_dir), str(dest_dir))
        return
    for p in sorted(src_dir.rglob("*"), key=lambda x: len(x.parts)):
        if not p.is_file():
            continue
        rel = p.relative_to(src_dir)
        target = dest_dir / rel
        _move_file(p, target, dry)
    # 删空目录
    if not dry:
        for p in sorted(src_dir.rglob("*"), reverse=True, key=lambda x: len(x.parts)):
            if p.is_dir():
                try:
                    p.rmdir()
                except OSError:
                    pass
        try:
            src_dir.rmdir()
        except OSError:
            print(f"[warn] could not remove empty dir {src_dir}", file=sys.stderr)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    dry = bool(args.dry_run)

    if not ASSETS.is_dir():
        print("No assets directory", file=sys.stderr)
        return 1

    _ensure_dir(YINYONG)
    _ensure_dir(CS)

    # 1) 顶层目录（除 yinyong / cs）
    for child in sorted(ASSETS.iterdir(), key=lambda x: x.name):
        if not child.is_dir():
            continue
        if child.name in ("yinyong", "cs"):
            continue
        nm = child.name
        if "主界面按钮区域确认样图" in nm or "偷菜" in nm or "好友农场" in nm:
            _move_tree_merge(child, YINYONG / nm, dry)
        elif "种植" in nm:
            _move_tree_merge(child, CS / nm, dry)
        else:
            print(f"NOTE: unknown top folder -> yinyong: {nm}")
            _move_tree_merge(child, YINYONG / nm, dry)

    # 2) 顶层 PNG（模板或试验图）
    for child in sorted(ASSETS.iterdir(), key=lambda x: x.name):
        if not child.is_file():
            continue
        if child.name in STAY_ROOT_FILES:
            continue
        if child.suffix.lower() != ".png":
            continue
        rel = child.relative_to(ASSETS)
        role = _png_role(rel)
        if role == "stay":
            continue
        dest = (YINYONG if role == "yinyong" else CS) / child.name
        _move_file(child, dest, dry)

    print("Done." + (" (dry-run)" if dry else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
