"""
试用与自愿打赏提示（PyQt6），与 donation_dialog 共用同一份状态 JSON。
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from donation_dialog import (
    BUTTON_DELAY_SEC,
    DONATION_MESSAGE,
    WEI_SHANG_NO_EXIT_AT,
    finalize_session_usage_on_exit,
    load_state,
    save_state,
    should_show_reminder,
)

_QR_PATH = Path(__file__).resolve().parent.parent / "assets" / "donation_qr.png"


class _DonationDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("感谢支持")
        self.setModal(True)
        # 勿挂到主窗口下：否则会继承控制台 QSS 里浅色 QLabel 字色，在默认浅底上几乎看不见说明文字
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setObjectName("DonationDialogRoot")
        self.setStyleSheet(
            """
            QDialog#DonationDialogRoot {
                background-color: #FFFFFF;
            }
            QDialog#DonationDialogRoot QLabel {
                color: #222222;
                background-color: transparent;
                font-size: 12px;
            }
            QDialog#DonationDialogRoot QPushButton {
                color: #111111;
                min-height: 28px;
            }
            """
        )
        self._wei_handled = False

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)

        if _QR_PATH.is_file():
            pix = QPixmap(str(_QR_PATH))
            if not pix.isNull():
                lab = QLabel()
                lab.setPixmap(
                    pix.scaled(
                        280,
                        280,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
                lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
                root.addWidget(lab)
            else:
                root.addWidget(QLabel(f"收款码图片无法读取: {_QR_PATH.name}"))
        else:
            root.addWidget(QLabel(f"缺少收款码: {_QR_PATH}"))

        cap = QLabel(DONATION_MESSAGE.strip())
        cap.setWordWrap(True)
        cap.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cap.setMaximumWidth(360)
        root.addWidget(cap)

        row = QHBoxLayout()
        self._yi_remain_sec = int(BUTTON_DELAY_SEC)
        self._btn_yi = QPushButton(self._yi_shang_button_caption())
        self._btn_yi.setEnabled(False)
        self._btn_yi.setMinimumWidth(160)
        self._btn_wei = QPushButton("未赏")
        self._btn_wei.setMinimumWidth(100)
        row.addWidget(self._btn_yi)
        row.addWidget(self._btn_wei)
        root.addLayout(row)

        self._btn_yi.clicked.connect(self._on_yi_shang)
        self._btn_wei.clicked.connect(self._apply_wei_shang)

        # 每次弹出本窗（含上次点「未赏」后下次打开）都须等待 BUTTON_DELAY_SEC 秒才可点「已赏」。
        # 用每秒倒计时而非单次超长 QTimer，避免个别系统上超时回调不触发。
        self._yi_countdown_started = False
        self._yi_countdown_timer = QTimer(self)
        self._yi_countdown_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._yi_countdown_timer.timeout.connect(self._tick_yi_unlock_countdown)

    def _yi_shang_button_caption(self) -> str:
        if self._yi_remain_sec > 0:
            return f"已赏（约 {self._yi_remain_sec} 秒后可点）"
        return "已赏"

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        if self._yi_countdown_started:
            return
        self._yi_countdown_started = True
        self._yi_countdown_timer.start(1000)

    def _tick_yi_unlock_countdown(self) -> None:
        try:
            self._yi_remain_sec -= 1
            if self._yi_remain_sec <= 0:
                self._yi_countdown_timer.stop()
                self._btn_yi.setText("已赏")
                self._btn_yi.setEnabled(True)
                return
            self._btn_yi.setText(self._yi_shang_button_caption())
        except RuntimeError:
            self._yi_countdown_timer.stop()

    def _on_yi_shang(self) -> None:
        st = load_state()
        st["yi_shang_count"] = int(st.get("yi_shang_count", 0)) + 1
        st["last_reminder_ts"] = time.time()
        save_state(st)
        self._wei_handled = True
        self.accept()

    def _apply_wei_shang(self) -> None:
        if self._wei_handled:
            return
        self._wei_handled = True
        st = load_state()
        st["wei_shang_count"] = int(st.get("wei_shang_count", 0)) + 1
        wc = st["wei_shang_count"]
        save_state(st)
        self.accept()
        if wc < WEI_SHANG_NO_EXIT_AT:
            # sys.exit 可能绕过 QApplication.aboutToQuit，需先落盘本会话使用时长
            finalize_session_usage_on_exit()
            QApplication.instance().quit()
            sys.exit(0)

    def closeEvent(self, event) -> None:  # type: ignore[override]
        if not self._wei_handled:
            self._apply_wei_shang()
            event.accept()
            return
        super().closeEvent(event)


def show_if_needed(parent: QWidget | None = None) -> None:
    if not should_show_reminder():
        return
    dlg = _DonationDialog(None)
    dlg.exec()
