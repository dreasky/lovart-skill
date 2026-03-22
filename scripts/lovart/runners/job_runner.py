"""
Job execution runners.
"""

import time
from pathlib import Path
from typing import Optional

from ..config import Config
from ..models import Job, JobStatus
from ..services import CanvasService, JobStore
from .image_waiter import ImageWaiter


class JobRunner:
    """Orchestrates job submission and image download with retry logic."""

    def __init__(
        self,
        job_store: JobStore,
        images_dir: Optional[Path] = None,
        wait_seconds: int = 180,
        max_retries: int = 3,
    ):
        self.store = job_store
        self.images_dir = images_dir or Config.IMAGES_DIR
        self.waiter = ImageWaiter(wait_seconds=wait_seconds, max_retries=max_retries)

    def submit(self, page, prompt_path: Path) -> tuple[Job, Path]:
        """
        Phase 1: Open project, send prompt, mark submitted.
        Returns (job, image_path). Does NOT wait for image.
        """
        prompt_file = str(prompt_path.resolve())
        prompt_text = CanvasService.read_prompt(prompt_path)
        stem = prompt_path.stem
        image_path = self.images_dir.resolve() / f"{stem}.png"

        # Find or create job
        job = self.store.find_by_prompt(prompt_file)
        if not job:
            job = Job.create(prompt_file)
        self.store.upsert(job)

        print(f"\n[{stem}] submitting...", flush=True)

        # Skip if already done
        if job.status == JobStatus.DONE and image_path.exists():
            print(f"  [{stem}] already done, skipping.", flush=True)
            return job, image_path

        canvas = CanvasService(page)

        try:
            project_id = job.project_id
            result = canvas.open_project(project_id)

            # New project created
            if not project_id and result:
                project_id = result
                job.touch(project_id=project_id, project_url=page.url)
                self.store.upsert(job)
                self.store.save()

            # Check for existing image
            if project_id:
                page.wait_for_timeout(5000)

            canvas.dismiss_dialog()

            existing = canvas.try_download_image(image_path)
            if existing:
                print(f"  [{stem}] image already present, downloading.", flush=True)
                job.touch(status=JobStatus.DONE, image_path=str(existing))
                self.store.upsert(job)
                self.store.save()
                return job, image_path

            # Send prompt if not yet submitted
            if job.status != JobStatus.SUBMITTED:
                canvas.set_project_name(stem)
                canvas.send_prompt(prompt_text)

                # Check paywall
                page.wait_for_timeout(2000)
                if canvas.check_paywall():
                    print(f"  [{stem}] paywall detected — insufficient credits.", flush=True)
                    job.touch(status=JobStatus.FAILED)
                    self.store.upsert(job)
                    self.store.save()
                    return job, image_path
            else:
                print(f"  [{stem}] already submitted.", flush=True)

            job.touch(status=JobStatus.SUBMITTED)
            self.store.upsert(job)
            self.store.save()

        except Exception as e:
            print(f"  [{stem}] submit error: {e}", flush=True)
            job.touch(status=JobStatus.FAILED)
            self.store.upsert(job)
            self.store.save()

        return job, image_path

    def run_single(self, page, prompt_path: Path, session) -> Job:
        """
        Run one prompt → project → image job with retry logic.

        Args:
            page: Initial browser page
            prompt_path: Path to prompt file
            session: LovartSession for creating new pages
        """
        job, image_path = self.submit(page, prompt_path)

        if job.status in (JobStatus.DONE, JobStatus.FAILED):
            return job

        if not job.project_id:
            print(f"  [{job.stem}] no project_id, cannot wait.", flush=True)
            return job

        # Close the initial page to free resources
        try:
            page.close()
        except Exception:
            pass

        # Wait with retry logic
        canvas = CanvasService(None)
        success, final_path = self.waiter.wait_and_download(
            job=job,
            image_path=image_path,
            canvas=canvas,
            page_factory=session.new_page,
        )

        if success and final_path:
            job.touch(status=JobStatus.DONE, image_path=str(final_path))
        # On failure, keep SUBMITTED status for later retry
        self.store.upsert(job)
        self.store.save()

        return job

    def run_batch(self, prompt_paths: list[Path], session) -> None:
        """
        Run multiple jobs with parallel waiting.

        Args:
            prompt_paths: List of prompt file paths
            session: LovartSession for creating pages
        """
        submitted: list[tuple[Job, Path]] = []

        # Phase 1: Submit all jobs
        for p in prompt_paths:
            prompt_file = str(p.resolve())
            image_path = self.images_dir.resolve() / f"{p.stem}.png"
            existing = self.store.find_by_prompt(prompt_file)

            if existing and existing.status == JobStatus.DONE and image_path.exists():
                print(f"\n[{p.stem}] already done, skipping.", flush=True)
                continue

            page = session.new_page()
            job, image_path = self.submit(page, p)

            # Close page after submit
            try:
                page.close()
            except Exception:
                pass

            if job.status == JobStatus.SUBMITTED and job.project_id:
                submitted.append((job, image_path))
            elif job.status == JobStatus.FAILED:
                print(f"  [{p.stem}] failed, skipping.", flush=True)

        if not submitted:
            print("No jobs to wait for.", flush=True)
            return

        # Phase 2: Parallel waiting (each job waits independently)
        print(f"\n{len(submitted)} job(s) submitted. Starting wait cycles...", flush=True)

        # Use threading for parallel waiting
        import threading
        threads = []
        results = {}

        def wait_for_job(job: Job, image_path: Path, idx: int):
            canvas = CanvasService(None)
            success, final_path = self.waiter.wait_and_download(
                job=job,
                image_path=image_path,
                canvas=canvas,
                page_factory=session.new_page,
            )
            results[idx] = (success, final_path)

        for idx, (job, image_path) in enumerate(submitted):
            t = threading.Thread(
                target=wait_for_job,
                args=(job, image_path, idx),
                daemon=True,
            )
            threads.append(t)
            t.start()

        # Wait for all threads
        for t in threads:
            t.join()

        # Update job statuses
        for idx, (job, image_path) in enumerate(submitted):
            success, final_path = results.get(idx, (False, None))
            if success and final_path:
                job.touch(status=JobStatus.DONE, image_path=str(final_path))
            # Keep SUBMITTED on failure
            self.store.upsert(job)
            self.store.save()

    def download_all_submitted(self, session) -> None:
        """Download images for all submitted jobs."""
        pending = self.store.find_submitted()
        print(f"Downloading images for {len(pending)} submitted job(s)...", flush=True)

        for job in pending:
            p = Path(job.prompt_file)
            image_path = self.images_dir.resolve() / f"{p.stem}.png"
            print(f"\n[{p.stem}] project: {job.project_id}", flush=True)

            canvas = CanvasService(None)
            success, final_path = self.waiter.wait_and_download(
                job=job,
                image_path=image_path,
                canvas=canvas,
                page_factory=session.new_page,
            )

            if success and final_path:
                job.touch(status=JobStatus.DONE, image_path=str(final_path))
            self.store.upsert(job)
            self.store.save()