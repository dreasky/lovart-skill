"""
Base handler for job processing using Template Method pattern.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from ..models import Job
from ..services import JobStore


@dataclass
class HandlerContext:
    """Context passed between handlers."""

    job: Job
    page: Optional[Any] = None  # Playwright page
    page_factory: Optional[Callable] = None  # Factory to create new pages
    prompt_path: Optional[Path] = None
    image_path: Optional[Path] = None
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass
class HandlerResult:
    """Result from handler execution."""

    job: Optional[Job] = None
    success: bool = True
    status_changed: bool = False
    skipped: bool = False
    failed: bool = False
    error: Optional[str] = None
    data: Dict[str, Any] = field(default_factory=dict)


class BaseHandler(ABC):
    """
    Base handler using Template Method pattern.

    Subclasses should implement _do_execute() method.
    The execute() method defines the skeleton of the operation.
    """

    def __init__(self, store: JobStore):
        self.store = store

    def execute(self, context: HandlerContext) -> HandlerResult:
        """
        Template method: define the execution skeleton.

        1. Pre-process
        2. Execute core logic
        3. Post-process (persist)
        """
        self._pre_process(context)
        result = self._do_execute(context)
        self._post_process(context, result)
        return result

    def _pre_process(self, context: HandlerContext) -> None:
        """Pre-processing hook. Override in subclass if needed."""
        pass

    @abstractmethod
    def _do_execute(self, context: HandlerContext) -> HandlerResult:
        """Execute core logic. Must be implemented by subclass."""
        pass

    def _post_process(self, context: HandlerContext, result: HandlerResult) -> None:
        """Post-processing: persist changes."""
        if result.job and result.status_changed:
            self.store.upsert(result.job)
            self.store.save()