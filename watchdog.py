"""
watchdog.py — Auto-restarts the bot if it crashes. Runs 24/7.
This is what Windows Task Scheduler launches at startup.
"""

import subprocess
import time
import sys
import os
from datetime import datetime, timezone, timedelta

IST = timezone(timedelta(hours=5, minutes=30))
PYTHON = r"C:\Users\User\AppData\Local\Programs\Python\Python312\python.exe"
BOT_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(BOT_DIR, "data", "bot_log.txt")

os.makedirs(os.path.join(BOT_DIR, "data"), exist_ok=True)


def log(msg):
    now = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{now}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def run():
    log("=" * 50)
    log("  WhatsApp Bot Watchdog Started")
    log("  Bot will restart automatically if it crashes")
    log("=" * 50)

    restart_count = 0

    while True:
        try:
            log(f"Starting bot (attempt #{restart_count + 1})...")

            env = os.environ.copy()
            env["PYTHONUTF8"] = "1"

            process = subprocess.Popen(
                [PYTHON, "-u", "whatsapp_web_engine.py"],
                cwd=BOT_DIR,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                encoding="utf-8",
                errors="replace",
            )

            # Stream bot output to our log
            for line in process.stdout:
                line = line.rstrip()
                if line:
                    log(f"  BOT | {line}")

            process.wait()
            exit_code = process.returncode

            if exit_code == 0:
                log("Bot exited cleanly.")
            else:
                log(f"Bot crashed (exit code {exit_code}). Restarting in 10 seconds...")

            restart_count += 1
            time.sleep(10)

        except KeyboardInterrupt:
            log("Watchdog stopped by user.")
            break
        except Exception as e:
            log(f"Watchdog error: {e}. Retrying in 15 seconds...")
            time.sleep(15)


if __name__ == "__main__":
    run()
