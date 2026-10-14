"""Interactive command line entry point."""

import argparse
import getpass
import logging
import sys

from . import __version__
from .errors import ZjuError
from .models import Rollcall
from .notify import Notifier, configure_terminal


def seconds(value: str) -> int:
    parsed = int(value)
    if parsed < 5:
        raise argparse.ArgumentTypeError("必须至少为 5 秒")
    return parsed


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="ZJU-AC：终端登录与课堂签到提醒")
    result.add_argument("--version", action="version", version=__version__)
    result.add_argument("--interval", type=seconds, default=15, help="轮询间隔秒数，默认 15")
    result.add_argument("--remind-every", type=seconds, default=0, help="未完成时重复提醒的秒数")
    result.add_argument("--login-timeout", type=seconds, default=180, help="登录等待秒数，默认 180")
    result.add_argument(
        "--browser",
        choices=["msedge", "chrome", "chromium"],
        default="msedge" if sys.platform == "win32" else "chromium",
    )
    result.add_argument("--once", action="store_true", help="登录后查询一次并退出")
    result.add_argument("--demo", action="store_true", help="离线演示提醒，无需登录")
    result.add_argument("--no-desktop", action="store_true", help="关闭桌面通知")
    result.add_argument("--no-bell", action="store_true", help="关闭终端提示音")
    return result


def main(argv: list[str] | None = None) -> int:
    configure_terminal()
    args = parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    notifier = Notifier(desktop=not args.no_desktop, bell=not args.no_bell)
    if args.demo:
        notifier.send(Rollcall("demo", "演示课程", "这是一条离线测试提醒", "数字"))
        return 0
    if not sys.stdin.isatty():
        print("请在交互终端运行，以便安全输入学号和密码。", file=sys.stderr)
        return 2
    try:
        student_id = input("学号：").strip()
        password = getpass.getpass("统一身份认证密码（隐藏输入）：")
        if not student_id or not password:
            raise ZjuError("学号和密码不能为空。")
        from .auth import login
        from .monitor import run_monitor

        with login(student_id, password, args.browser, args.login_timeout) as client:
            password = ""
            run_monitor(client, notifier, args.interval, args.remind_every, args.once)
        return 0
    except (KeyboardInterrupt, EOFError):
        print("\n已退出。")
        return 0
    except ZjuError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    except Exception:
        # Third-party exceptions can include URLs with tickets; do not print their details.
        print("错误：程序遇到异常，请检查网络和浏览器，必要时重新运行。", file=sys.stderr)
        return 1
