"""
PyQt 控制台共用的子进程逻辑：单次脚本、循环任务启停。
日志写入：control_center_core._write_control_center_log。
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import control_center_core as ccc

BASE_DIR = ccc.BASE_DIR
_action_session_env = ccc._action_session_env
_subprocess_encoding = ccc._subprocess_encoding
_subprocess_flags = ccc._subprocess_flags
_write_log = ccc._write_control_center_log


@dataclass
class TaskUIState:
    """与控制台 UI 一致的界面快照（持久化应由界面在调用前完成）。"""

    main_master: bool
    friend_master: bool
    friend_actions: Dict[str, bool]
    main_interval: float
    friend_interval: float
    main_threshold: float
    friend_threshold: float


class QtControlCenterEngine:
    def __init__(
        self,
        on_status: Callable[[str, bool], None],
    ) -> None:
        self._status = on_status
        self.loop_proc: Optional[subprocess.Popen] = None
        self.loop_reader_thread: Optional[threading.Thread] = None
        self._loop_session_dir: Optional[Path] = None

    def _append(self, line: str) -> None:
        _write_log(line)

    def _append_safe(self, line: str) -> None:
        _write_log(line)

    def _notify(self, msg: str, *, error: bool = False) -> None:
        try:
            self._status(msg, error)
        except Exception:
            pass

    def is_loop_running(self) -> bool:
        return self.loop_proc is not None and self.loop_proc.poll() is None

    def run_once_background(
        self,
        name: str,
        cmd: List[str],
        *,
        header_success: Optional[str] = None,
        header_failure: Optional[str] = None,
    ) -> None:
        def run() -> None:
            cmd_use = list(cmd)
            if cmd_use and cmd_use[0] == sys.executable and "-u" not in cmd_use[1:]:
                cmd_use.insert(1, "-u")
            env_session, session_path = _action_session_env()
            self._append_safe(f"[{name}] 启动: {' '.join(cmd_use)}")
            if session_path is not None:
                self._append_safe(f"[{name}] 操作记录目录: {session_path}")
            try:
                cp = subprocess.Popen(
                    cmd_use,
                    cwd=str(BASE_DIR),
                    env=env_session,
                    stdout=subprocess.PIPE,  # type: ignore[arg-type]
                    stderr=subprocess.STDOUT,  # type: ignore[arg-type]
                    text=True,
                    encoding=_subprocess_encoding(),
                    errors="replace",
                    **_subprocess_flags(),
                )
                if cp.stdout:
                    for line in cp.stdout:
                        line = line.rstrip("\r\n")
                        if line:
                            self._append_safe(f"[{name}] {line}")
                cp.wait()
                self._append_safe(f"[{name}] 完成，exit={cp.returncode}")
                if header_success and header_failure:
                    rc = cp.returncode
                    if rc == 0:
                        self._notify(header_success, error=False)
                    else:
                        self._notify(f"{header_failure}（退出码 {rc}）", error=True)
                if session_path is not None:
                    try:
                        from action_session_recorder import finalize_session_dir

                        outp = finalize_session_dir(session_path)
                        if outp is not None:
                            self._append_safe(f"[{name}] 操作记录表: {outp}")
                    except Exception as exc:
                        self._append_safe(f"[{name}] 操作记录生成失败: {type(exc).__name__}: {exc}")
            except Exception as exc:
                self._append_safe(f"[{name}] 执行异常: {type(exc).__name__}: {exc}")
                if header_failure:
                    self._notify(f"{header_failure}：{type(exc).__name__}", error=True)

        threading.Thread(target=run, daemon=True).start()

    def run_region_auto(self) -> None:
        cmd = [sys.executable, "game_window_pick_worker.py", "--mode", "auto"]
        self.run_once_background(
            "region_auto", cmd, header_success="自动拾取成功", header_failure="自动拾取失败"
        )

    def run_region_manual(self) -> None:
        cmd = [sys.executable, "game_window_pick_worker.py", "--mode", "pick"]
        self.run_once_background(
            "region_manual", cmd, header_success="窗口拾取成功", header_failure="窗口拾取失败"
        )

    def run_main_once(self, st: TaskUIState) -> None:
        if not st.main_master:
            self._append("[main_once] 跳过：未启用主界面任务。")
            self._notify("未启用主界面任务，无法执行一次", error=True)
            return
        if bool(st.friend_master):
            self._append("[main_once] 已触发组合执行：先主界面任务，再好友农场任务。")
            cmd = [sys.executable, "friend_farm_worker.py", "--once", "--run-main-first", "1"]
            self.run_once_background(
                "main_once",
                cmd,
                header_success="执行一次成功（先主界面后好友）",
                header_failure="执行一次失败",
            )
            return
        self._append("[main_once] 已触发执行一次（仅主界面任务）。")
        cmd = [sys.executable, "main_interface_worker.py", "--once"]
        self.run_once_background(
            "main_once",
            cmd,
            header_success="执行一次成功（主界面）",
            header_failure="执行一次失败",
        )

    def run_friend_once(self, st: TaskUIState) -> None:
        if not st.friend_master:
            self._append("[friend_once] 跳过：未启用好友农场。")
            self._notify("未启用好友农场，无法执行一次", error=True)
            return
        if not any(st.friend_actions.values()):
            self._append("[friend_once] 跳过：好友农场动作未勾选。")
            self._notify("请至少勾选一项好友农场动作", error=True)
            return
        run_main_first = "1" if st.main_master else "0"
        if run_main_first == "1":
            self._append("[friend_once] 已触发组合执行：先主界面任务，再好友农场任务。")
            ok_msg, fail_msg = "执行一次成功（先主界面后好友）", "执行一次失败"
        else:
            self._append("[friend_once] 已触发执行一次（仅好友农场任务）。")
            ok_msg, fail_msg = "执行一次成功（好友农场）", "执行一次失败"
        cmd = [sys.executable, "friend_farm_worker.py", "--once", "--run-main-first", run_main_first]
        self.run_once_background("friend_once", cmd, header_success=ok_msg, header_failure=fail_msg)

    def start_loop(self, st: TaskUIState) -> None:
        if self.is_loop_running():
            self._append("[loop] 已在运行中，忽略重复启动。")
            self._notify("循环任务已在运行", error=True)
            return
        if not st.main_master and not st.friend_master:
            self._append("[loop] 跳过：主界面任务与好友农场任务都未启用。")
            self._notify("请至少启用主界面或好友农场任务", error=True)
            return
        if st.friend_master and not any(st.friend_actions.values()):
            self._append("[loop] 跳过：好友农场已启用但动作全未勾选。")
            self._notify("好友农场已启用但未勾选动作", error=True)
            return

        if st.main_master and st.friend_master:
            cmd = [sys.executable, "friend_farm_worker.py", "--run-main-first", "1"]
            mode = "主界面+好友农场循环（先主后友）"
        elif st.main_master:
            cmd = [sys.executable, "main_interface_worker.py"]
            mode = "仅主界面任务循环"
        else:
            cmd = [sys.executable, "friend_farm_worker.py", "--run-main-first", "0"]
            mode = "仅好友农场循环"

        cmd_use = list(cmd)
        if cmd_use and cmd_use[0] == sys.executable and "-u" not in cmd_use[1:]:
            cmd_use.insert(1, "-u")
        self._append(f"[loop] 启动: {mode} -> {' '.join(cmd_use)}")

        env_session, session_path = _action_session_env()
        if session_path is not None:
            self._append(f"[loop] 操作记录目录: {session_path}")

        try:
            self.loop_proc = subprocess.Popen(
                cmd_use,
                cwd=str(BASE_DIR),
                env=env_session,
                stdout=subprocess.PIPE,  # type: ignore[arg-type]
                stderr=subprocess.STDOUT,  # type: ignore[arg-type]
                text=True,
                encoding=_subprocess_encoding(),
                errors="replace",
                **_subprocess_flags(),
            )
        except Exception as exc:
            self.loop_proc = None
            self._append(f"[loop] 启动失败: {type(exc).__name__}: {exc}")
            self._notify(f"启动任务失败：{type(exc).__name__}", error=True)
            return

        self._notify("启动任务成功", error=False)
        self._loop_session_dir = session_path

        def read_loop_output() -> None:
            proc = self.loop_proc
            if proc is None:
                return
            try:
                if proc.stdout:
                    for line in proc.stdout:
                        line = line.rstrip("\r\n")
                        if line:
                            self._append_safe(f"[loop] {line}")
                proc.wait()
                self._append_safe(f"[loop] 已停止，exit={proc.returncode}")
            finally:
                sd = self._loop_session_dir
                self._loop_session_dir = None
                self.loop_proc = None
                self.loop_reader_thread = None
                if sd is not None and sd.is_dir():
                    try:
                        from action_session_recorder import finalize_session_dir

                        outp = finalize_session_dir(sd)
                        if outp is not None:
                            self._append_safe(f"[loop] 操作记录表: {outp}")
                    except Exception as exc:
                        self._append_safe(f"[loop] 操作记录生成失败: {type(exc).__name__}: {exc}")

        self.loop_reader_thread = threading.Thread(target=read_loop_output, daemon=True)
        self.loop_reader_thread.start()

    def stop_loop(self) -> None:
        if not self.is_loop_running():
            self._append("[loop] 当前没有运行中的循环任务。")
            self._notify("当前没有运行中的循环任务", error=True)
            return
        proc = self.loop_proc
        if proc is None:
            self._notify("当前没有运行中的循环任务", error=True)
            return
        session_dir = self._loop_session_dir
        self._loop_session_dir = None
        self._append("[loop] 正在停止循环任务...")
        self._notify("已发送停止，循环任务将退出", error=False)
        try:
            proc.terminate()
        except Exception:
            pass

        def _finalize_session_later() -> None:
            import time as _time

            _time.sleep(1.0)
            if session_dir is None or not session_dir.is_dir():
                return
            try:
                from action_session_recorder import finalize_session_dir

                outp = finalize_session_dir(session_dir)
                if outp is not None:
                    self._append_safe(f"[loop] 操作记录表已生成: {outp}")
            except Exception as exc:
                self._append_safe(f"[loop] 操作记录生成失败: {type(exc).__name__}: {exc}")

        threading.Thread(target=_finalize_session_later, daemon=True).start()
