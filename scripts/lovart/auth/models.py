"""
Authentication models.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


@dataclass
class StorageOrigin:
    """Local storage origin data."""

    origin: str
    localStorage: List[Dict[str, str]] = field(default_factory=list)


@dataclass
class AuthState:
    """Authentication state containing cookies and localStorage."""

    cookies: List[Dict[str, Any]] = field(default_factory=list)
    origins: List[StorageOrigin] = field(default_factory=list)
    updated_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result = {
            "cookies": self.cookies,
            "origins": [{"origin": o.origin, "localStorage": o.localStorage} for o in self.origins],
        }
        if self.updated_at:
            result["updated_at"] = self.updated_at
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AuthState":
        """Create AuthState from dictionary."""
        origins = []
        for o in data.get("origins", []):
            origins.append(StorageOrigin(origin=o.get("origin", ""), localStorage=o.get("localStorage", [])))
        return cls(
            cookies=data.get("cookies", []),
            origins=origins,
            updated_at=data.get("updated_at"),
        )

    @classmethod
    def from_context(cls, context) -> "AuthState":
        """Extract storage state from browser context."""
        cookies = context.cookies()
        origins: List[StorageOrigin] = []

        try:
            pages = context.pages
            page = pages[0] if pages else None
            if page and "lovart.ai" in page.url:
                local_storage = page.evaluate("() => Object.entries(localStorage)")
                origins.append(
                    StorageOrigin(
                        origin="https://www.lovart.ai",
                        localStorage=[{"name": k, "value": v} for k, v in local_storage],
                    )
                )
        except Exception:
            pass

        return cls(cookies=cookies, origins=origins)

    def touch(self) -> None:
        """Update timestamp."""
        self.updated_at = datetime.now(timezone.utc).isoformat()