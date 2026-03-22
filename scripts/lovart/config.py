"""
Configuration constants for Lovart automation.
"""

from pathlib import Path


class Config:
    """Central configuration for paths and constants."""

    # Paths
    SKILL_DIR: Path = Path(__file__).parent.parent.parent
    DATA_DIR: Path = SKILL_DIR / "scripts" / "data"
    JOBS_FILE: Path = DATA_DIR / "jobs.json"
    IMAGES_DIR: Path = DATA_DIR / "images"

    # URLs
    CANVAS_URL: str = "https://www.lovart.ai/canvas"
    NEW_PROJECT_URL: str = f"{CANVAS_URL}?newProject=true"
    DOWNLOAD_BASE: str = "https://download.lovart.ai/artifacts/agent/"

    # Selectors
    CHAT_INPUT_SELECTOR: str = "[data-testid='agent-message-input']"
    IMAGE_CARD_SELECTOR: str = "[data-testid='image-generation-card']"
    PROJECT_NAME_INPUT: str = "input#LoTextInput"

    # Timeouts
    PAGE_LOAD_TIMEOUT: int = 30000
    CHAT_INPUT_TIMEOUT: int = 20000
    IMAGE_WAIT_TIMEOUT: int = 300
    POLL_INTERVAL: int = 10
    POLL_TIMEOUT: int = 360

    @classmethod
    def ensure_dirs(cls) -> None:
        """Ensure data directories exist."""
        cls.DATA_DIR.mkdir(parents=True, exist_ok=True)
        cls.IMAGES_DIR.mkdir(parents=True, exist_ok=True)