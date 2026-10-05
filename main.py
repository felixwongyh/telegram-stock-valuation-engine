"""
main.py - Entry Point
Usage:
  python main.py                 # Start Telegram Bot
  python main.py bot           # Start Telegram Bot
  python main.py demo AAPL        # Run demo valuation on AAPL and print report
  python main.py test           # Run pytest suite
  python main.py test_demo       # Run demo valuation on AAPL, MSFT, NVDA
"""
from __future__ import annotations

import asyncio
import io
import os
import sys
from pathlib import Path


def _fix_proxy_env() -> None:
    """Fix common broken proxy env vars (e.g. ::1 in NO_PROXY breaks httpx)."""
    for _key in ("NO_PROXY", "no_proxy"):
        _val = os.environ.get(_key)
        if not _val:
            continue
        _parts = [p.strip() for p in _val.split(",") if p.strip()]
        _clean = [
            p for p in _parts
            if not (p.startswith("::") or p == "::1" or p == "::")
            and not ("/" in p and p.startswith("::"))
        ]
        if "localhost" not in _clean:
            _clean.append("localhost")
        if "127.0.0.1" not in _clean:
            _clean.append("127.0.0.1")
        os.environ[_key] = ",".join(_clean)


_fix_proxy_env()

if sys.platform == "win32":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    except Exception:
        pass

PYTHONIOENCODING = os.environ.setdefault("PYTHONIOENCODING", "utf-8")

ROOT = Path(__file__).parent.resolve()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import get_logger

log = get_logger("main")


def safe_print(text: str) -> None:
    try:
        print(text)
    except UnicodeEncodeError:
        encoded = text.encode("ascii", "replace").decode("ascii")
        print(encoded)


async def demo_valuation(ticker: str, skip_monte_carlo: bool = False) -> None:
    from telegram_bot import ValuationPipeline
    report = await ValuationPipeline.run(ticker, skip_monte_carlo=skip_monte_carlo)
    safe_print("=" * 80)
    safe_print(report)
    safe_print("=" * 80)


def run_tests() -> int:
    import subprocess
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", "-v", "--tb=short"],
        cwd=str(ROOT),
    )
    return result.returncode


def print_help() -> None:
    safe_print("""
估值引擎 — Telegram Bot

用法：
  python main.py                 启动 Telegram Bot（轮询模式）
  python main.py bot             同上
  python main.py demo <代码>      运行演示估值并输出到控制台
  python main.py demo_fast <代码>  跳过蒙特卡洛的快速演示
  python main.py test_demo        运行 AAPL、MSFT、NVDA 的演示
  python main.py test            运行 pytest 测试套件
  python main.py help            显示帮助

示例：
  python main.py demo AAPL
  python main.py demo_fast NVDA
  python main.py test
""")


def main() -> int:
    args = sys.argv[1:]
    cmd = args[0].lower() if args else "bot"

    if cmd in ("help", "-h", "--help"):
        print_help()
        return 0

    if cmd == "bot":
        from telegram_bot import TelegramBotRunner
        bot = TelegramBotRunner()
        try:
            bot.run_polling()
            return 0
        except KeyboardInterrupt:
            log.info("Bot stopped by user.")
            return 0
        except Exception as e:
            log.exception(f"Bot failed to start: {e}")
            safe_print(f"\nERROR: {e}")
            safe_print("TIP: Copy .env.example to .env and set TELEGRAM_BOT_TOKEN")
            return 1

    if cmd == "demo":
        ticker = args[1] if len(args) > 1 else "AAPL"
        asyncio.run(demo_valuation(ticker, skip_monte_carlo=False))
        return 0

    if cmd == "demo_fast":
        ticker = args[1] if len(args) > 1 else "AAPL"
        asyncio.run(demo_valuation(ticker, skip_monte_carlo=True))
        return 0

    if cmd == "test_demo":
        async def run_all():
            for t in ["AAPL", "MSFT", "NVDA"]:
                await demo_valuation(t, skip_monte_carlo=True)
        asyncio.run(run_all())
        return 0

    if cmd == "test":
        return run_tests()

    print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
