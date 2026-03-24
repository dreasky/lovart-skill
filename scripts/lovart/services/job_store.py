"""
Job persistence store using Repository pattern.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ..config import Config
from ..models import Job, JobStatus


class JobStore:
    """Repository for Job persistence."""

    def __init__(self, jobs_file: Optional[Path] = None):
        self._jobs_file = jobs_file or Config.JOBS_FILE
        self._jobs: list[Job] = []
        self._load()

    def _load(self) -> None:
        """Load jobs from disk."""
        if not self._jobs_file.exists():
            self._jobs = []
            return
        with open(self._jobs_file, encoding="utf-8") as f:
            data = json.load(f)
        self._jobs = [Job.from_dict(item) for item in data]

    def save(self) -> None:
        """Persist jobs to disk."""
        Config.ensure_dirs()
        with open(self._jobs_file, "w", encoding="utf-8") as f:
            json.dump([job.to_dict() for job in self._jobs], f, indent=2, ensure_ascii=False)

    def all(self) -> list[Job]:
        """Return all jobs."""
        return self._jobs.copy()

    def find_by_prompt(self, prompt_file: str) -> Optional[Job]:
        """Find job by prompt file path."""
        stem = Path(prompt_file).stem
        resolved = str(Path(prompt_file).resolve())
        for job in self._jobs:
            if job.prompt_file == resolved or job.stem == stem:
                return job
        return None

    def upsert(self, job: Job) -> None:
        """Insert or update a job."""
        # Normalize path
        job.prompt_file = str(Path(job.prompt_file).resolve())
        if job.image_path:
            job.image_path = str(Path(job.image_path).resolve())

        # Find and update or append
        for i, existing in enumerate(self._jobs):
            if existing.prompt_file == job.prompt_file or existing.stem == job.stem:
                self._jobs[i] = job
                return
        self._jobs.append(job)

    def find_by_status(self, status: JobStatus) -> list[Job]:
        """Find all jobs with given status."""
        return [job for job in self._jobs if job.status == status]

    def find_submitted(self) -> list[Job]:
        """Find all submitted jobs with project_id."""
        return [
            job
            for job in self._jobs
            if job.status == JobStatus.SUBMITTED and job.project_id
        ]

    def find_failed(self) -> list[Job]:
        """Find all failed jobs."""
        return [job for job in self._jobs if job.status == JobStatus.FAILED]

    def reset_failed(self) -> int:
        """Reset all failed jobs to pending. Returns count of reset jobs."""
        count = 0
        for job in self._jobs:
            if job.status == JobStatus.FAILED:
                job.status = JobStatus.PENDING
                job.error = None
                job.updated_at = datetime.now(timezone.utc).isoformat()
                count += 1
        if count > 0:
            self.save()
        return count