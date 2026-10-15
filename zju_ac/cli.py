"""Interactive command line entry point."""

import argparse
import getpass
import logging
import sys
import traceback
from pathlib import Path

from . import __version__
from .config import Settings, load_config
from .errors import AuthenticationExpired, TemporaryError, ZjuError
from .models import Rollcall
from .notify import Notifier, configure_terminal
from .watchdog import USER_ACTION_REQUIRED, Credentials, run_watchdog


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="ZJU-AC：运行参数统一读取根目录 config.toml")
    result.add_argument("--version", action="version", version=__version__)
    return result


def main(argv: list[str] | None = None) -> int:
    configure_terminal()
    parser().parse_args(argv)
    try:
        settings = load_config()
    except ZjuError as exc:
        print(f"配置错误：{exc}", file=sys.stderr)
        return USER_ACTION_REQUIRED
    return run_application(settings)


def run_application(
    args: Settings,
    credentials: Credentials | None = None,
    supervised: bool = False,
) -> int:
    configure_terminal()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    notifier = Notifier(desktop=args.desktop, bell=args.bell)
    if args.demo:
        notifier.send(Rollcall("demo", "演示课程", "这是一条离线测试提醒", "数字"))
        return 0
    if credentials is None and not sys.stdin.isatty():
        print("请在交互终端运行，以便安全输入学号和密码。", file=sys.stderr)
        return 2
    try:
        # Import runtime dependencies before requesting any credentials.
        from .auth import login
        from .checkin import ConfirmedCheckin
        from .monitor import run_monitor

        if credentials is None:
            student_id = input("学号：").strip()
            password = getpass.getpass("统一身份认证密码（隐藏输入）：")
        else:
            student_id, password = credentials.student_id, credentials.password
        if not student_id or not password:
            raise ZjuError("学号和密码不能为空。")
        if args.watchdog and not args.once and not supervised:
            return run_watchdog(args, Credentials(student_id, password))
        with login(student_id, password, args.login_timeout) as client:
            password = ""
            checkin = (
                None
                if args.reminders_only or args.once
                else ConfirmedCheckin(client, settings=args)
            )
            try:
                run_monitor(
                    client,
                    notifier,
                    args.interval,
                    args.remind_every,
                    args.once,
                    checkin=checkin,
                )
            finally:
                if checkin is not None:
                    checkin.close()
        return 0
    except (KeyboardInterrupt, EOFError):
        print("\n已退出。")
        return 0
    except (AuthenticationExpired, TemporaryError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    except ZjuError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return USER_ACTION_REQUIRED if supervised else 1
    except ModuleNotFoundError as exc:
        package = {"requests": "requests", "bs4": "beautifulsoup4"}.get(exc.name)
        missing = f"缺少运行依赖 {package}" if package else "运行依赖安装不完整"
        print(
            f"错误：{missing}。请在当前 conda 环境中执行：\n"
            "python -m pip install -r requirements.txt\n"
            f"当前 Python：{sys.executable}",
            file=sys.stderr,
        )
        return USER_ACTION_REQUIRED if supervised else 1
    except Exception as exc:
        # Report a code location, never exception arguments, credentials, or ticket URLs.
        frame = traceback.extract_tb(exc.__traceback__)[-1]
        location = f"{Path(frame.filename).name}:{frame.lineno}"
        print(
            f"错误：程序遇到未处理异常（{type(exc).__name__}，{location}）。"
            "请反馈这条错误信息以便定位。",
            file=sys.stderr,
        )
        return 1
