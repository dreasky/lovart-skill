"""
Authentication state persistence.
"""

import json
from pathlib import Path
from typing import Optional

from .models import AuthState


class AuthStore:
    """Repository for AuthState persistence."""

    def __init__(self, auth_file: Optional[Path] = None):
        self._auth_file = auth_file or Path(__file__).parent.parent.parent / "data" / "auth" / "lovart.json"

    def load(self) -> Optional[AuthState]:
        """Load auth state from disk. Returns None if not found."""
        if not self._auth_file.exists():
            return None
        with open(self._auth_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        return AuthState.from_dict(data)

    def save(self, state: AuthState) -> None:
        """Persist auth state to disk."""
        self._auth_file.parent.mkdir(parents=True, exist_ok=True)
        state.touch()
        with open(self._auth_file, "w", encoding="utf-8") as f:
            json.dump(state.to_dict(), f, indent=2)
        print(f"   Session saved to {self._auth_file}", flush=True)

    def exists(self) -> bool:
        """Check if auth file exists."""
        return self._auth_file.exists()

    def delete(self) -> None:
        """Delete auth file if exists."""
        if self._auth_file.exists():
            self._auth_file.unlink()