"""
Single job executor - executes one job at a time.
"""

from pathlib import Path

from ..handlers import HandlerContext
from ..models import Job, JobStatus
from .base import BaseExecutor


class SingleExecutor(BaseExecutor):
    """
    Executor for running a single job.

    Flow:
    1. Submit job (open project, send prompt)
    2. Wait for generation start
    3. Wait for image and download

    Note: Session must be already initialized (context manager entered) before calling execute.
    """

    def execute(self, prompt_path: Path) -> Job:
        """
        Execute a single job.

        Args:
            prompt_path: Path to the prompt file

        Returns:
            The job object after execution
        """
        # Get or create job
        job = self._get_or_create_job(prompt_path)

        # Check if should skip
        if self._should_skip(prompt_path, job):
            print(f"\n[{job.stem}] already done, skipping.", flush=True)
            return job

        print(f"\n[{job.stem}] executing...", flush=True)

        # Session should already be active
        page = self.session.page

        # Phase 1: Submit
        ctx = HandlerContext(
            job=job,
            page=page,
            prompt_path=prompt_path,
            image_path=self.wait_handler.images_dir / f"{job.stem}.png",
        )
        submit_result = self.submit_handler.execute(ctx)

        # Save job status after submission
        if submit_result.status_changed:
            self.store.upsert(job)
            self.store.save()

        if submit_result.skipped:
            return job

        if submit_result.failed or submit_result.job.status != JobStatus.SUBMITTED:
            return job

        # Close initial page
        try:
            page.close()
        except Exception:
            pass

        # Phase 2: Wait and download
        wait_ctx = HandlerContext(
            job=job,
            page_factory=self.session.new_page,
            image_path=self.wait_handler.images_dir / f"{job.stem}.png",
        )
        self.wait_handler.execute(wait_ctx)

        return job