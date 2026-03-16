#!/usr/bin/env python3
"""
Lovart.ai Canvas Automation

Each job = one prompt file → one Lovart project → one generated image.
All jobs are tracked in data/jobs.json for full traceability.

Usage:
    # Single image (first run — creates new project)
    python run.py lovart.py --prompt prompts/01_city.md

    # Retry a failed job by prompt file
    python run.py lovart.py --prompt prompts/01_city.md

    # Batch: submit all .md files in a folder (one project each)
    python run.py lovart.py --batch prompts/

    # Download images for all submitted jobs
    python run.py lovart.py --download-all
"""

import argparse
import base64
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from session import LovartSession

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

SKILL_DIR = Path(__file__).parent.parent
DATA_DIR = SKILL_DIR / "scripts" / "data"
JOBS_FILE = DATA_DIR / "jobs.json"
IMAGES_DIR = DATA_DIR / "images"

# ---------------------------------------------------------------------------
# Job status
# ---------------------------------------------------------------------------

STATUS_PENDING = "pending"      # job created, not yet submitted
STATUS_SUBMITTED = "submitted"  # prompt sent, waiting for image
STATUS_DONE = "done"            # image downloaded
STATUS_FAILED = "failed"        # something went wrong

# ---------------------------------------------------------------------------
# Jobs table helpers
# ---------------------------------------------------------------------------


def load_jobs() -> list[dict]:
    if not JOBS_FILE.exists():
        return []
    with open(JOBS_FILE, encoding="utf-8") as f:
        return json.load(f)


