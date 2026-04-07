#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
QQ 农场控制台 — PyQt6：顶行 游戏窗口识别|任务控制，次行 主界面|好友，底行 种植|统计列；
初始约 730×690、最小 730×600。无边框窗 + 自定义标题栏 52px + 双主题 QSS。

运行: 双击根目录「启动.bat」，或: python gui_scripts/new_main_pyqt.py（项目根为工作目录时）
主题偏好：项目根目录 user_data/qt_ui_prefs.json。Windows 下默认隐藏本进程控制台；亦可用 pythonw。
"""

from __future__ import annotations

import ctypes
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

def _hide_console_on_windows() -> None:
    """前台不显示 CMD 黑窗（Windows）。"""
    if sys.platform != "win32":
        return
    try:
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 0)  # SW_HIDE
    except Exception:
        pass


# 项目根目录（本文件在 gui_scripts/ 下）
_ROOT = Path(__file__).resolve().parent.parent
APP_ICON_PATH = _ROOT / "assets" / "app_icon.ico"
if str(_ROOT / "gui_scripts") not in sys.path:
    sys.path.insert(0, str(_ROOT / "gui_scripts"))

import control_center_core as ccc
from game_region_locator import (
    MAIN_INTERFACE_PATROL_TEMPLATE_THRESHOLD,
    PATROL_MIN_FRIEND_INTERVAL_SEC,
    PATROL_MIN_MAIN_INTERVAL_SEC,
    STEAL_UI_MATCH_THRESHOLD,
    load_main_interface_actions_enabled,
    load_steal_feature_config,
    save_main_interface_actions_enabled,
    save_steal_feature_config,
)
from planting_strategy_worker import (
    STRATEGY_FERT_EXP_OPTIMAL,
    STRATEGY_FERT_PROFIT_OPTIMAL,
    STRATEGY_LEVEL_OPTIMAL,
    STRATEGY_MANUAL,
    STRATEGY_OPTIONS,
    STRATEGY_PROFIT_OPTIMAL,
    get_current_level,
    get_level_available_seeds,
    get_optimal_seed_for_level,
    get_strategy_best_seed,
    load_planting_strategy_config,
    save_planting_strategy_config,
)
from qt_control_center_engine import QtControlCenterEngine, TaskUIState
from task_click_stats import read_stats, reset_all_stats

import donation_dialog
import donation_dialog_qt

from PyQt6.QtCore import QObject, QPoint, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QFont,
    QIcon,
    QIntValidator,
    QKeySequence,
    QMouseEvent,
    QShortcut,
)
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFrame,
    QGraphicsDropShadowEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

# 外边距、圆角按钮尺寸（与历史 Tk 版对齐）
UI_PAD = 8
BTN_W = 100
BTN_H = 34
# 每个功能区块（卡片列）固定宽度（原约 338px，现 320px）
SECTION_BOX_WIDTH = 320
# 「任务统计」卡片固定高度
TASK_STATS_CARD_HEIGHT = 254
# 各区块（卡片）之间的间距（水平与垂直）
BOX_SPACING = 30
# 卡片内：文字/控件与卡片边框（含圆角内侧）的边距
SECTION_INNER_PAD = 15

# PyQt 界面偏好（与代码分离，便于根目录只保留启动/依赖/说明）
_PYQT_UI_PREFS = _ROOT / "user_data" / "qt_ui_prefs.json"


def _migrate_legacy_user_files() -> None:
    """把旧版根目录下的 qt_ui_prefs.json 迁到 user_data/。"""
    if _PYQT_UI_PREFS.is_file():
        return
    legacy = _ROOT / "qt_ui_prefs.json"
    if not legacy.is_file():
        return
    try:
        _PYQT_UI_PREFS.parent.mkdir(parents=True, exist_ok=True)
        _PYQT_UI_PREFS.write_bytes(legacy.read_bytes())
    except OSError:
        pass


def _load_dark_theme_pref() -> bool:
    """读取上次保存的深色主题；无文件或解析失败时默认深色。"""
    try:
        if _PYQT_UI_PREFS.is_file():
            data = json.loads(_PYQT_UI_PREFS.read_text(encoding="utf-8"))
            return bool(data.get("dark_theme", True))
    except Exception:
        pass
    return True


# ---------------------------------------------------------------------------
# QSS（浅色 / 深色）
# ---------------------------------------------------------------------------

QSS_LIGHT = """
QMainWindow, QWidget#BodyRoot {
    background-color: #F5F5F5;
    color: #000000;
}
QFrame#Hairline {
    background-color: #E8E8E8;
    max-height: 1px;
    min-height: 1px;
    border: none;
}
QFrame#SectionCard {
    background-color: #FFFFFF;
    border: 1px solid #E0E0E0;
    border-radius: 8px;
}
QLabel#SectionTitle {
    color: #000000;
    font-weight: bold;
    font-size: 13px;
}
QLabel { color: #000000; background-color: transparent; }
QLabel#StatCaption { color: #000000; font-size: 13px; }
QLabel#StatValue { color: #07C160; font-weight: bold; font-size: 18px; }
QLabel#HintLabel { color: #888888; font-size: 12px; }
QCheckBox { color: #000000; spacing: 6px; background-color: transparent; }
QCheckBox::indicator {
    width: 16px; height: 16px; border-radius: 3px;
    border: 1px solid #CCCCCC; background: #FFFFFF;
}
QCheckBox::indicator:checked {
    border: 1px solid #07C160; background-color: #07C160;
}
QLineEdit {
    background-color: #FFFFFF; color: #000000;
    border: 1px solid #DDDDDD; border-radius: 4px;
    padding: 5px 8px; min-height: 18px;
}
QComboBox {
    background-color: #FFFFFF; color: #000000;
    border: 1px solid #DDDDDD; border-radius: 4px;
    padding: 5px 8px; min-height: 18px;
}
QComboBox::drop-down { border: none; width: 22px; }
QComboBox QAbstractItemView {
    background: #FFFFFF; color: #000000; border: 1px solid #DDDDDD;
    selection-background-color: #07C160; selection-color: #FFFFFF;
}
QPushButton#BtnPrimary {
    background-color: #07C160; color: #FFFFFF; border: none;
    border-radius: 4px; padding: 0px; font-weight: bold;
    min-width: 100px; max-width: 100px; min-height: 34px; max-height: 34px;
}
QPushButton#BtnPrimary:hover { background-color: #06AD56; }
QPushButton#BtnStop {
    background-color: #DC3545; color: #FFFFFF; border: none;
    border-radius: 4px; padding: 0px; font-weight: bold;
    min-width: 100px; max-width: 100px; min-height: 34px; max-height: 34px;
}
QPushButton#BtnStop:hover { background-color: #C82333; }
QPushButton#BtnSecondary {
    background-color: #F2F2F2; color: #000000;
    border: 1px solid #DDDDDD; border-radius: 4px;
    padding: 0px;
    min-width: 100px; max-width: 100px; min-height: 34px; max-height: 34px;
}
QPushButton#BtnSecondary:hover { background-color: #E6E6E6; }
QPushButton#BtnSecondaryWide {
    background-color: #F2F2F2; color: #000000;
    border: 1px solid #DDDDDD; border-radius: 4px;
    padding: 0px;
    min-width: 120px; max-width: 120px; min-height: 34px; max-height: 34px;
}
QPushButton#BtnSecondaryWide:hover { background-color: #E6E6E6; }
QPushButton#TitleBarTheme {
    background-color: transparent; color: inherit;
    border: 1px solid #CCCCCC; border-radius: 4px;
    min-width: 44px; max-width: 44px; min-height: 26px; max-height: 26px;
    font-size: 11px;
}
QPushButton#TitleBarTheme:hover { background-color: #E8E8E8; }
QStatusBar {
    background-color: #EEEEEE; color: #333333;
    border-top: 1px solid #E0E0E0;
}
"""

QSS_DARK = """
QMainWindow, QWidget#BodyRoot {
    background-color: #1E1E1E;
    color: #F0F0F0;
}
QFrame#Hairline {
    background-color: #3C3C3C;
    max-height: 1px;
    min-height: 1px;
    border: none;
}
QFrame#SectionCard {
    background-color: #2D2D2D;
    border: 1px solid #3C3C3C;
    border-radius: 8px;
}
QLabel#SectionTitle { color: #F0F0F0; font-weight: bold; font-size: 13px; }
QLabel { color: #F0F0F0; background-color: transparent; }
QLabel#StatCaption { color: #F0F0F0; font-size: 13px; }
QLabel#StatValue { color: #07C160; font-weight: bold; font-size: 18px; }
QLabel#HintLabel { color: #AAAAAA; font-size: 12px; }
QCheckBox { color: #F0F0F0; spacing: 6px; background-color: transparent; }
QCheckBox::indicator {
    width: 16px; height: 16px; border-radius: 3px;
    border: 1px solid #666666; background: #3C3C3C;
}
QCheckBox::indicator:checked {
    border: 1px solid #07C160; background-color: #07C160;
}
QLineEdit {
    background-color: #3C3C3C; color: #F0F0F0;
    border: 1px solid #555555; border-radius: 4px;
    padding: 5px 8px; min-height: 18px;
}
QComboBox {
    background-color: #3C3C3C; color: #F0F0F0;
    border: 1px solid #555555; border-radius: 4px;
    padding: 5px 8px; min-height: 18px;
}
QComboBox::drop-down { border: none; width: 22px; }
QComboBox QAbstractItemView {
    background: #2D2D2D; color: #F0F0F0; border: 1px solid #555555;
    selection-background-color: #07C160; selection-color: #FFFFFF;
}
QPushButton#BtnPrimary {
    background-color: #07C160; color: #FFFFFF; border: none;
    border-radius: 4px; padding: 0px; font-weight: bold;
    min-width: 100px; max-width: 100px; min-height: 34px; max-height: 34px;
}
QPushButton#BtnPrimary:hover { background-color: #06AD56; }
QPushButton#BtnStop {
    background-color: #DC3545; color: #FFFFFF; border: none;
    border-radius: 4px; padding: 0px; font-weight: bold;
    min-width: 100px; max-width: 100px; min-height: 34px; max-height: 34px;
}
QPushButton#BtnStop:hover { background-color: #C82333; }
QPushButton#BtnSecondary {
    background-color: #3C3C3C; color: #F0F0F0;
    border: 1px solid #555555; border-radius: 4px;
    padding: 0px;
    min-width: 100px; max-width: 100px; min-height: 34px; max-height: 34px;
}
QPushButton#BtnSecondary:hover { background-color: #4A4A4A; }
QPushButton#BtnSecondaryWide {
    background-color: #3C3C3C; color: #F0F0F0;
    border: 1px solid #555555; border-radius: 4px;
    padding: 0px;
    min-width: 120px; max-width: 120px; min-height: 34px; max-height: 34px;
}
QPushButton#BtnSecondaryWide:hover { background-color: #4A4A4A; }
QPushButton#TitleBarTheme {
    background-color: transparent; color: #F0F0F0;
    border: 1px solid #555555; border-radius: 4px;
    min-width: 44px; max-width: 44px; min-height: 26px; max-height: 26px;
    font-size: 11px;
}
QPushButton#TitleBarTheme:hover { background-color: #3C3C3C; }
QStatusBar {
    background-color: #252525; color: #F0F0F0;
    border-top: 1px solid #3C3C3C;
}
"""


class TitleBar(QWidget):
    """标题栏 52px：「QQ 农场」、主题切换、最小化/关闭。"""

    def __init__(self, main_window: QMainWindow) -> None:
        super().__init__(main_window)
        self.setObjectName("TitleBar")
        self._main = main_window
        self._drag_pos: Optional[QPoint] = None
        self.setFixedHeight(52)

        self._lbl_title = QLabel("QQ 农场")
        self._lbl_title.setObjectName("TitleBarText")
        self._lbl_title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        self._btn_theme = QPushButton("主题")
        self._btn_theme.setObjectName("TitleBarTheme")

        def _toggle_theme() -> None:
            mw = self._main
            if hasattr(mw, "_toggle_theme"):
                mw._toggle_theme()

        self._btn_theme.clicked.connect(_toggle_theme)

        self._btn_min = QPushButton("\u2212")
        self._btn_min.setObjectName("TitleBarButton")
        self._btn_min.setFixedSize(40, 28)
        self._btn_min.clicked.connect(self._main.showMinimized)

        self._btn_close = QPushButton("\u2715")
        self._btn_close.setObjectName("TitleBarButtonClose")
        self._btn_close.setFixedSize(40, 28)
        self._btn_close.clicked.connect(self._on_close)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 0, 8, 0)
        lay.setSpacing(8)
        lay.addWidget(self._lbl_title)
        lay.addStretch()
        lay.addWidget(self._btn_theme)
        lay.addWidget(self._btn_min)
        lay.addWidget(self._btn_close)

    def apply_theme(self, dark: bool) -> None:
        if dark:
            self.setStyleSheet(
                """
                QWidget#TitleBar {
                    background-color: #2D2D2D;
                    border-bottom: 1px solid #3C3C3C;
                }
                QLabel#TitleBarText {
                    color: #F0F0F0;
                    font-size: 14px;
                    font-weight: bold;
                    background: transparent;
                }
                QPushButton#TitleBarButton, QPushButton#TitleBarButtonClose {
                    background-color: transparent;
                    color: #F0F0F0;
                    border: none;
                    border-radius: 4px;
                    font-size: 16px;
                }
                QPushButton#TitleBarButton:hover, QPushButton#TitleBarButtonClose:hover {
                    background-color: #3C3C3C;
                }
                QPushButton#TitleBarButtonClose:hover {
                    background-color: #C82333;
                    color: #FFFFFF;
                }
                """
            )
        else:
            self.setStyleSheet(
                """
                QWidget#TitleBar {
                    background-color: #FFFFFF;
                    border-bottom: 1px solid #E8E8E8;
                }
                QLabel#TitleBarText {
                    color: #000000;
                    font-size: 14px;
                    font-weight: bold;
                    background: transparent;
                }
                QPushButton#TitleBarButton, QPushButton#TitleBarButtonClose {
                    background-color: transparent;
                    color: #000000;
                    border: none;
                    border-radius: 4px;
                    font-size: 16px;
                }
                QPushButton#TitleBarButton:hover, QPushButton#TitleBarButtonClose:hover {
                    background-color: #E8E8E8;
                }
                QPushButton#TitleBarButtonClose:hover {
                    background-color: #DC3545;
                    color: #FFFFFF;
                }
                """
            )

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self._main.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_pos is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self._main.move(event.globalPosition().toPoint() - self._drag_pos)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._drag_pos = None
        super().mouseReleaseEvent(event)

    def _on_close(self) -> None:
        w = self._main
        if isinstance(w, FarmAssistantWindow) and w._engine.is_loop_running():
            w._engine.stop_loop()
        QApplication.quit()


class _UiBridge(QObject):
    status_msg = pyqtSignal(str, bool)


class FarmAssistantWindow(QMainWindow):
    """顶行「游戏窗口识别|任务控制」、次行「主界面|好友」、底行「种植|统计列」。"""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("QQ 农场")
        if APP_ICON_PATH.is_file():
            self.setWindowIcon(QIcon(str(APP_ICON_PATH)))
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        # 两列 320 + BOX_SPACING + 外边距：约 730 宽
        self.resize(730, 690)
        self.setMinimumSize(730, 600)

        self._dark_mode = _load_dark_theme_pref()
        self._section_cards: List[QFrame] = []
        self._card_shadows: List[QGraphicsDropShadowEffect] = []
        self._f12_down_prev = False

        self.menuBar().hide()

        self._bridge = _UiBridge(self)
        self._bridge.status_msg.connect(self._on_engine_status)
        self._engine = QtControlCenterEngine(
            on_status=lambda m, e: self._bridge.status_msg.emit(m, e),
        )

        self._planting_level = int(get_current_level())
        self._main_act_cbs: Dict[str, QCheckBox] = {}
        self._friend_act_cbs: Dict[str, QCheckBox] = {}

        self._title_bar = TitleBar(self)
        self._build_ui()
        self._build_shortcuts()

        self._load_config_into_widgets()
        self._append_log("控制台已就绪（PyQt6，运行记录见 logs/control_center.log）。")

        self._stats_timer = QTimer(self)
        self._stats_timer.timeout.connect(self._refresh_task_stats)
        self._stats_timer.start(800)

        self._usage_acc_timer = QTimer(self)
        self._usage_acc_timer.timeout.connect(donation_dialog.accumulate_usage_tick)
        self._usage_acc_timer.start(10_000)
        donation_dialog.start_usage_session_clock()

        if sys.platform == "win32":
            self._f12_poll = QTimer(self)
            self._f12_poll.timeout.connect(self._poll_f12_key_state)
            self._f12_poll.start(120)

        self._apply_theme(initial=True)
        if not _PYQT_UI_PREFS.is_file():
            self._save_theme_prefs()

    def _center_and_snap_to_content(self) -> None:
        """对齐 Tk _snap_window_to_content：至少 730×600，按内容收紧高度。"""
        self.adjustSize()
        screen = QApplication.primaryScreen().availableGeometry()
        fg = self.frameGeometry()
        fg.moveCenter(screen.center())
        self.move(fg.topLeft())
        w = max(730, self.width())
        h = max(600, self.height())
        self.resize(w, h)

    def _append_log(self, line: str) -> None:
        ccc._write_control_center_log(line)

    def _status_suffix(self) -> str:
        return "  |  F12：停止任务  |  " + ("深色" if self._dark_mode else "浅色") + " 主题"

    def _on_engine_status(self, msg: str, error: bool) -> None:
        p = "错误：" if error else ""
        self.statusBar().showMessage(p + msg + self._status_suffix(), 15000 if error else 8000)

    def _make_section(self, title: str) -> Tuple[QWidget, QVBoxLayout]:
        """区块标题在卡片内顶部；内边距为 SECTION_INNER_PAD（文字/控件距边框 15px）。"""
        wrap = QWidget()
        outer = QVBoxLayout(wrap)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        card = QFrame()
        card.setObjectName("SectionCard")
        inner = QVBoxLayout(card)
        inner.setContentsMargins(SECTION_INNER_PAD, SECTION_INNER_PAD, SECTION_INNER_PAD, SECTION_INNER_PAD)
        inner.setSpacing(SECTION_INNER_PAD)

        ttl = QLabel(title)
        ttl.setObjectName("SectionTitle")
        f = QFont(ttl.font())
        f.setBold(True)
        f.setPointSize(11)
        ttl.setFont(f)
        inner.addWidget(ttl)

        outer.addWidget(card)
        self._section_cards.append(card)
        wrap.setFixedWidth(SECTION_BOX_WIDTH)
        return wrap, inner

    def _h(self, sp: int = UI_PAD) -> QHBoxLayout:
        h = QHBoxLayout()
        h.setSpacing(sp)
        h.setContentsMargins(0, 0, 0, 0)
        return h

    def _stat_subheading(self, text: str) -> QLabel:
        lab = QLabel(text)
        f = QFont(lab.font())
        f.setBold(True)
        f.setPointSize(10)
        lab.setFont(f)
        return lab

    def _save_theme_prefs(self) -> None:
        try:
            _PYQT_UI_PREFS.write_text(
                json.dumps({"dark_theme": self._dark_mode}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass

    def _apply_theme(self, initial: bool = False) -> None:
        self.setStyleSheet(QSS_DARK if self._dark_mode else QSS_LIGHT)
        self._title_bar.apply_theme(self._dark_mode)
        self.statusBar().showMessage("就绪" + self._status_suffix())
        self._refresh_section_shadows()
        if not initial:
            print(f"[theme] {'深色' if self._dark_mode else '浅色'}")

    def _refresh_section_shadows(self) -> None:
        for eff in self._card_shadows:
            eff.setEnabled(False)
            eff.deleteLater()
        self._card_shadows.clear()
        blur = 12 if self._dark_mode else 14
        off = 1 if self._dark_mode else 2
        c = QColor(0, 0, 0, 40 if self._dark_mode else 28)
        for card in self._section_cards:
            eff = QGraphicsDropShadowEffect(self)
            eff.setBlurRadius(float(blur))
            eff.setOffset(float(off), float(off))
            eff.setColor(c)
            card.setGraphicsEffect(eff)
            self._card_shadows.append(eff)

    def _toggle_theme(self) -> None:
        self._dark_mode = not self._dark_mode
        self._save_theme_prefs()
        self._apply_theme(initial=False)

    # --- 配置 -----------------------------------------------------------------
    def _load_config_into_widgets(self) -> None:
        steal_cfg = load_steal_feature_config()
        acts = load_main_interface_actions_enabled()

        self.chk_enable_main.blockSignals(True)
        for cb in self._main_act_cbs.values():
            cb.blockSignals(True)
        self.chk_enable_friend.blockSignals(True)
        for cb in self._friend_act_cbs.values():
            cb.blockSignals(True)
        self.le_main_threshold.blockSignals(True)
        self.le_friend_threshold.blockSignals(True)

        for name, cb in self._main_act_cbs.items():
            cb.setChecked(bool(acts.get(name, False)))

        self.le_main_interval.setText(
            str(max(PATROL_MIN_MAIN_INTERVAL_SEC, float(steal_cfg.get("main_patrol_interval_sec", 0.0))))
        )
        self.le_main_threshold.setText(
            f"{float(steal_cfg.get('main_patrol_threshold', MAIN_INTERFACE_PATROL_TEMPLATE_THRESHOLD)):.2f}"
        )
        self.le_friend_interval.setText(
            str(max(PATROL_MIN_FRIEND_INTERVAL_SEC, float(steal_cfg.get("friend_patrol_interval_sec", 0.0))))
        )
        self.le_friend_threshold.setText(
            f"{float(steal_cfg.get('friend_patrol_threshold', STEAL_UI_MATCH_THRESHOLD)):.2f}"
        )
        self.chk_enable_friend.setChecked(bool(steal_cfg.get("master_enabled", False)))
        fac = steal_cfg.get("actions") or {}
        for name, cb in self._friend_act_cbs.items():
            cb.setChecked(bool(fac.get(name, False)))

        self.chk_enable_main.blockSignals(False)
        for cb in self._main_act_cbs.values():
            cb.blockSignals(False)
        self.chk_enable_friend.blockSignals(False)
        for cb in self._friend_act_cbs.values():
            cb.blockSignals(False)
        self.le_main_threshold.blockSignals(False)
        self.le_friend_threshold.blockSignals(False)

        self._sync_main_actions_state()
        self._sync_friend_actions_state()

        pcfg = load_planting_strategy_config()
        self._planting_level = int(pcfg.get("mock_level", get_current_level()))
        self.le_planting_level.setText(str(self._planting_level))

        strat = str(pcfg.get("strategy", STRATEGY_LEVEL_OPTIMAL)).strip()
        self.combo_strategy.blockSignals(True)
        self.combo_strategy.clear()
        self.combo_strategy.addItems(STRATEGY_OPTIONS)
        if strat in STRATEGY_OPTIONS:
            self.combo_strategy.setCurrentIndex(STRATEGY_OPTIONS.index(strat))
        else:
            self.combo_strategy.setCurrentIndex(0)
        self.combo_strategy.blockSignals(False)

        manual = str(pcfg.get("manual_seed", "")).strip()
        self.combo_seed.blockSignals(True)
        self.combo_seed.clear()
        if manual:
            self.combo_seed.addItem(manual)
            self.combo_seed.setCurrentIndex(0)
        self.combo_seed.blockSignals(False)

        self._refresh_planting_seed_combo(save=False)

    def _parse_thresholds_from_ui(self) -> Optional[Tuple[float, float]]:
        try:
            return (
                max(0.0, min(1.0, float(self.le_main_threshold.text().strip()))),
                max(0.0, min(1.0, float(self.le_friend_threshold.text().strip()))),
            )
        except Exception:
            return None

    def _persist_thresholds(self, silent: bool = True) -> bool:
        parsed = self._parse_thresholds_from_ui()
        if parsed is None:
            return False
        main_th, friend_th = parsed
        cfg = load_steal_feature_config()
        save_steal_feature_config(
            master_enabled=self.chk_enable_friend.isChecked(),
            actions={k: cb.isChecked() for k, cb in self._friend_act_cbs.items()},
            main_interval=float(cfg.get("main_patrol_interval_sec", 0.0)),
            friend_interval=float(cfg.get("friend_patrol_interval_sec", 0.0)),
            main_threshold=main_th,
            friend_threshold=friend_th,
            friend_list_scroll_steps=int(cfg.get("friend_list_scroll_steps", 0)),
        )
        return True

    def _safe_float(self, value: str, name: str) -> Optional[float]:
        try:
            return float(value.strip())
        except Exception:
            QMessageBox.warning(self, "参数错误", f"{name} 不是数字。")
            return None

    def _persist_patrol_intervals(self, silent: bool = False) -> bool:
        main_iv = self._safe_float(self.le_main_interval.text(), "定时巡查农场(秒)")
        if main_iv is None:
            return False
        friend_iv = self._safe_float(self.le_friend_interval.text(), "定时巡查好友农场(秒)")
        if friend_iv is None:
            return False
        main_iv_use = max(PATROL_MIN_MAIN_INTERVAL_SEC, float(main_iv))
        friend_iv_use = max(PATROL_MIN_FRIEND_INTERVAL_SEC, float(friend_iv))
        self.le_main_interval.setText(str(main_iv_use))
        self.le_friend_interval.setText(str(friend_iv_use))
        cfg = load_steal_feature_config()
        th = self._parse_thresholds_from_ui()
        main_th = float(cfg.get("main_patrol_threshold", MAIN_INTERFACE_PATROL_TEMPLATE_THRESHOLD))
        friend_th = float(cfg.get("friend_patrol_threshold", STEAL_UI_MATCH_THRESHOLD))
        if th is not None:
            main_th, friend_th = th
        save_steal_feature_config(
            master_enabled=self.chk_enable_friend.isChecked(),
            actions={k: cb.isChecked() for k, cb in self._friend_act_cbs.items()},
            main_interval=main_iv_use,
            friend_interval=friend_iv_use,
            main_threshold=main_th,
            friend_threshold=friend_th,
            friend_list_scroll_steps=int(cfg.get("friend_list_scroll_steps", 0)),
        )
        if not silent:
            self._append_log(f"[patrol_interval] 已保存: 农场={main_iv_use:g}s, 好友={friend_iv_use:g}s")
        return True

    def _persist_main_actions(self) -> None:
        data = {k: cb.isChecked() for k, cb in self._main_act_cbs.items()}
        save_main_interface_actions_enabled(data)
        self._append_log(f"[main_actions] 已保存: {','.join(k for k, o in data.items() if o) or '无'}")
        self._persist_patrol_intervals(silent=True)

    def _persist_friend_actions(self) -> None:
        cfg = load_steal_feature_config()
        self._sync_friend_actions_state()
        actions = {k: cb.isChecked() for k, cb in self._friend_act_cbs.items()}
        save_steal_feature_config(
            master_enabled=self.chk_enable_friend.isChecked(),
            actions=actions,
            main_interval=float(cfg.get("main_patrol_interval_sec", 0.0)),
            friend_interval=float(cfg.get("friend_patrol_interval_sec", 0.0)),
            main_threshold=float(cfg.get("main_patrol_threshold", MAIN_INTERFACE_PATROL_TEMPLATE_THRESHOLD)),
            friend_threshold=float(cfg.get("friend_patrol_threshold", STEAL_UI_MATCH_THRESHOLD)),
            friend_list_scroll_steps=int(cfg.get("friend_list_scroll_steps", 0)),
        )
        self._append_log(
            f"[friend_actions] 启用={int(self.chk_enable_friend.isChecked())}, "
            f"动作={','.join(k for k, o in actions.items() if o) or '无'}"
        )
        self._persist_patrol_intervals(silent=True)

    def _persist_planting_strategy(self) -> None:
        strategy = self._current_strategy_text()
        seed = self.combo_seed.currentText().strip()
        locked = seed if strategy == STRATEGY_LEVEL_OPTIMAL else ""
        manual_seed = seed if strategy == STRATEGY_MANUAL else ""
        save_planting_strategy_config(
            strategy=strategy,
            manual_seed=manual_seed,
            locked_seed=locked,
            mock_level=int(self._planting_level),
        )
        self._append_log(f"[planting_strategy] 策略={strategy}, 种子={seed or '无'}")

    def _current_strategy_text(self) -> str:
        i = self.combo_strategy.currentIndex()
        if 0 <= i < len(STRATEGY_OPTIONS):
            return STRATEGY_OPTIONS[i]
        return STRATEGY_OPTIONS[0] if STRATEGY_OPTIONS else ""

    def _on_main_master_toggled(self, _c: bool) -> None:
        self._sync_main_actions_state()
        self._append_log(f"[main_actions] 主界面启用={int(self.chk_enable_main.isChecked())}")

    def _sync_main_actions_state(self) -> None:
        on = self.chk_enable_main.isChecked()
        for cb in self._main_act_cbs.values():
            cb.setEnabled(on)

    def _sync_friend_actions_state(self) -> None:
        on = self.chk_enable_friend.isChecked()
        for cb in self._friend_act_cbs.values():
            cb.setEnabled(on)

    def _task_state(self) -> TaskUIState:
        th = self._parse_thresholds_from_ui()
        mt, ft = th if th else (0.4, 0.4)
        return TaskUIState(
            main_master=self.chk_enable_main.isChecked(),
            friend_master=self.chk_enable_friend.isChecked(),
            friend_actions={k: cb.isChecked() for k, cb in self._friend_act_cbs.items()},
            main_interval=float(self.le_main_interval.text().strip() or "0"),
            friend_interval=float(self.le_friend_interval.text().strip() or "0"),
            main_threshold=mt,
            friend_threshold=ft,
        )

    def _refresh_planting_seed_combo(self, save: bool = True) -> None:
        level = int(self._planting_level)
        seeds = get_level_available_seeds(level)
        strategy = self._current_strategy_text()

        self.combo_seed.blockSignals(True)
        self.combo_seed.clear()
        self.combo_seed.addItems(seeds)

        if strategy != STRATEGY_MANUAL:
            locked = (
                get_strategy_best_seed(level, strategy)
                or get_optimal_seed_for_level(level)
                or (seeds[0] if seeds else "")
            )
            if locked and locked in seeds:
                self.combo_seed.setCurrentIndex(seeds.index(locked))
            elif seeds:
                self.combo_seed.setCurrentIndex(0)
            self.combo_seed.setEnabled(False)
            if strategy == STRATEGY_LEVEL_OPTIMAL:
                tip = f"经验最优：{locked or '无'}"
            elif strategy == STRATEGY_PROFIT_OPTIMAL:
                tip = f"利润最优：{locked or '无'}"
            elif strategy == STRATEGY_FERT_EXP_OPTIMAL:
                tip = f"普肥·经验：{locked or '无'}"
            elif strategy == STRATEGY_FERT_PROFIT_OPTIMAL:
                tip = f"普肥·利润：{locked or '无'}"
            else:
                tip = f"推荐：{locked or '无'}"
            self.lbl_planting_hint.setText(tip)
        else:
            self.combo_seed.setEnabled(True)
            cur = self.combo_seed.currentText().strip()
            if not cur and seeds:
                self.combo_seed.setCurrentIndex(0)
            elif cur in seeds:
                self.combo_seed.setCurrentIndex(seeds.index(cur))
            elif seeds:
                self.combo_seed.setCurrentIndex(0)
            self.lbl_planting_hint.setText(f"自选种子，本等级共 {len(seeds)} 种")

        if seeds:
            show = ",".join(seeds[:8])
            if len(seeds) > 8:
                show += "..."
            self.lbl_seed_available.setText(f"可种种子: {show}")
        else:
            self.lbl_seed_available.setText("可种种子: 无")

        self.combo_seed.blockSignals(False)
        if save:
            self._persist_planting_strategy()

    def _on_planting_strategy_changed(self, _i: int) -> None:
        self._refresh_planting_seed_combo(save=True)

    def _on_planting_seed_changed(self, _i: int) -> None:
        if self._current_strategy_text() == STRATEGY_MANUAL:
            self._persist_planting_strategy()

    def _confirm_planting_level(self) -> None:
        raw = self.le_planting_level.text().strip()
        try:
            v = int(raw)
        except ValueError:
            QMessageBox.warning(self, "等级", "请输入 1～300 的整数。")
            return
        v = min(300, max(1, v))
        self._planting_level = v
        self.le_planting_level.setText(str(v))
        self._append_log(f"[planting_strategy] 已确认等级 Lv.{self._planting_level}")
        self._refresh_planting_seed_combo(save=True)
        self._on_engine_status(f"已确认等级 Lv.{self._planting_level}，策略与种子已更新", error=False)

    def _refresh_task_stats(self) -> None:
        try:
            s = read_stats()
            m, f = s["main"], s["friend"]
            for k in self._stat_main:
                self._stat_main[k].setText(str(int(m.get(k, 0))))
            self._stat_friend["收获"].setText(str(int(f.get("摘取", 0))))
            for k in ("浇水", "除虫", "除草"):
                self._stat_friend[k].setText(str(int(f.get(k, 0))))
        except Exception:
            pass

    def _clear_all_task_stats(self) -> None:
        reset_all_stats()
        for lab in self._stat_main.values():
            lab.setText("0")
        for lab in self._stat_friend.values():
            lab.setText("0")
        self._append_log("[stats] 已清零")
        self._on_engine_status("统计数据已全部清零", error=False)

    def _do_start_loop(self) -> None:
        if not self._persist_patrol_intervals(silent=False):
            QMessageBox.warning(self, "参数错误", "巡查间隔未通过校验。")
            return
        self._persist_friend_actions()
        self._engine.start_loop(self._task_state())

    def _do_stop_loop(self) -> None:
        self._engine.stop_loop()

    def _do_main_run_once(self) -> None:
        if not self.chk_enable_main.isChecked():
            self._on_engine_status("未启用主界面任务，无法执行一次", error=True)
            return
        if not self._persist_patrol_intervals(silent=False):
            QMessageBox.warning(self, "参数错误", "巡查间隔未通过校验。")
            return
        if self.chk_enable_friend.isChecked():
            self._persist_friend_actions()
        self._engine.run_main_once(self._task_state())

    def _do_friend_run_once(self) -> None:
        if not self.chk_enable_friend.isChecked():
            self._on_engine_status("未启用好友农场，无法执行一次", error=True)
            return
        if not any(cb.isChecked() for cb in self._friend_act_cbs.values()):
            self._on_engine_status("请至少勾选一项好友农场动作", error=True)
            return
        if not self._persist_patrol_intervals(silent=False):
            QMessageBox.warning(self, "参数错误", "巡查间隔未通过校验。")
            return
        self._persist_friend_actions()
        self._engine.run_friend_once(self._task_state())

    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("BodyRoot")
        self.setCentralWidget(root)
        v = QVBoxLayout(root)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        v.addWidget(self._title_bar)
        hair = QFrame()
        hair.setObjectName("Hairline")
        hair.setFixedHeight(1)
        v.addWidget(hair)

        outer = QVBoxLayout()
        outer.setContentsMargins(BOX_SPACING, BOX_SPACING, BOX_SPACING, BOX_SPACING)
        outer.setSpacing(BOX_SPACING)

        # --- 顶行：游戏窗口识别 | 任务控制（与 Tk top_row 一致） ---
        top_row = self._h(BOX_SPACING)
        w_reg, inner_reg = self._make_section("游戏窗口识别")
        rg = self._h(UI_PAD)
        br1 = QPushButton("自动拾取")
        br1.setObjectName("BtnSecondary")
        br1.setFixedSize(BTN_W, BTN_H)
        br1.clicked.connect(self._engine.run_region_auto)
        br2 = QPushButton("窗口拾取")
        br2.setObjectName("BtnSecondary")
        br2.setFixedSize(BTN_W, BTN_H)
        br2.clicked.connect(self._engine.run_region_manual)
        rg.addWidget(br1)
        rg.addWidget(br2)
        rg.addStretch()
        inner_reg.addLayout(rg)

        w_key, inner_key = self._make_section("任务控制")
        kg = self._h(UI_PAD)
        self.btn_start = QPushButton("启动任务")
        self.btn_start.setObjectName("BtnPrimary")
        self.btn_start.setFixedSize(BTN_W, BTN_H)
        self.btn_start.clicked.connect(self._do_start_loop)
        self.btn_stop = QPushButton("停止 (F12)")
        self.btn_stop.setObjectName("BtnStop")
        self.btn_stop.setFixedSize(BTN_W, BTN_H)
        self.btn_stop.clicked.connect(self._do_stop_loop)
        kg.addWidget(self.btn_start)
        kg.addWidget(self.btn_stop)
        kg.addStretch()
        inner_key.addLayout(kg)

        top_row.addWidget(w_reg, 1, Qt.AlignmentFlag.AlignBottom)
        top_row.addWidget(w_key, 1, Qt.AlignmentFlag.AlignBottom)
        outer.addLayout(top_row)

        # --- 次行：主界面任务 | 好友农场任务 ---
        task_row = self._h(BOX_SPACING)
        w_main, inner_main = self._make_section("主界面任务")

        self.chk_enable_main = QCheckBox("启用主界面任务")
        self.chk_enable_main.setChecked(True)
        self.chk_enable_main.toggled.connect(self._on_main_master_toggled)
        r1 = self._h(UI_PAD)
        r1.addWidget(self.chk_enable_main)
        r1.addSpacing(12)
        r1.addWidget(QLabel("匹配阈值"))
        self.le_main_threshold = QLineEdit()
        self.le_main_threshold.setFixedWidth(56)
        self.le_main_threshold.textChanged.connect(lambda _t: self._persist_thresholds())
        r1.addWidget(self.le_main_threshold)
        r1.addStretch()
        inner_main.addLayout(r1)

        r2 = self._h(UI_PAD)
        for name in ("收获", "浇水", "除虫", "除草"):
            cb = QCheckBox(name)
            cb.toggled.connect(self._persist_main_actions)
            self._main_act_cbs[name] = cb
            r2.addWidget(cb)
        r2.addStretch()
        inner_main.addLayout(r2)

        r3 = QHBoxLayout()
        r3.setContentsMargins(0, 0, 0, 0)
        r3.setSpacing(0)
        r3.addWidget(QLabel("巡查间隔 (秒)"))
        r3.addSpacing(4)
        self.le_main_interval = QLineEdit()
        self.le_main_interval.setFixedWidth(80)
        r3.addWidget(self.le_main_interval)
        r3.addSpacing(12)
        self.btn_main_once = QPushButton("执行一次")
        self.btn_main_once.setObjectName("BtnPrimary")
        self.btn_main_once.setFixedSize(BTN_W, BTN_H)
        self.btn_main_once.clicked.connect(self._do_main_run_once)
        r3.addWidget(self.btn_main_once)
        r3.addStretch()
        inner_main.addLayout(r3)

        w_fr, inner_fr = self._make_section("好友农场任务")

        self.chk_enable_friend = QCheckBox("启用好友农场")
        self.chk_enable_friend.toggled.connect(self._persist_friend_actions)
        f1 = self._h(UI_PAD)
        f1.addWidget(self.chk_enable_friend)
        f1.addSpacing(12)
        f1.addWidget(QLabel("匹配阈值"))
        self.le_friend_threshold = QLineEdit()
        self.le_friend_threshold.setFixedWidth(56)
        self.le_friend_threshold.textChanged.connect(lambda _t: self._persist_thresholds())
        f1.addWidget(self.le_friend_threshold)
        f1.addStretch()
        inner_fr.addLayout(f1)

        f2 = self._h(UI_PAD)
        for name in ("摘取", "除虫", "浇水", "除草"):
            cb = QCheckBox(name)
            cb.toggled.connect(self._persist_friend_actions)
            self._friend_act_cbs[name] = cb
            f2.addWidget(cb)
        f2.addStretch()
        inner_fr.addLayout(f2)

        f3 = QHBoxLayout()
        f3.setContentsMargins(0, 0, 0, 0)
        f3.setSpacing(0)
        f3.addWidget(QLabel("巡查间隔 (秒)"))
        f3.addSpacing(4)
        self.le_friend_interval = QLineEdit()
        self.le_friend_interval.setFixedWidth(80)
        f3.addWidget(self.le_friend_interval)
        f3.addSpacing(12)
        self.btn_friend_once = QPushButton("执行一次")
        self.btn_friend_once.setObjectName("BtnPrimary")
        self.btn_friend_once.setFixedSize(BTN_W, BTN_H)
        self.btn_friend_once.clicked.connect(self._do_friend_run_once)
        f3.addWidget(self.btn_friend_once)
        f3.addStretch()
        inner_fr.addLayout(f3)

        task_row.addWidget(w_main, 1, Qt.AlignmentFlag.AlignBottom)
        task_row.addWidget(w_fr, 1, Qt.AlignmentFlag.AlignBottom)
        outer.addLayout(task_row)

        # --- 底行：种植策略 | 右侧统计列 ---
        # 顶对齐：若用 AlignBottom，右侧统计列很高时会把左侧「种植策略」压到底部，
        # 主界面任务与种植策略之间会出现大块空白（实为底行内空隙）。
        bottom_row = self._h(BOX_SPACING)
        w_plant, inner_plant = self._make_section("种植策略")

        p1 = self._h(UI_PAD)
        p1.addWidget(QLabel("当前等级"))
        self.le_planting_level = QLineEdit()
        self.le_planting_level.setFixedWidth(56)
        self.le_planting_level.setValidator(QIntValidator(1, 300, self))
        self.le_planting_level.setAlignment(Qt.AlignmentFlag.AlignCenter)
        p1.addWidget(self.le_planting_level)
        p1.addStretch()
        self.btn_confirm_level = QPushButton("确认等级")
        self.btn_confirm_level.setObjectName("BtnSecondary")
        self.btn_confirm_level.setFixedSize(BTN_W, BTN_H)
        self.btn_confirm_level.clicked.connect(self._confirm_planting_level)
        p1.addWidget(self.btn_confirm_level)
        inner_plant.addLayout(p1)

        self.combo_strategy = QComboBox()
        self.combo_strategy.addItems(STRATEGY_OPTIONS)
        self.combo_strategy.setMinimumWidth(200)
        self.combo_strategy.currentIndexChanged.connect(self._on_planting_strategy_changed)
        ps = self._h(UI_PAD)
        ps.addWidget(QLabel("策略"))
        ps.addWidget(self.combo_strategy, 1)
        inner_plant.addLayout(ps)

        self.combo_seed = QComboBox()
        self.combo_seed.setMinimumWidth(200)
        self.combo_seed.currentIndexChanged.connect(self._on_planting_seed_changed)
        pseed = self._h(UI_PAD)
        pseed.addWidget(QLabel("种子"))
        pseed.addWidget(self.combo_seed, 1)
        inner_plant.addLayout(pseed)

        self.lbl_planting_hint = QLabel("")
        self.lbl_planting_hint.setObjectName("HintLabel")
        self.lbl_planting_hint.setWordWrap(True)
        inner_plant.addWidget(self.lbl_planting_hint)

        self.lbl_seed_available = QLabel("")
        self.lbl_seed_available.setObjectName("HintLabel")
        self.lbl_seed_available.setWordWrap(True)
        inner_plant.addWidget(self.lbl_seed_available)

        right_col = QWidget()
        rvl = QVBoxLayout(right_col)
        rvl.setContentsMargins(0, 0, 0, 0)
        rvl.setSpacing(0)

        w_stats, inner_stats = self._make_section("任务统计")
        w_stats.setFixedHeight(TASK_STATS_CARD_HEIGHT)

        grid_m = QGridLayout()
        grid_m.setSpacing(UI_PAD)
        self._stat_main = {}
        pairs_m = [("收获", "浇水"), ("除虫", "除草")]
        for r, pair in enumerate(pairs_m):
            for c, name in enumerate(pair):
                cell = QWidget()
                hl = self._h(4)
                hl.addWidget(QLabel(f"{name}："))
                vl = QLabel("0")
                vl.setObjectName("StatValue")
                hl.addWidget(vl)
                hl.addStretch()
                cell.setLayout(hl)
                self._stat_main[name] = vl
                grid_m.addWidget(cell, r, c)
        inner_stats.addLayout(grid_m)

        inner_stats.addWidget(self._stat_subheading("好友农场"))
        grid_f = QGridLayout()
        grid_f.setSpacing(UI_PAD)
        self._stat_friend = {}
        pairs_f = [("收获", "浇水"), ("除虫", "除草")]
        for r, pair in enumerate(pairs_f):
            for c, name in enumerate(pair):
                cell = QWidget()
                hl = self._h(4)
                hl.addWidget(QLabel(f"{name}："))
                vl = QLabel("0")
                vl.setObjectName("StatValue")
                hl.addWidget(vl)
                hl.addStretch()
                cell.setLayout(hl)
                self._stat_friend[name] = vl
                grid_f.addWidget(cell, r, c)
        inner_stats.addLayout(grid_f)

        self.btn_clear_stats = QPushButton("全部数据清零")
        self.btn_clear_stats.setObjectName("BtnSecondaryWide")
        self.btn_clear_stats.setFixedSize(120, BTN_H)
        self.btn_clear_stats.clicked.connect(self._clear_all_task_stats)
        inner_stats.addWidget(self.btn_clear_stats)

        rvl.addWidget(w_stats)
        rvl.addStretch(1)

        right_col.setFixedWidth(SECTION_BOX_WIDTH)

        bottom_row.addWidget(w_plant, 1, Qt.AlignmentFlag.AlignTop)
        bottom_row.addWidget(right_col, 1, Qt.AlignmentFlag.AlignTop)
        outer.addLayout(bottom_row)

        v.addLayout(outer, 1)

        sb = QStatusBar()
        self.setStatusBar(sb)
        sb.showMessage("就绪" + self._status_suffix())

    def _build_shortcuts(self) -> None:
        sc = QShortcut(QKeySequence(Qt.Key.Key_F12), self)
        sc.setContext(Qt.ShortcutContext.ApplicationShortcut)
        sc.activated.connect(self._do_stop_loop)

    def _poll_f12_key_state(self) -> None:
        if sys.platform != "win32":
            return
        try:
            down = bool(ctypes.windll.user32.GetAsyncKeyState(0x7B) & 0x8000)
            if down and not self._f12_down_prev:
                self._do_stop_loop()
            self._f12_down_prev = down
        except Exception:
            pass

    def closeEvent(self, event) -> None:
        if self._engine.is_loop_running():
            self._engine.stop_loop()
        event.accept()


def main() -> int:
    _migrate_legacy_user_files()
    _hide_console_on_windows()
    donation_dialog.prepare_session()
    app = QApplication(sys.argv)
    app.aboutToQuit.connect(donation_dialog.finalize_session_usage_on_exit)
    if APP_ICON_PATH.is_file():
        app.setWindowIcon(QIcon(str(APP_ICON_PATH)))
    w = FarmAssistantWindow()
    w.show()
    QTimer.singleShot(0, w._center_and_snap_to_content)
    QTimer.singleShot(300, lambda: donation_dialog_qt.show_if_needed(w))
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
