"""
Submit handler for job submission.
"""

from pathlib import Path

from ..models import Job, JobStatus
from ..services import CanvasService, JobStore
from .base import BaseHandler, HandlerContext, HandlerResult


class SubmitHandler(BaseHandler):
    """
    Handler for job submission phase.

    Responsibilities:
    - Open project (new or existing)
    - Check for existing images
    - Send prompt
    - Handle paywall
    - Wait for generation to start
    - Update job status to SUBMITTED
    """

    def __init__(
        self,
        store: JobStore,
        downloader,  # ImageDownloader
        images_dir: Path,
    ):
        super().__init__(store)
        self.downloader = downloader
        self.images_dir = images_dir

    def _do_execute(self, context: HandlerContext) -> HandlerResult:
        """Execute submission logic."""
        job = context.job
        canvas = CanvasService(context.page)

        # Check if already done
        if self._is_already_done(job):
            return HandlerResult(job=job, skipped=True)

        # Open project
        try:
            project_id = job.project_id
            result = canvas.open_project(project_id)

            # New project created
            if not project_id and result:
                project_id = result
                job.touch(project_id=project_id, project_url=context.page.url)
        except Exception as e:
            job.touch(status=JobStatus.FAILED, error=f"open_project failed: {e}")
            return HandlerResult(
                job=job,
                status_changed=True,
                failed=True,
            )

        # Wait for page to settle
        if project_id:
            context.page.wait_for_timeout(5000)

        # Dismiss any dialogs
        canvas.dismiss_dialog()

        # Check for existing image on canvas
        if project_id:
            existing = self.downloader.try_download_from_canvas(
                context.page,
                self.images_dir / f"{job.stem}.png",
                job.stem,
            )
            if existing:
                job.touch(status=JobStatus.DONE, image_path=str(existing))
                return HandlerResult(
                    job=job,
                    status_changed=True,
                )

        # Set project name
        canvas.set_project_name(job.stem)

        # Send prompt
        prompt_text = CanvasService.read_prompt(Path(job.prompt_file))
        canvas.send_prompt(prompt_text)

        # Check for paywall
        context.page.wait_for_timeout(2000)
        if canvas.check_paywall():
            job.touch(status=JobStatus.FAILED, error="paywall: insufficient credits")
            return HandlerResult(
                job=job,
                status_changed=True,
                failed=True,
            )

        # Wait for generation to start
        if not canvas.wait_for_generation_start(timeout=30):
            job.touch(status=JobStatus.FAILED, error="generation did not start within 30s")
            return HandlerResult(
                job=job,
                status_changed=True,
                failed=True,
            )

        # Update status
        job.touch(status=JobStatus.SUBMITTED)
        return HandlerResult(
            job=job,
            status_changed=True,
        )

    def _is_already_done(self, job: Job) -> bool:
        """Check if job is already completed with image file."""
        if job.status != JobStatus.DONE:
            return False
        return self.downloader.check_exists(job.stem)