def save_jobs(jobs: list[dict]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(JOBS_FILE, "w", encoding="utf-8") as f:
        json.dump(jobs, f, indent=2, ensure_ascii=False)


def find_job(jobs: list[dict], prompt_file: str) -> dict | None:
    for j in jobs:
        if j["prompt_file"] == prompt_file:
            return j
    return None


def upsert_job(jobs: list[dict], job: dict) -> None:
    for i, j in enumerate(jobs):
        if j["prompt_file"] == job["prompt_file"]:
            jobs[i] = job
            return
    jobs.append(job)


def new_job(prompt_file: str, prompt_text: str) -> dict:
    return {
        "prompt_file": prompt_file,
        "prompt_text": prompt_text,
        "project_id": None,
        "project_url": None,
        "status": STATUS_PENDING,
        "image_path": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def touch_job(job: dict, **kwargs) -> dict:
    job.update(kwargs)
    job["updated_at"] = datetime.now(timezone.utc).isoformat()
    return job


# ---------------------------------------------------------------------------
# Prompt helpers
# ---------------------------------------------------------------------------


def read_prompt(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"\*{1,2}(.+?)\*{1,2}", r"\1", text)
    text = re.sub(r"`(.+?)`", r"\1", text)
    return text.strip()


# ---------------------------------------------------------------------------
# Canvas helpers
# ---------------------------------------------------------------------------

CANVAS_URL = "https://www.lovart.ai/canvas"

CHAT_INPUT_SELECTOR = "[data-testid='agent-message-input']"
IMAGE_SELECTOR = "img[src*='cdn'], img[src*='blob'], img[src*='output']"


def extract_project_id(url: str) -> str | None:
    qs = parse_qs(urlparse(url).query)
    ids = qs.get("projectId", [])
    return ids[0] if ids else None


def open_canvas(page, project_id: str | None = None) -> str:
    url = f"{CANVAS_URL}?projectId={project_id}" if project_id else CANVAS_URL
    print(f"  Opening: {url}", flush=True)
    page.goto(url, wait_until="domcontentloaded", timeout=30000)

    for _ in range(60):
        current = page.evaluate("location.href")
        pid = extract_project_id(current)
        if pid:
            print(f"  Project ID: {pid}", flush=True)
            return pid
        time.sleep(1)

    raise RuntimeError(f"Could not detect projectId in URL after navigation")


def send_prompt(page, prompt_text: str) -> None:
    print("  Waiting for chat input...", flush=True)
    page.wait_for_selector(CHAT_INPUT_SELECTOR, timeout=20000)
    page.locator(CHAT_INPUT_SELECTOR).click()
    # Lexical rich text editor — must use keyboard.type(), fill() won't work
    page.keyboard.type(prompt_text)
    print(f"  Prompt typed ({len(prompt_text)} chars)", flush=True)
    page.keyboard.press("Enter")
    print("  Prompt sent.", flush=True)


def wait_and_download_image(page, dest_path: Path, timeout: int = 180) -> bool:
    """Wait for a generated image and download it to dest_path."""
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    print(f"  Waiting for image (timeout={timeout}s)...", flush=True)

    deadline = time.time() + timeout
    seen_srcs: set[str] = set()

    while time.time() < deadline:
        imgs = page.locator(IMAGE_SELECTOR).all()
        for img in imgs:
            try:
                src = img.get_attribute("src") or ""
                if not src or src in seen_srcs:
                    continue
                seen_srcs.add(src)
                if _download_image(page, src, dest_path):
                    print(f"  Saved: {dest_path}", flush=True)
                    return True
            except Exception:
                continue
        time.sleep(2)

    print("  No image found within timeout.", flush=True)
    return False


def _download_image(page, src: str, dest: Path) -> bool:
    data_b64 = page.evaluate(
        """async (url) => {
            const resp = await fetch(url);
            if (!resp.ok) return null;
            const buf = await resp.arrayBuffer();
            const bytes = new Uint8Array(buf);
            let binary = '';
            for (let i = 0; i < bytes.byteLength; i++) binary += String.fromCharCode(bytes[i]);
            return btoa(binary);
        }""",
        src,
    )
    if not data_b64:
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(base64.b64decode(data_b64))
    return True


# ---------------------------------------------------------------------------
# Single job runner
# ---------------------------------------------------------------------------


def run_single(page, prompt_path: Path, jobs: list[dict]) -> dict:
    """Run one prompt → project → image job. Updates and returns the job."""
    prompt_file = str(prompt_path)
    prompt_text = read_prompt(prompt_path)

    job = find_job(jobs, prompt_file)
    if not job:
        job = new_job(prompt_file, prompt_text)
        upsert_job(jobs, job)

    # Derive image filename from prompt filename
    stem = prompt_path.stem
    image_path = IMAGES_DIR / f"{stem}.png"

    print(f"\n[{stem}]", flush=True)

    # Skip if already done
    if job["status"] == STATUS_DONE and image_path.exists():
        print("  Already done, skipping.", flush=True)
        return job

    try:
        # Open canvas (new project or resume existing)
        pid = open_canvas(page, job.get("project_id"))
        current_url = page.evaluate("location.href")

        touch_job(job, project_id=pid, project_url=current_url)
        upsert_job(jobs, job)
        save_jobs(jobs)

        # Send prompt (skip if already submitted)
        if job["status"] != STATUS_SUBMITTED:
            send_prompt(page, prompt_text)
            touch_job(job, status=STATUS_SUBMITTED)
            upsert_job(jobs, job)
            save_jobs(jobs)

        # Download image
        ok = wait_and_download_image(page, image_path)
        if ok:
            touch_job(job, status=STATUS_DONE, image_path=str(image_path))
        else:
            touch_job(job, status=STATUS_FAILED)

    except Exception as e:
        print(f"  Error: {e}", flush=True)
        touch_job(job, status=STATUS_FAILED)

    upsert_job(jobs, job)
    save_jobs(jobs)
    return job


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description="Lovart.ai canvas automation")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--prompt", help="Single prompt .md file")
    group.add_argument("--batch", help="Folder of prompt .md files")
    group.add_argument("--download-all", action="store_true", help="Download images for submitted jobs")
    parser.add_argument("--headless", action="store_true")
    args = parser.parse_args()

    jobs = load_jobs()

    with LovartSession(headless=args.headless) as session:
        if not session.is_logged_in():
            print("Session expired. Please re-authenticate.")
            return

        page = session.page

        if args.prompt:
            p = Path(args.prompt)
            if not p.exists():
                print(f"File not found: {p}")
                return
            run_single(page, p, jobs)

        elif args.batch:
            folder = Path(args.batch)
            md_files = sorted(folder.glob("*.md"))
            if not md_files:
                print(f"No .md files found in {folder}")
                return
            print(f"Batch: {len(md_files)} prompts", flush=True)
            for p in md_files:
                run_single(page, p, jobs)

        elif args.download_all:
            pending = [j for j in jobs if j["status"] == STATUS_SUBMITTED and j.get("project_id")]
            print(f"Downloading images for {len(pending)} submitted job(s)...", flush=True)
            for job in pending:
                p = Path(job["prompt_file"])
                image_path = IMAGES_DIR / f"{p.stem}.png"
                print(f"\n[{p.stem}] project: {job['project_id']}", flush=True)
                open_canvas(page, job["project_id"])
                ok = wait_and_download_image(page, image_path)
                if ok:
                    touch_job(job, status=STATUS_DONE, image_path=str(image_path))
                else:
                    touch_job(job, status=STATUS_FAILED)
                upsert_job(jobs, job)
                save_jobs(jobs)

    # Print summary
    print("\n--- Jobs Summary ---", flush=True)
    for j in load_jobs():
        stem = Path(j["prompt_file"]).stem
        print(f"  {stem:30s}  {j['status']:10s}  {j.get('project_id', '')[:16]}", flush=True)


if __name__ == "__main__":
    main()
