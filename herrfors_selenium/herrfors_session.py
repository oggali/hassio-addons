from typing import Optional
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
import time
import os
import requests

LOGIN_URL = "https://identity.herrfors.fi/?locale=fi-FI"
PORTAL_URL = "https://portal.herrfors.fi/fi-FI/charts"

def get_herrfors_session_token(email: str, password: str, headless: bool = True, verbose: bool = True) -> Optional[str]:
    if not email or not password:
        if verbose: print("Missing email or password.")
        return None

    options = Options()
    # use new headless if available
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
    # Recommended for headless stability
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-infobars")
    # Use system chromium
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    wait = WebDriverWait(driver, 20)

    try:
        if verbose: print("Opening identity page...")
        driver.get(LOGIN_URL)
        time.sleep(1.5)

        # Wait for username input presence & visible
        username_present = wait.until(EC.presence_of_element_located((By.NAME, "username")))
        wait.until(lambda d: username_present.is_displayed() and username_present.is_enabled())

        # Fill username using JS (works for React controlled inputs)
        driver.execute_script("""
            const el = document.querySelector('input[name="username"]');
            if (el) { el.focus(); el.value = arguments[0]; el.dispatchEvent(new Event('input', {bubbles: true})); }
        """, email)
        time.sleep(0.3)

        # Wait for password
        password_present = wait.until(EC.presence_of_element_located((By.NAME, "password")))
        wait.until(lambda d: password_present.is_displayed() and password_present.is_enabled())

        driver.execute_script("""
            const el = document.querySelector('input[name="password"]');
            if (el) { el.focus(); el.value = arguments[0]; el.dispatchEvent(new Event('input', {bubbles: true})); }
        """, password)
        time.sleep(0.3)

        # Trigger enter/validation
        driver.execute_script("""
            const pw = document.querySelector('input[name="password"]');
            if (pw) pw.dispatchEvent(new KeyboardEvent('keydown', {key:'Enter', bubbles:true}));
        """)
        time.sleep(0.25)

        # Submit via JS click that generates real events
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
        time.sleep(4)  # allow submission to proceed

        # Wait for portal or cookie to appear
        try:
            WebDriverWait(driver, 40).until(
                lambda d: "portal.herrfors.fi" in d.current_url
                or any("session" in c["name"].lower() for c in d.get_cookies())
            )
        except Exception:
            # continue to next step and explicitly open portal
            if verbose: print("Redirect/cookie not detected in wait; trying to load portal directly.")

        # Open portal page to ensure cookie gets set on portal domain
        try:
            driver.get(PORTAL_URL)
            time.sleep(4)
        except Exception:
            time.sleep(2)

        # collect cookies and find likely session token
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
