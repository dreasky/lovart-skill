#!/usr/bin/env python3
"""
Camoufox-based Lovart.ai Authentication

Uses Camoufox (Firefox-based anti-detection browser) which reliably passes
Cloudflare Turnstile verification — Chromium-based tools are detected by CF.

Opens browser for manual login (email + password + email verification code).
Waits for redirect to /zh/home, then extracts and saves session cookies.
"""

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any

LOVART_URL = "https://www.lovart.ai/zh"
LOVART_HOME_URL = "https://www.lovart.ai/zh/home"

AUTH_FILE = Path(__file__).parent / "data" / "auth" / "lovart.json"


def _extract_storage_state(context) -> Dict[str, Any]:
    cookies = context.cookies()

    origins = []
    try:
        pages = context.pages
        page = pages[0] if pages else None
        if page and "lovart.ai" in page.url:
            local_storage = page.evaluate("() => Object.entries(localStorage)")
            origins.append({
                "origin": "https://www.lovart.ai",
                "localStorage": [{"name": k, "value": v} for k, v in local_storage]
            })
    except Exception:
        pass

    return {"cookies": cookies, "origins": origins}


def save_auth_state(storage_state: Dict[str, Any]) -> None:
    AUTH_FILE.parent.mkdir(parents=True, exist_ok=True)
    storage_state["updated_at"] = datetime.now(timezone.utc).isoformat()
    with open(AUTH_FILE, "w") as f:
        json.dump(storage_state, f, indent=2)
    print(f"   Session saved to {AUTH_FILE}", flush=True)


def load_auth_state() -> Optional[Dict[str, Any]]:
    """Load saved session from disk. Returns None if not found."""
    if not AUTH_FILE.exists():
        return None
    with open(AUTH_FILE, "r") as f:
        return json.load(f)


def authenticate(timeout_seconds: int = 600) -> tuple[bool, Optional[Dict[str, Any]]]:
    """
    Open Camoufox (Firefox) for manual Lovart.ai login.

    Camoufox uses Firefox with randomized fingerprints specifically tuned
    to pass Cloudflare Turnstile without user interaction.

    Returns: (success, storage_state)
    """
    try:
        from camoufox.sync_api import Camoufox
    except ImportError:
        print("Camoufox not installed. Run: pip install camoufox[geoip] && python -m camoufox fetch")
        return False, None

    print("Opening browser for Lovart.ai authentication...", flush=True)
    print("   (Camoufox Firefox — Cloudflare compatible)", flush=True)

    try:
        with Camoufox(headless=False) as browser:
            context = browser.new_context()
            page = context.new_page()

            print(f"Navigating to {LOVART_URL}...", flush=True)
            page.goto(LOVART_URL, wait_until="domcontentloaded")

            print(flush=True)
            print("Please complete login in the browser:", flush=True)
            print("  1. Click '开始体验'", flush=True)
            print("  2. Enter email + password", flush=True)
            print("  3. Enter verification code from email", flush=True)
            print("  (DO NOT close the browser)", flush=True)
            print(flush=True)

            print("   (Type 'ok' + Enter here anytime to manually confirm login)", flush=True)
            print(flush=True)

            import threading
            manual_confirm = threading.Event()

            def _wait_for_input():
                try:
                    while not manual_confirm.is_set():
                        line = input()
                        if line.strip().lower() in ("ok", "y", "yes", "done"):
                            manual_confirm.set()
                            break
                except Exception:
                    pass

            input_thread = threading.Thread(target=_wait_for_input, daemon=True)
            input_thread.start()

            start_time = time.time()
            authenticated = False
            last_url = ""

            while time.time() - start_time < timeout_seconds:
                try:
                    if manual_confirm.is_set():
                        print("   Manual confirm received.", flush=True)
                        authenticated = True
                        break

                    pages = context.pages
                    if not pages:
                        print("Browser was closed.", flush=True)
                        break

                    for pg in pages:
                        try:
                            # Use evaluate() to get SPA route URL (history.pushState)
                            # page.url only tracks real navigations, not client-side routing
                            url = pg.evaluate("location.href")
                            if url != last_url:
                                print(f"   URL: {url}", flush=True)
                                last_url = url
                            if "/zh/home" in url:
                                print("   Detected /zh/home — login successful!", flush=True)
                                page = pg
                                time.sleep(2)
                                authenticated = True
                                break
                        except Exception:
                            continue

                    if authenticated:
                        break

                    time.sleep(0.5)

                except Exception as e:
                    if "closed" in str(e).lower() or "target" in str(e).lower():
                        print("Browser was closed.", flush=True)
                    else:
                        print(f"Error: {e}", flush=True)
                    break

            storage_state = None
            if authenticated:
                print("Authentication successful!", flush=True)
                try:
                    storage_state = _extract_storage_state(context)
                except Exception:
                    print("   Could not extract session.", flush=True)
            else:
                print("Authentication timed out or cancelled.", flush=True)

            return authenticated, storage_state

    except Exception as e:
        print(f"Authentication error: {e}", flush=True)
        return False, None


if __name__ == "__main__":
    import sys

    success, storage_state = authenticate()
    if success and storage_state:
        save_auth_state(storage_state)
    sys.exit(0 if success else 1)
