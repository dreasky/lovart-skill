"""
Canvas page operations service.
"""

import base64
import re
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, urlparse

from ..config import Config
from ..models import Job, JobStatus


class CanvasService:
    """Service for interacting with Lovart canvas pages."""

    def __init__(self, page):
        self.page = page

    # -----------------------------------------------------------------------
    # Page Navigation
    # -----------------------------------------------------------------------

    def open_project(self, project_id: Optional[str] = None) -> Optional[str]:
        """
        Open canvas page. Returns new project_id if creating new project.

        New project: go to /canvas?newProject=true, wait for canvas to load.
        Existing project: go directly to /canvas?projectId=...
        """
        if project_id:
            url = f"{Config.CANVAS_URL}?projectId={project_id}"
            print(f"  Resuming project: {url}", flush=True)
            self.page.goto(url, wait_until="domcontentloaded", timeout=Config.PAGE_LOAD_TIMEOUT)
            return None
        else:
            print(f"  New project: {Config.NEW_PROJECT_URL}", flush=True)
            self.page.goto(Config.NEW_PROJECT_URL, wait_until="domcontentloaded", timeout=Config.PAGE_LOAD_TIMEOUT)
            print("  Waiting for projectId in URL...", flush=True)
            self.page.wait_for_function(
                "() => new URLSearchParams(location.search).get('projectId')",
                timeout=Config.PAGE_LOAD_TIMEOUT,
            )
            pid = self._extract_project_id(self.page.url)
            if not pid:
                raise RuntimeError(f"No projectId in URL after canvas loaded: {self.page.url}")
            print(f"  Project ID: {pid}", flush=True)
            return pid

    @staticmethod
    def _extract_project_id(url: str) -> Optional[str]:
        """Extract project ID from URL."""
        qs = parse_qs(urlparse(url).query)
        if qs.get("projectId"):
            return qs["projectId"][0]
        m = re.search(r"projectId=([a-zA-Z0-9]+)", url)
        return m.group(1) if m else None

    # -----------------------------------------------------------------------
    # Dialog & Input
    # -----------------------------------------------------------------------

    def dismiss_dialog(self) -> None:
        """Close any blocking dialog before interacting."""
        try:
            self.page.wait_for_selector("[role='dialog'][data-state='open']", timeout=5000)
            dialog = self.page.locator("[role='dialog'][data-state='open']")
            print(f"  dismiss_dialog: found {dialog.count()} open dialog(s)", flush=True)
            close_btn = dialog.locator("button[aria-label='Close']")
            print(f"  dismiss_dialog: close buttons found: {close_btn.count()}", flush=True)
            close_btn.click()
            self.page.wait_for_selector(
                "[role='dialog'][data-state='open']", state="hidden", timeout=5000
            )
            print("  dismiss_dialog: dialog closed", flush=True)
            self.page.wait_for_selector(
                "div[data-state='open'][aria-hidden='true']", state="hidden", timeout=5000
            )
            print("  dismiss_dialog: overlay cleared", flush=True)
        except Exception as e:
            print(f"  dismiss_dialog: {e}", flush=True)

    def set_project_name(self, name: str) -> None:
        """Set the project name input field."""
        try:
            inp = self.page.locator(Config.PROJECT_NAME_INPUT)
            inp.wait_for(timeout=5000)
            inp.evaluate(
                "(el, name) => { el.removeAttribute('readonly'); el.value = name; }", name
            )
            inp.dispatch_event("input")
            inp.dispatch_event("change")
            inp.click()
            inp.press("Tab")
            self.page.wait_for_timeout(500)
            print(f"  Project name set: {name}", flush=True)
        except Exception as e:
            print(f"  set_project_name: {e}", flush=True)

    # -----------------------------------------------------------------------
    # Prompt
    # -----------------------------------------------------------------------

    @staticmethod
    def read_prompt(path: Path) -> str:
        """Read and clean markdown prompt file."""
        text = path.read_text(encoding="utf-8")
        text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
        text = re.sub(r"\*{1,2}(.+?)\*{1,2}", r"\1", text)
        text = re.sub(r"`(.+?)`", r"\1", text)
        return text.strip()

    def send_prompt(self, prompt_text: str) -> None:
        """Send prompt to the chat input."""
        print("  Waiting for chat input...", flush=True)
        self.page.wait_for_selector(Config.CHAT_INPUT_SELECTOR, timeout=Config.CHAT_INPUT_TIMEOUT)
        self.page.locator(Config.CHAT_INPUT_SELECTOR).click()
        self.page.wait_for_timeout(300)

        self.page.evaluate(
            """(text) => {
                const editor = document.querySelector('[data-lexical-editor="true"]');
                if (!editor) return;
                editor.focus();
                const p = editor.querySelector('p');
                if (p) {
                    p.innerHTML = '';
                    const range = document.createRange();
                    const sel = window.getSelection();
                    range.selectNodeContents(p);
                    range.collapse(false);
                    sel.removeAllRanges();
                    sel.addRange(range);
                }
                document.execCommand('insertText', false, text);
            }""",
            prompt_text,
        )
        print(f"  Prompt pasted ({len(prompt_text)} chars)", flush=True)
        self.page.keyboard.press("Enter")
        print("  Prompt sent.", flush=True)

    # -----------------------------------------------------------------------
    # Image Download
    # -----------------------------------------------------------------------

    def try_download_image(self, dest_path: Path) -> Optional[Path]:
        """
        Non-blocking check: download image if ready.
        Returns path if downloaded, None if not ready.
        """
        cards = self.page.locator(Config.IMAGE_CARD_SELECTOR).all()
        if not cards:
            return None
        img = cards[-1].locator("img[src*='/artifacts/agent/']").first
        if img.count() == 0:
            return None
        src = img.get_attribute("src") or ""
        if not src:
            return None
        return self._do_download(src, dest_path)

    def wait_and_download(self, dest_path: Path, timeout: int = None) -> bool:
        """
        Blocking wait for image, then download.
        Returns True if successful.
        """
        timeout = timeout or Config.IMAGE_WAIT_TIMEOUT
        Config.IMAGES_DIR.mkdir(parents=True, exist_ok=True)
        print(f"  Waiting for image generation (timeout={timeout}s)...", flush=True)

        try:
            self.page.wait_for_selector(Config.IMAGE_CARD_SELECTOR, timeout=timeout * 1000)
        except Exception:
            print("  Timed out waiting for image-generation-card.", flush=True)
            return False

        cards = self.page.locator(Config.IMAGE_CARD_SELECTOR).all()
        last_card = cards[-1]
        print(f"  Image card found ({len(cards)} total), waiting for img src...", flush=True)

        img_locator = last_card.locator("img[src*='/artifacts/agent/']").first
        img_locator.wait_for(timeout=300000)

        src = img_locator.get_attribute("src") or ""
        try:
            self._do_download(src, dest_path)
            return True
        except Exception as e:
            print(f"  Download error: {e}", flush=True)
            return False

    def _do_download(self, src: str, dest_path: Path) -> Path:
        """Download image from src URL to dest_path."""
        m = re.search(r"/artifacts/agent/([^?]+)", src)
        if not m:
            raise ValueError(f"Could not extract filename from src: {src}")
        filename = m.group(1)
        download_url = f"{Config.DOWNLOAD_BASE}{filename}"
        ext = Path(filename).suffix or ".png"
        final_path = dest_path.with_suffix(ext)
        Config.IMAGES_DIR.mkdir(parents=True, exist_ok=True)

        data_b64 = self.page.evaluate(
            """async (url) => {
                const resp = await fetch(url);
                if (!resp.ok) throw new Error('HTTP ' + resp.status);
                const blob = await resp.blob();
                return await new Promise((resolve, reject) => {
                    const reader = new FileReader();
                    reader.onload = () => resolve(reader.result.split(',')[1]);
                    reader.onerror = reject;
                    reader.readAsDataURL(blob);
                });
            }""",
            download_url,
        )
        final_path.write_bytes(base64.b64decode(data_b64))
        print(f"  Saved: {final_path}", flush=True)
        return final_path

    # -----------------------------------------------------------------------
    # Paywall Check
    # -----------------------------------------------------------------------

    def check_paywall(self) -> bool:
        """Check if paywall is present (insufficient credits)."""
        return self.page.locator("[data-testid='paywall-container']").count() > 0

    # -----------------------------------------------------------------------
    # Generation State
    # -----------------------------------------------------------------------

    def is_generating(self) -> bool:
        """Check if image is currently being generated."""
        # Look for loading/generating indicators
        loading_selectors = [
            "[data-testid='image-generation-loading']",
            ".generating",
            "[class*='loading']",
            "[class*='spinner']",
        ]
        for selector in loading_selectors:
            if self.page.locator(selector).count() > 0:
                return True
        return False

    def wait_for_current_generation(self, timeout: int = 300) -> bool:
        """
        Wait for current generation to complete (if any).
        Returns True if generation completed (or no generation in progress).
        """
        if not self.is_generating():
            return True

        print("  Image generating, waiting for completion...", flush=True)
        try:
            # Wait for loading indicators to disappear
            self.page.wait_for_selector(
                "[data-testid='image-generation-loading']",
                state="hidden",
                timeout=timeout * 1000,
            )
            return True
        except Exception:
            return False

    def check_image_status(self) -> str:
        """
        Check current image status on the page.
        Returns: 'ready', 'generating', or 'none'
        """
        # Check for completed image first
        cards = self.page.locator(Config.IMAGE_CARD_SELECTOR).all()
        if cards:
            img = cards[-1].locator("img[src*='/artifacts/agent/']").first
            if img.count() > 0 and img.get_attribute("src"):
                return "ready"

        # Check for generating state
        if self.is_generating():
            return "generating"

        return "none"