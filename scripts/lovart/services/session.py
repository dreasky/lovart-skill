"""
Browser session management.
"""

from pathlib import Path
from typing import Optional

from ..auth import AuthState, AuthStore, Authenticator


class LovartSession:
    """
    Context manager that provides an authenticated Lovart.ai browser page.

    Loads session from disk. If session is missing or expired, re-authenticates.

    Example:
        with LovartSession() as session:
            session.page.goto("https://www.lovart.ai/zh/home")
            # interact with page
    """

    HOME_URL = "https://www.lovart.ai/zh/home"

    def __init__(
        self,
        headless: bool = False,
        reauth_if_needed: bool = True,
        auth_file: Optional[Path] = None,
    ):
        self.headless = headless
        self.reauth_if_needed = reauth_if_needed
        self._auth_file = auth_file or Path(__file__).parent.parent.parent / "data" / "auth" / "lovart.json"
        self._browser_cm = None
        self._context = None
        self.page = None

    def __enter__(self):
        self._start()
        return self

    def __exit__(self, *_):
        self.close()

    def _start(self):
        from camoufox.sync_api import Camoufox

        store = AuthStore(self._auth_file)
        state = store.load()

        if not state and self.reauth_if_needed:
            print("No saved session found. Starting authentication...", flush=True)
            authenticator = Authenticator()
            success, state = authenticator.authenticate()
            if success and state:
                store.save(state)
            else:
                raise RuntimeError("Authentication failed.")

        if not state:
            raise RuntimeError(f"No auth session found at {self._auth_file}. Run patchright_auth.py first.")

        self._browser_cm = Camoufox(headless=self.headless)
        browser = self._browser_cm.__enter__()
        self._context = browser.new_context(viewport={"width": 600, "height": 600})

        # Restore cookies from saved session
        if state.cookies:
            self._context.add_cookies([c for c in state.cookies if isinstance(c, dict)])

        self.page = self._context.new_page()

    def close(self):
        if self._context:
            self._context.close()
        if self._browser_cm:
            self._browser_cm.__exit__(None, None, None)

    def new_page(self):
        """Create and return a new page from the shared browser context."""
        return self._context.new_page()

    def is_logged_in(self) -> bool:
        """Navigate to home and check if session is still valid."""
        try:
            self.page.goto(self.HOME_URL, wait_until="domcontentloaded", timeout=15000)
            return "/zh/home" in self.page.url
        except Exception:
            return False