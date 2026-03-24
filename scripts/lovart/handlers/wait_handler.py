"""
Wait handler for image waiting and download.
"""

import time
from pathlib import Path
from typing import Optional

from ..models import Job, JobStatus
from ..services import CanvasService, JobStore
from .base import BaseHandler, HandlerContext, HandlerResult


class WaitHandler(BaseHandler):
    """
    Handler for waiting on image generation and downloading.

    Responsibilities:
    - Check image status
    - Download completed images
    - Wait for generating images
    - Mark failed on timeout/error
    """

    def __init__(
        self,
        store: JobStore,
        downloader,  # ImageDownloader
        images_dir: Path,
        timeout: int = 300,  # Max wait time in seconds
        poll_interval: int = 10,
    ):
        super().__init__(store)
        self.downloader = downloader
        self.images_dir = images_dir
        self.timeout = timeout
        self.poll_interval = poll_interval

    def _do_execute(self, context: HandlerContext) -> HandlerResult:
        """Execute wait and download logic."""
        job = context.job
        page = context.page_factory()

        try:
            canvas = CanvasService(page)
            canvas.open_project(job.project_id)
            canvas.dismiss_dialog()
            page.wait_for_timeout(2000)

            print(f"  [{job.stem}] waiting for image (timeout={self.timeout}s)...", flush=True)

            # Poll for image ready
            elapsed = 0

            while elapsed < self.timeout:
                status = canvas.check_image_status()

                if status == "ready":
                    path = self._try_download(canvas, job)
                    if path:
                        job.touch(status=JobStatus.DONE, image_path=str(path))
                        return HandlerResult(
                            job=job,
                            status_changed=True,
                        )

                elif status == "generating":
                    print(f"  [{job.stem}] image generating...", flush=True)
                    remaining = self.timeout - elapsed
                    if canvas.wait_for_generation_complete(timeout=min(remaining, 300)):
                        # Generation complete, wait a moment for image to render
                        print(f"  [{job.stem}] generation complete, checking image...", flush=True)
                        time.sleep(2)
                        status = canvas.check_image_status()
                        if status == "ready":
                            path = self._try_download(canvas, job)
                            if path:
                                job.touch(status=JobStatus.DONE, image_path=str(path))
                                return HandlerResult(
                                    job=job,
                                    status_changed=True,
                                )
                        # If not ready yet, continue polling

                time.sleep(self.poll_interval)
                elapsed += self.poll_interval

            # Timeout reached
            job.touch(status=JobStatus.FAILED, error=f"wait timeout after {self.timeout}s")
            return HandlerResult(
                job=job,
                status_changed=True,
                failed=True,
            )

        except Exception as e:
            job.touch(status=JobStatus.FAILED, error=f"wait error: {e}")
            return HandlerResult(
                job=job,
                status_changed=True,
                failed=True,
            )

        finally:
            try:
                page.close()
            except Exception:
                pass

    def _try_download(self, canvas: CanvasService, job: Job) -> Optional[Path]:
        """Try to download image from canvas."""
        path = self.downloader.try_download_from_canvas(
            canvas.page,
            self.images_dir / f"{job.stem}.png",
            job.stem,
        )
        if path:
            print(f"  [{job.stem}] downloaded successfully.", flush=True)
        return path