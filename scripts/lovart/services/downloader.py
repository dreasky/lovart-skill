"""
Image download service with progress callbacks and concurrent control.
"""

import base64
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from ..config import Config


@dataclass
class DownloadProgress:
    """Download progress information."""

    job_id: str
    status: str  # 'pending', 'downloading', 'completed', 'failed'
    progress: float = 0.0  # 0.0 - 1.0
    path: Optional[Path] = None
    error: Optional[str] = None


# Type alias for progress callbacks
ProgressCallback = Callable[[DownloadProgress], None]


class ImageDownloader:
    """
    Image download service with progress callbacks and concurrent control.

    Usage:
        downloader = ImageDownloader(Config.IMAGES_DIR)

        # Register progress callback
        downloader.on_progress(lambda p: print(f"{p.job_id}: {p.status}"))

        # Download single image
        path = downloader.download(page, src, dest_path, job_id="123")

        # Check if image exists
        if downloader.check_exists("my_image"):
            path = downloader.get_existing_path("my_image")
    """

    SUPPORTED_EXTENSIONS = (".png", ".jpeg", ".jpg", ".webp")

    def __init__(self, images_dir: Path, max_concurrent: int = 3):
        self.images_dir = Path(images_dir)
        self.max_concurrent = max_concurrent
        self._progress_callbacks: List[ProgressCallback] = []

    def on_progress(self, callback: ProgressCallback) -> None:
        """Register a progress callback."""
        self._progress_callbacks.append(callback)

    def _notify_progress(self, progress: DownloadProgress) -> None:
        """Notify all registered callbacks."""
        for cb in self._progress_callbacks:
            try:
                cb(progress)
            except Exception as e:
                print(f"Progress callback error: {e}", flush=True)

    def ensure_dir(self) -> None:
        """Ensure images directory exists."""
        self.images_dir.mkdir(parents=True, exist_ok=True)

    def check_exists(self, stem: str) -> bool:
        """Check if image exists for given stem (any supported extension)."""
        for ext in self.SUPPORTED_EXTENSIONS:
            if (self.images_dir / f"{stem}{ext}").exists():
                return True
        return False

    def get_existing_path(self, stem: str) -> Optional[Path]:
        """Get existing image path for given stem (any supported extension)."""
        for ext in self.SUPPORTED_EXTENSIONS:
            path = self.images_dir / f"{stem}{ext}"
            if path.exists():
                return path
        return None

    def download(self, page, src: str, dest_path: Path, job_id: str = None) -> Path:
        """
        Download a single image.

        Args:
            page: Browser page to use for download
            src: Image source URL
            dest_path: Destination path (extension may change based on actual format)
            job_id: Optional job ID for progress tracking

        Returns:
            Path to downloaded file

        Raises:
            Exception on download failure
        """
        job_id = job_id or dest_path.stem
        self._notify_progress(
            DownloadProgress(job_id=job_id, status="downloading", progress=0.0)
        )

        try:
            # Extract download URL
            m = re.search(r"/artifacts/agent/([^?]+)", src)
            if not m:
                raise ValueError(f"Could not extract filename from src: {src}")

            filename = m.group(1)
            download_url = f"{Config.DOWNLOAD_BASE}{filename}"

            # Determine final path with correct extension
            ext = Path(filename).suffix or ".png"
            final_path = dest_path.with_suffix(ext)

            # Ensure directory exists
            self.ensure_dir()

            # Execute download via browser
            data_b64 = page.evaluate(
                """async (url) => {
                    const resp = await fetch(url);
                    if (!resp.ok) throw new Error('HTTP ' + resp.status);
                    const blob = await resp.blob();
                    return await new Promise((resolve, reject) => {
                        const reader = new FileReader();
                        reader.onload = () => resolve(reader.result.split(',')[1]);
                        reader.onerror = reject;
                        reader.readAsDataURL(blob);
                    });
                }""",
                download_url,
            )

            final_path.write_bytes(base64.b64decode(data_b64))

            self._notify_progress(
                DownloadProgress(
                    job_id=job_id, status="completed", progress=1.0, path=final_path
                )
            )

            return final_path

        except Exception as e:
            self._notify_progress(
                DownloadProgress(job_id=job_id, status="failed", progress=0.0, error=str(e))
            )
            raise

    def try_download_from_canvas(
        self, page, dest_path: Path, job_id: str = None
    ) -> Optional[Path]:
        """
        Try to download image from canvas page.

        Returns:
            Path if image found and downloaded, None otherwise
        """
        cards = page.locator(Config.IMAGE_CARD_SELECTOR).all()
        if not cards:
            return None

        img = cards[-1].locator("img[src*='/artifacts/agent/']").first
        if img.count() == 0:
            return None

        src = img.get_attribute("src")
        if not src:
            return None

        return self.download(page, src, dest_path, job_id)

    def download_batch(
        self,
        tasks: List[Tuple[str, Path]],  # (src, dest_path)
        page_factory: Callable,
        job_ids: Optional[List[str]] = None,
    ) -> Dict[str, Tuple[bool, Optional[Path]]]:
        """
        Download multiple images concurrently.

        Args:
            tasks: List of (src, dest_path) tuples
            page_factory: Callable that returns a new page
            job_ids: Optional list of job IDs (must match tasks length)

        Returns:
            Dict mapping job_id to (success, path) tuple
        """
        results: Dict[str, Tuple[bool, Optional[Path]]] = {}

        with ThreadPoolExecutor(max_workers=self.max_concurrent) as executor:
            futures = {}

            for i, (src, dest) in enumerate(tasks):
                job_id = job_ids[i] if job_ids else f"task_{i}"
                page = page_factory()
                future = executor.submit(self.download, page, src, dest, job_id)
                futures[future] = job_id

            for future in as_completed(futures):
                job_id = futures[future]
                try:
                    path = future.result()
                    results[job_id] = (True, path)
                except Exception as e:
                    print(f"Batch download error for {job_id}: {e}", flush=True)
                    results[job_id] = (False, None)

        return results