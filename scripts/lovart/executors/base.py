"""
Base executor for job execution strategies.
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import List, Optional

from ..handlers import SubmitHandler, WaitHandler
from ..models import Job, JobStatus
from ..services import JobStore, LovartSession


class BaseExecutor(ABC):
    """
    Base executor using Strategy pattern.

    Different executors implement different execution strategies:
    - SingleExecutor: Execute one job at a time
    - BatchExecutor: Execute multiple jobs in parallel
    """

    def __init__(
        self,
        store: JobStore,
        submit_handler: SubmitHandler,
        wait_handler: WaitHandler,
        session: LovartSession,
    ):
        self.store = store
        self.submit_handler = submit_handler
        self.wait_handler = wait_handler
        self.session = session

    def _get_or_create_job(self, prompt_path: Path) -> Job:
        """Get existing job or create new one."""
        prompt_file = str(prompt_path.resolve())
        job = self.store.find_by_prompt(prompt_file)
        if not job:
            job = Job.create(prompt_file)
            self.store.upsert(job)
        return job

    def _should_skip(self, prompt_path: Path, job: Optional[Job] = None) -> bool:
        """Check if job should be skipped (already done with image)."""
        if job is None:
            job = self.store.find_by_prompt(str(prompt_path.resolve()))
        if not job:
            return False
        if job.status != JobStatus.DONE:
            return False
        # Check if image exists
        return self.wait_handler.downloader.check_exists(job.stem)

    @abstractmethod
    def execute(self, *args, **kwargs):
        """Execute jobs. Must be implemented by subclass."""
        pass