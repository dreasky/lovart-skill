"""
Browser-based authentication flow.
"""

import threading
import time
from typing import Optional, Tuple

from .models import AuthState


class Authenticator:
    """Orchestrates browser-based authentication for Lovart.ai."""

    # URLs
    LOVART_URL = "https://www.lovart.ai/zh"
    HOME_URL = "https://www.lovart.ai/zh/home"

    def __init__(self, timeout_seconds: int = 600):
        self.timeout = timeout_seconds

    def authenticate(self) -> Tuple[bool, Optional[AuthState]]:
        """
        Open Camoufox (Firefox) for manual Lovart.ai login.

        Camoufox uses Firefox with randomized fingerprints specifically tuned
        to pass Cloudflare Turnstile without user interaction.

        Returns: (success, auth_state)
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

                print(f"Navigating to {self.LOVART_URL}...", flush=True)
                page.goto(self.LOVART_URL, wait_until="domcontentloaded")

                self._print_instructions()

                # Manual confirmation listener
                manual_confirm = threading.Event()
                input_thread = threading.Thread(
                    target=self._wait_for_manual_input,
                    args=(manual_confirm,),
                    daemon=True,
                )
                input_thread.start()

                # Poll for authentication
                result = self._poll_for_auth(context, page, manual_confirm)
                return result

        except Exception as e:
            print(f"Authentication error: {e}", flush=True)
            return False, None

    def _print_instructions(self) -> None:
        """Print login instructions to console."""
        print(flush=True)
        print("Please complete login in the browser:", flush=True)
        print("  1. Click '开始体验'", flush=True)
        print("  2. Enter email + password", flush=True)
        print("  3. Enter verification code from email", flush=True)
        print("  (DO NOT close the browser)", flush=True)
        print(flush=True)
        print("   (Type 'ok' + Enter here anytime to manually confirm login)", flush=True)
        print(flush=True)

    def _wait_for_manual_input(self, event: threading.Event) -> None:
        """Listen for manual confirmation from stdin."""
        try:
            while not event.is_set():
                line = input()
                if line.strip().lower() in ("ok", "y", "yes", "done"):
                    event.set()
                    break
        except Exception:
            pass

    def _poll_for_auth(
        self, context, page, manual_confirm: threading.Event
    ) -> Tuple[bool, Optional[AuthState]]:
        """Poll browser pages for successful authentication."""
        start_time = time.time()
        authenticated = False
        last_url = ""
        result_page = page

        while time.time() - start_time < self.timeout:
            try:
                # Check manual confirmation
                if manual_confirm.is_set():
                    print("   Manual confirm received.", flush=True)
                    authenticated = True
                    break

                # Check browser state
                pages = context.pages
                if not pages:
                    print("Browser was closed.", flush=True)
                    break

                # Check all pages for home URL
                for pg in pages:
                    try:
                        url = pg.evaluate("location.href")
                        if url != last_url:
                            print(f"   URL: {url}", flush=True)
                            last_url = url
                        if self._is_home_url(url):
                            print("   Detected /zh/home — login successful!", flush=True)
                            result_page = pg
                            time.sleep(2)
                            authenticated = True
                            break
                    except Exception:
                        continue

                if authenticated:
                    break

                time.sleep(0.5)

            except Exception as e:
                if self._is_browser_closed_error(e):
                    print("Browser was closed.", flush=True)
                else:
                    print(f"Error: {e}", flush=True)
                break

        # Extract state if authenticated
        if authenticated:
            print("Authentication successful!", flush=True)
            try:
                state = AuthState.from_context(context)
                return True, state
            except Exception:
                print("   Could not extract session.", flush=True)
                return True, None
        else:
            print("Authentication timed out or cancelled.", flush=True)
            return False, None

    def _is_home_url(self, url: str) -> bool:
        """Check if URL indicates successful login."""
        return "/zh/home" in url

    def _is_browser_closed_error(self, error: Exception) -> bool:
        """Check if error indicates browser was closed."""
        msg = str(error).lower()
        return "closed" in msg or "target" in msg