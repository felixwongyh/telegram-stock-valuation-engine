import sys
from pathlib import Path

ROOT = Path(__file__).parent.resolve()
sys.path.insert(0, str(ROOT))

print("=" * 70)
print("Telegram Bot Configuration Verification")
print("=" * 70)

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

print(f"\n[1/3] Environment Variables Check")
token_ok = bool(TELEGRAM_BOT_TOKEN)
print(f"  TELEGRAM_BOT_TOKEN: {'OK' if token_ok else 'FAIL - empty'}")
if token_ok:
    print(f"    Length: {len(TELEGRAM_BOT_TOKEN)} chars")
    print(f"    Preview: {TELEGRAM_BOT_TOKEN[:15]}...{TELEGRAM_BOT_TOKEN[-6:]}")
else:
    print(f"    [ERROR] Token is empty!")

chat_ok = bool(TELEGRAM_CHAT_ID)
print(f"  TELEGRAM_CHAT_ID: {'OK' if chat_ok else 'WARN - empty'}")
if chat_ok:
    print(f"    Value: {TELEGRAM_CHAT_ID}")

if not token_ok:
    sys.exit(1)

print(f"\n[2/3] TelegramBotRunner Initialization Check")
try:
    from telegram_bot import TelegramBotRunner
    bot = TelegramBotRunner()
    print(f"  Init: OK")
    token_passed = bool(bot.token) and bot.token != "your_telegram_bot_token_here"
    print(f"  Token passed: {'OK' if token_passed else 'FAIL'}")
    
    if not token_passed:
        print("  [ERROR] Token not loaded correctly!")
        sys.exit(1)
except Exception as e:
    print(f"  [ERROR] Init failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print(f"\n[3/3] App Build Check (no network)")
try:
    app = bot._build_app()
    print(f"  Application build: OK")
    print(f"  Handlers registered: {len(app.handlers)}")
    print(f"  Commands: /start, /help, /about, /val, /val_fast")
except Exception as e:
    print(f"  [ERROR] App build failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print("\n" + "=" * 70)
print("SUCCESS! All checks passed. Token and config loaded correctly.")
print("=" * 70)
print("\nNext steps:")
print("   Start bot:  python main.py bot")
print("   Test demo:  python main.py demo_fast AAPL")
print("\nNote: Full valuation needs numpy/scipy/pandas/yfinance installed.")
print("   If compilation errors on Python 3.13, use Python 3.11/3.12 or")
print("   install pre-built wheels.")
