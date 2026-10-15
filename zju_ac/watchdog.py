"""Supervise a separate worker process without storing credentials on disk."""

import logging
import multiprocessing
import os
import sys
import time
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass

from .notify import configure_terminal

LOGGER = logging.getLogger(__name__)
USER_ACTION_REQUIRED = 2
RESTART_WINDOW = 600


@dataclass(frozen=True, repr=False)
class Credentials:
    student_id: str
    password: str


@contextmanager
def worker_terminal():
    """Restore stdin after multiprocessing replaces it with the null device.

    On Windows NUL is a character device and isatty() may return True. It
    still returns EOF immediately, so that check cannot detect usable input.
    This context is only used in the spawned worker: always reopen its terminal.
    """
    original = sys.stdin
    terminal = None
    try:
        try:
            terminal = open("CONIN$" if os.name == "nt" else "/dev/tty", encoding="utf-8")
        except OSError as exc:
            from .errors import ZjuError

            raise ZjuError("无法打开交互终端，请在普通终端中运行看门狗模式。") from exc
        sys.stdin = terminal
        yield
    finally:
        sys.stdin = original
        if terminal is not None:
            terminal.close()


def worker_entry(args, credentials: Credentials) -> None:
    from .cli import run_application
    from .errors import ZjuError

    configure_terminal()
    try:
        with worker_terminal():
            code = run_application(args, credentials, supervised=True)
    except (KeyboardInterrupt, EOFError):
        code = 0
    except ZjuError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        code = USER_ACTION_REQUIRED
    raise SystemExit(code)


def stop_worker(worker) -> None:
    """Give Ctrl+C cleanup a chance, then stop only the process owned by this supervisor."""
    if worker.pid is None:
        return
    if worker.is_alive():
        try:
            worker.join(timeout=3)
        except KeyboardInterrupt:
            pass
    if worker.is_alive():
        worker.terminate()
        worker.join(timeout=5)
    if worker.is_alive():
        worker.kill()
        worker.join(timeout=5)


def run_watchdog(args, credentials: Credentials) -> int:
    context = multiprocessing.get_context("spawn")
    restarts: deque[float] = deque()
    worker = None
    LOGGER.info(
        "看门狗已启用：异常退出后等待 %s 秒，10 分钟内最多重启 %s 次。",
        args.restart_delay,
        args.max_restarts,
    )
    try:
        while True:
            worker = context.Process(
                target=worker_entry,
                args=(args, credentials),
                name="zju-ac-worker",
            )
            try:
                worker.start()
            except (OSError, ValueError):
                LOGGER.error("看门狗无法启动工作进程，请检查当前 Python 和系统权限。")
                return 1
            LOGGER.info("工作进程已启动（PID %s）。", worker.pid)
            worker.join()
            code = worker.exitcode
            worker.close()
            worker = None
            if code == 0:
                LOGGER.info("工作进程正常退出，看门狗已停止。")
                return 0
            if code == USER_ACTION_REQUIRED:
                LOGGER.error("工作进程需要人工处理认证、依赖或配置问题，看门狗已停止。")
                return 1
            now = time.monotonic()
            while restarts and now - restarts[0] >= RESTART_WINDOW:
                restarts.popleft()
            if len(restarts) >= args.max_restarts:
                LOGGER.error("10 分钟内已重启 %s 次，停止以避免持续崩溃。", args.max_restarts)
                return 1
            restarts.append(now)
            LOGGER.warning(
                "工作进程异常退出（退出码 %s），%s 秒后重启（本窗口第 %s 次）。",
                code,
                args.restart_delay,
                len(restarts),
            )
            time.sleep(args.restart_delay)
    except KeyboardInterrupt:
        LOGGER.info("收到退出指令，看门狗已停止，不再重启。")
        return 0
    finally:
        if worker is not None:
            stop_worker(worker)
            worker.close()
