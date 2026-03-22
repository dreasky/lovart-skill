"""
Image waiting and retry logic.
"""

import re
import time
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from ..config import Config
from ..models import Job

if TYPE_CHECKING:
    from ..services import CanvasService


def read_prompt(path: Path) -> str:
    """Read and clean markdown prompt file."""
    text = path.read_text(encoding="utf-8")
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"\*{1,2}(.+?)\*{1,2}", r"\1", text)
    text = re.sub(r"`(.+?)`", r"\1", text)
    return text.strip()


class ImageWaiter:
    """
    Handles image waiting with retry logic.

    Flow: close page → wait → reopen → check → download or resubmit
    """

    def __init__(
        self,
        wait_seconds: int = 180,
        max_retries: int = 3,
    ):
        self.wait_seconds = wait_seconds
        self.max_retries = max_retries

    def wait_and_download(
        self,
        job: Job,
        image_path: Path,
        canvas: "CanvasService",
        page_factory,
    ) -> tuple[bool, Optional[Path]]:
        """
        Wait for image with retry logic.

        Args:
            job: The job to wait for
            image_path: Where to save the image
            canvas: CanvasService instance
            page_factory: Callable that returns a new page

        Returns:
            (success, final_path)
        """
        retry_count = 0

        while retry_count < self.max_retries:
            # Wait before checking
            print(f"  [{job.stem}] waiting {self.wait_seconds}s (retry {retry_count + 1}/{self.max_retries})...", flush=True)
            time.sleep(self.wait_seconds)

            # Open page and check
            try:
                page = page_factory()
                canvas.page = page
                canvas.open_project(job.project_id)
                canvas.dismiss_dialog()
                page.wait_for_timeout(2000)  # Let page settle

                status = canvas.check_image_status()
                print(f"  [{job.stem}] image status: {status}", flush=True)

                if status == "ready":
                    result = canvas.try_download_image(image_path)
                    if result:
                        print(f"  [{job.stem}] downloaded successfully.", flush=True)
                        return True, result

                elif status == "generating":
                    # Wait for current generation
                    if canvas.wait_for_current_generation():
                        result = canvas.try_download_image(image_path)
                        if result:
                            print(f"  [{job.stem}] downloaded after generation.", flush=True)
                            return True, result

                # No image, need to resubmit
                print(f"  [{job.stem}] no image found, resubmitting...", flush=True)
                self._resubmit(job, canvas)

            except Exception as e:
                print(f"  [{job.stem}] check error: {e}", flush=True)
            finally:
                # Always close the page to free resources
                try:
                    if 'page' in locals():
                        page.close()
                except Exception:
                    pass

            retry_count += 1

        print(f"  [{job.stem}] max retries reached, keeping SUBMITTED status.", flush=True)
        return False, None

    def _resubmit(self, job: Job, canvas: "CanvasService") -> None:
        """Resubmit the prompt."""
        prompt_text = read_prompt(Path(job.prompt_file))
        canvas.send_prompt(prompt_text)
        print(f"  [{job.stem}] prompt resubmitted.", flush=True)