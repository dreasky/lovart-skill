"""
Job data model.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional


class JobStatus(Enum):
    """Job status enumeration."""

    PENDING = "pending"
    SUBMITTED = "submitted"
    DONE = "done"
    FAILED = "failed"

    @classmethod
    def allowed_transitions(cls) -> dict["JobStatus", list["JobStatus"]]:
        """Return allowed status transitions."""
        return {
            cls.PENDING: [cls.SUBMITTED, cls.FAILED],
            cls.SUBMITTED: [cls.DONE, cls.FAILED, cls.SUBMITTED],
            cls.FAILED: [cls.SUBMITTED, cls.PENDING],
            cls.DONE: [],
        }


@dataclass
class Job:
    """Represents a single generation job."""

    prompt_file: str
    project_id: Optional[str] = None
    project_url: Optional[str] = None
    status: JobStatus = JobStatus.PENDING
    image_path: Optional[str] = None
    error: Optional[str] = None  # Failure reason
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @property
    def stem(self) -> str:
        """Get the prompt file stem (filename without extension)."""
        return Path(self.prompt_file).stem

    def can_transition_to(self, new_status: JobStatus) -> bool:
        """Check if transition to new status is allowed."""
        allowed = JobStatus.allowed_transitions().get(self.status, [])
        return new_status in allowed

    def transition_to(self, new_status: JobStatus) -> bool:
        """
        Execute status transition.

        Returns True if transition was successful, False if not allowed.
        """
        if not self.can_transition_to(new_status):
            return False
        self.status = new_status
        self.updated_at = datetime.now(timezone.utc).isoformat()
        return True

    def touch(self, **kwargs) -> "Job":
        """Update fields and refresh updated_at timestamp."""
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)
        self.updated_at = datetime.now(timezone.utc).isoformat()
        return self

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "prompt_file": self.prompt_file,
            "project_id": self.project_id,
            "project_url": self.project_url,
            "status": self.status.value,
            "image_path": self.image_path,
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Job":
        """Create Job from dictionary."""
        return cls(
            prompt_file=data["prompt_file"],
            project_id=data.get("project_id"),
            project_url=data.get("project_url"),
            status=JobStatus(data.get("status", "pending")),
            image_path=data.get("image_path"),
            error=data.get("error"),
            created_at=data.get("created_at", datetime.now(timezone.utc).isoformat()),
            updated_at=data.get("updated_at", datetime.now(timezone.utc).isoformat()),
        )

    @classmethod
    def create(cls, prompt_file: str) -> "Job":
        """Factory method to create a new job."""
        return cls(prompt_file=str(Path(prompt_file).resolve()))