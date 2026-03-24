"""
Batch executor - executes multiple jobs with controlled concurrency.
"""

import threading
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from ..handlers import HandlerContext
from ..models import Job, JobStatus
from ..services import CanvasService
from .base import BaseExecutor


class BatchExecutor(BaseExecutor):
    """
    Executor for running multiple jobs with controlled concurrency.

    Flow:
    1. Submit all jobs (each in own page)
    2. Keep pages open for waiting (max concurrent pages limited)
    3. Wait for all jobs using semaphore-based concurrency control
    4. Mark failed on timeout/error
    """

    def __init__(self, *args, max_concurrent_pages: int = 10, **kwargs):
        super().__init__(*args, **kwargs)
        self.max_concurrent_pages = max_concurrent_pages
        self._submitted: List[Tuple[Job, Path, object]] = []  # (job, image_path, page)
        self._results: Dict[str, Tuple[bool, Optional[Path], Optional[str]]] = {}  # (success, path, error)
        self._lock = threading.Lock()
        self._page_semaphore: Optional[threading.Semaphore] = None

    def execute(self, prompt_paths: List[Path]) -> List[Job]:
        """
        Execute multiple jobs with controlled concurrency.

        Args:
            prompt_paths: List of prompt file paths

        Returns:
            List of job objects after execution
        """
        # Initialize semaphore for page limit
        self._page_semaphore = threading.Semaphore(self.max_concurrent_pages)

        # Phase 1: Submit all jobs
        self._submitted = []
        for p in prompt_paths:
            self._submit_one(p)

        if not self._submitted:
            print("No jobs to wait for.", flush=True)
            return []

        # Phase 2: Wait with controlled concurrency (pages stay open)
        print(
            f"\n{len(self._submitted)} job(s) submitted. "
            f"Waiting with max {self.max_concurrent_pages} concurrent pages...",
            flush=True,
        )
        self._parallel_wait_with_pages()

        # Return all submitted jobs
        return [job for job, _, _ in self._submitted]

    def _submit_one(self, prompt_path: Path) -> Optional[Job]:
        """Submit a single job."""
        job = self._get_or_create_job(prompt_path)

        # Check if should skip
        if self._should_skip(prompt_path, job):
            print(f"\n[{job.stem}] already done, skipping.", flush=True)
            return None

        print(f"\n[{job.stem}] submitting...", flush=True)

        page = self.session.new_page()
        image_path = self.wait_handler.images_dir / f"{job.stem}.png"

        ctx = HandlerContext(
            job=job,
            page=page,
            prompt_path=prompt_path,
            image_path=image_path,
        )
        result = self.submit_handler.execute(ctx)

        # Save job status
        if result.status_changed:
            self.store.upsert(job)
            self.store.save()

        if result.job and result.job.status == JobStatus.SUBMITTED:
            with self._lock:
                self._submitted.append((result.job, image_path, page))
        else:
            # Close page if not submitted
            try:
                page.close()
            except Exception:
                pass

        return result.job

    def _parallel_wait_with_pages(self) -> None:
        """Wait for all jobs keeping pages open, with concurrency control."""
        threads = []

        for idx, (job, image_path, page) in enumerate(self._submitted):
            t = threading.Thread(
                target=self._wait_for_job_with_page,
                args=(job, image_path, page, idx),
                daemon=True,
            )
            threads.append(t)
            t.start()

        # Wait for all threads
        for t in threads:
            t.join()

        # Update job statuses based on results
        for job, _, _ in self._submitted:
            key = job.stem
            if key in self._results:
                success, path, error = self._results[key]
                if success and path:
                    job.touch(status=JobStatus.DONE, image_path=str(path))
                else:
                    job.touch(status=JobStatus.FAILED, error=error or "unknown error")
                self.store.upsert(job)
                self.store.save()

    def _wait_for_job_with_page(
        self, job: Job, image_path: Path, page, idx: int
    ) -> None:
        """Wait for a single job keeping page open (runs in thread)."""
        # Acquire semaphore to limit concurrent waiting
        self._page_semaphore.acquire()

        try:
            canvas = CanvasService(page)
            timeout = self.wait_handler.timeout
            poll_interval = self.wait_handler.poll_interval

            print(f"  [{job.stem}] waiting for image (timeout={timeout}s)...", flush=True)

            elapsed = 0
            while elapsed < timeout:
                status = canvas.check_image_status()

                if status == "ready":
                    # Try download immediately
                    path = self.wait_handler.downloader.try_download_from_canvas(
                        page, image_path, job.stem
                    )
                    if path:
                        print(f"  [{job.stem}] downloaded successfully.", flush=True)
                        with self._lock:
                            self._results[job.stem] = (True, path, None)
                        return

                elif status == "generating":
                    print(f"  [{job.stem}] image generating...", flush=True)
                    remaining = timeout - elapsed
                    if canvas.wait_for_generation_complete(timeout=min(remaining, 300)):
                        # Generation complete, immediately check and download
                        print(f"  [{job.stem}] generation complete, checking image...", flush=True)
                        # Small wait for image to render
                        time.sleep(2)
                        status = canvas.check_image_status()
                        if status == "ready":
                            path = self.wait_handler.downloader.try_download_from_canvas(
                                page, image_path, job.stem
                            )
                            if path:
                                print(f"  [{job.stem}] downloaded successfully.", flush=True)
                                with self._lock:
                                    self._results[job.stem] = (True, path, None)
                                return
                        # If not ready, continue polling
                    else:
                        # Generation wait timed out, continue polling
                        pass

                time.sleep(poll_interval)
                elapsed += poll_interval

            # Timeout reached
            print(f"  [{job.stem}] wait timeout.", flush=True)
            with self._lock:
                self._results[job.stem] = (False, None, f"wait timeout after {timeout}s")

        except Exception as e:
            print(f"  [{job.stem}] wait error: {e}", flush=True)
            with self._lock:
                self._results[job.stem] = (False, None, str(e))

        finally:
            try:
                page.close()
            except Exception:
                pass
            self._page_semaphore.release()