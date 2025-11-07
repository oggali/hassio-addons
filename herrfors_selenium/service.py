import json
import os
import time
from hassapi import HassAPI   # comes built-in when homeassistant_api is enabled

REFRESH_TRIGGER_FILE = "/share/herrfors_refresh_now"

def main():
    ha = HassAPI()  # Auto-auth to supervisor
    print("🔌 Registering Home Assistant service: herrfors_selenium.refresh_now")

    @ha.service("herrfors_selenium", "refresh_now")
    def refresh_now_call(data):
        print("⚡ Manual refresh requested by HA service")
        with open(REFRESH_TRIGGER_FILE, "w") as f:
            f.write(str(time.time()))
        return {"status": "ok"}

    ha.run_forever()

if __name__ == "__main__":
    main()
