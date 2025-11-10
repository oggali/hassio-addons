from typing import Optional
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
# from webdriver_manager.chrome import ChromeDriverManager

import time

LOGIN_URL = "https://identity.herrfors.fi/?locale=fi-FI"
PORTAL_URL = "https://portal.herrfors.fi/fi-FI/charts"

def get_herrfors_session_token(email: str, password: str, headless: bool = True, verbose: bool = True) -> Optional[str]:
    if not email or not password:
        if verbose: print("Missing email/password.")
        return None

    options = Options()
    try:
        if headless:
            options.add_argument("--headless=new")
    except Exception:
        if headless:
            options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-infobars")

    options.add_argument("--disable-software-rasterizer")

    # service = Service(ChromeDriverManager().install())
    service = Service("/usr/lib/chromium/chromedriver")
    driver = webdriver.Chrome(service=service, options=options)

    wait = WebDriverWait(driver, 20)

    try:
        if verbose: print("Opening identity page...")
        driver.get(LOGIN_URL)
        time.sleep(1.5)

        # username
        username_present = wait.until(EC.presence_of_element_located((By.NAME, "username")))
        wait.until(lambda d: username_present.is_displayed() and username_present.is_enabled())
        driver.execute_script("""
            const el = document.querySelector('input[name="username"]');
            if (el) { el.focus(); el.value = arguments[0]; el.dispatchEvent(new Event('input', {bubbles: true})); }
        """, email)
        time.sleep(0.3)
        if verbose: print("username inserted...")

        # password
        password_present = wait.until(EC.presence_of_element_located((By.NAME, "password")))
        if verbose: print("Waiting password field...")
        wait.until(lambda d: password_present.is_displayed() and password_present.is_enabled())
        driver.execute_script("""
            const el = document.querySelector('input[name="password"]');
            if (el) { el.focus(); el.value = arguments[0]; el.dispatchEvent(new Event('input', {bubbles: true})); }
        """, password)
        time.sleep(0.3)

        if verbose: print("password inserted...")
        # trigger validation
        driver.execute_script("""
            const pw = document.querySelector('input[name="password"]');
            if (pw) pw.dispatchEvent(new KeyboardEvent('keydown', {key:'Enter', bubbles:true}));
        """)
        time.sleep(0.25)

        # submit
        if verbose: print("Submitting login (JS click)...")
        driver.execute_script("""
            const btn = document.querySelector('button[type="submit"]');
            if (btn) {
                btn.scrollIntoView({behavior:'instant', block:'center'});
                btn.focus();
                btn.click();
                btn.dispatchEvent(new MouseEvent('click', {bubbles:true, cancelable:true, view:window}));
            }
        """)
        time.sleep(4)

        # wait for cookie or portal
        try:
            WebDriverWait(driver, 40).until(
                lambda d: "portal.herrfors.fi" in d.current_url
                or any("session" in c["name"].lower() for c in d.get_cookies())
            )
        except Exception:
            if verbose: print("Redirect/cookie not detected in wait; trying portal page load.")

        try:
            driver.get(PORTAL_URL)
            time.sleep(4)
        except:
            time.sleep(2)

        cookies = driver.get_cookies()
        if verbose: print("Cookies:", [c["name"] for c in cookies])
        for c in cookies:
            name = c.get("name", "")
            if "__Secure-next-auth.session-token" in name or "next-auth.session-token" in name or "session-token" in name:
                if verbose: print("Found session cookie:", name)
                return c.get("value")

        if verbose: print("No session cookie found.")
        return None

    except Exception as e:
        if verbose: print("Login error:", e)
        return None

    finally:
        driver.quit()
        if verbose: print("Browser closed.")
