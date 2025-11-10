import os
import time
import threading
from datetime import datetime, time as dtime, timedelta, timezone
import json
from pathlib import Path
import pytz
import requests

from refresh_server import start_server, refresh_queue
from herrfors_session import get_herrfors_session_token

EMAIL = os.getenv("email")
PASSWORD = os.getenv("password")
REFRESH_INTERVAL = int(os.getenv("refresh_interval_minutes", "360"))
WINDOW_START = os.getenv("refresh_window_start", "08:00")
WINDOW_END = os.getenv("refresh_window_end", "12:00")

TOKEN_FILE = os.getenv("token_file")

RUN_IN_START = bool(os.getenv("run_immediately", "false"))


def log(msg):
    print(f"[Herrfors] {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S%z')} {msg}", flush=True)


def parse_time(tstr):
    h, m = map(int, tstr.split(":"))
    return dtime(hour=h, minute=m)


WIN_START = parse_time(WINDOW_START)
WIN_END = parse_time(WINDOW_END)


def fetch_expiration(session_cookie: str) -> str | None:
    try:
        url = "https://portal.herrfors.fi/api/auth/session"
        r = requests.get(url, cookies={"__Secure-next-auth.session-token": session_cookie}, timeout=10)
        r.raise_for_status()
        j = r.json()
        return j.get("expires")
    except Exception as e:
        print("Error fetching expiry:", e)
        return None

def fetch_token(manual_override=False):

    if not token_valid() or manual_override:
        log(f"Manually override {manual_override}")
        log("Starting Selenium token fetch...")

        raw_token = get_herrfors_session_token(EMAIL, PASSWORD, True, True)
        expires = fetch_expiration(raw_token)
        if not expires:
            print("Could not determine token expiry; will still store token without expires.")
            expires = None

        ts = datetime.now(pytz.UTC).isoformat(timespec="seconds")

        from decode_encode_token import encrypt_token
        encrypted = encrypt_token(raw_token, EMAIL, PASSWORD)
        wrapped = f"{ts}:{encrypted}"

        payload = {
            "token_timestamp": ts,
            "expires": expires,
            "token": wrapped
        }
        Path(TOKEN_FILE).write_text(json.dumps(payload, indent=2))
        print("Saved encrypted token to:", TOKEN_FILE)
    else:
        log("Valid token found from file, no need to fetch it.")


def token_valid():
    if not os.path.exists(TOKEN_FILE):
        log("⚠️ No token file found.")
        return False

    with open(TOKEN_FILE, "r") as f:
        token_data = json.load(f)

    try:
        exp = token_data.get("expires")
        if not exp:
            return False
        dt = datetime.fromisoformat(exp.replace("Z", "+00:00"))
        return datetime.now(timezone.utc) + timedelta(seconds=REFRESH_INTERVAL) < dt

    except Exception as ex:
        log(f"⚠️ Token check failed: {ex}")
        return False

def within_refresh_window():
    now = datetime.now().time()
    # standard range: start < now < end
    if WIN_START < WIN_END:
        return WIN_START <= now <= WIN_END
    # overnight crossing window (e.g. 22:00-04:00)
    return now >= WIN_START or now <= WIN_END



def background_worker():
    if RUN_IN_START:
        fetch_token()
    while True:
        try:
            # Manual refresh always bypasses time window
            if not refresh_queue.empty():
                refresh_queue.get()
                log("🔄 Manual refresh request received — window ignored.")
                fetch_token(True)
                continue

            # Automatic refresh respects time window
            elif within_refresh_window():
                log("⏰ Inside refresh window — performing scheduled refresh.")
                fetch_token(False)
                time.sleep(REFRESH_INTERVAL)
            else:
                log("⛔ Outside refresh window — skipping refresh.")
                time.sleep(REFRESH_INTERVAL)

            time.sleep(60)

        except Exception as ex:
            log(f"Error: {ex}")
            time.sleep(60)


threading.Thread(target=start_server, daemon=True).start()
background_worker()
