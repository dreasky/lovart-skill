#!/usr/bin/env python3
"""
Lovart.ai Session Client

Loads saved auth session and provides a browser context ready for automation.
Usage:
    from session import LovartSession

    with LovartSession() as session:
        page = session.page
        # do stuff with page
"""

from pathlib import Path
from typing import Optional

from patchright_auth import load_auth_state, authenticate, save_auth_state, LOVART_HOME_URL

AUTH_FILE = Path(__file__).parent / "data" / "auth" / "lovart.json"


class LovartSession:
    """
    Context manager that provides an authenticated Lovart.ai browser page.

    Loads session from disk. If session is missing or expired, re-authenticates.

    Example:
        with LovartSession() as session:
            session.page.goto("https://www.lovart.ai/zh/home")
            # interact with page
    """

    def __init__(self, headless: bool = False, reauth_if_needed: bool = True):
        self.headless = headless
        self.reauth_if_needed = reauth_if_needed
        self._playwright = None
        self._context = None
        self.page = None

    def __enter__(self):
        self._start()
        return self

    def __exit__(self, *_):
        self.close()

    def _start(self):
        from camoufox.sync_api import Camoufox

        state = load_auth_state()
        if not state and self.reauth_if_needed:
            print("No saved session found. Starting authentication...", flush=True)
            success, state = authenticate()
            if success and state:
                save_auth_state(state)
            else:
                raise RuntimeError("Authentication failed.")

        if not state:
            raise RuntimeError(f"No auth session found at {AUTH_FILE}. Run patchright_auth.py first.")

        self._browser_cm = Camoufox(headless=self.headless)
        browser = self._browser_cm.__enter__()
        self._context = browser.new_context()

        # Restore cookies from saved session
        cookies = state.get("cookies", [])
        if cookies:
            self._context.add_cookies(cookies)

        self.page = self._context.new_page()

    def close(self):
        if self._context:
            self._context.close()
        if hasattr(self, "_browser_cm"):
            self._browser_cm.__exit__(None, None, None)

    def is_logged_in(self) -> bool:
        """Navigate to home and check if session is still valid."""
        try:
            self.page.goto(LOVART_HOME_URL, wait_until="domcontentloaded", timeout=15000)
            return "/zh/home" in self.page.url
        except Exception:
            return False
