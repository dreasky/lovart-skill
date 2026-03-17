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

STATUS_PENDING = "pending"  # job created, not yet submitted
STATUS_SUBMITTED = "submitted"  # prompt sent, waiting for image
STATUS_DONE = "done"  # image downloaded
STATUS_FAILED = "failed"  # something went wrong

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


def new_job(prompt_file: str) -> dict:
    return {
        "prompt_file": prompt_file,
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


def extract_project_id(url: str) -> str | None:
    # Try query string first (handles ?agent=1&projectId=xxx)
    qs = parse_qs(urlparse(url).query)
    if qs.get("projectId"):
        return qs["projectId"][0]
    # Fallback: regex scan (handles any URL shape)
    m = re.search(r"projectId=([a-zA-Z0-9]+)", url)
    return m.group(1) if m else None


NEW_PROJECT_URL = f"{CANVAS_URL}?newProject=true"


PROJECT_NAME_INPUT = "input#LoTextInput"


def set_project_name(page, name: str) -> None:
    """Set the project name input field and blur to apply."""
    try:
        inp = page.locator(PROJECT_NAME_INPUT)
        inp.wait_for(timeout=5000)
        inp.evaluate(
            "(el, name) => { el.removeAttribute('readonly'); el.value = name; }", name
        )
        inp.dispatch_event("input")
        inp.dispatch_event("change")
        inp.blur()
        print(f"  Project name set: {name}", flush=True)
    except Exception as e:
        print(f"  set_project_name: {e}", flush=True)


def open_page(
    page, project_id: str | None, project_name: str | None = None
) -> str | None:
    """
    New project: go to /canvas?newProject=true, wait for canvas to load, return projectId.
    Existing project: go directly to /canvas?projectId=..., return None.
    """
    if project_id:
        url = f"{CANVAS_URL}?projectId={project_id}"
        print(f"  Resuming project: {url}", flush=True)
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        return None
    else:
        print(f"  New project: {NEW_PROJECT_URL}", flush=True)
        page.goto(NEW_PROJECT_URL, wait_until="domcontentloaded", timeout=30000)
        print("  Waiting for projectId in URL...", flush=True)
        page.wait_for_function(
            "() => new URLSearchParams(location.search).get('projectId')", timeout=30000
        )
        pid = extract_project_id(page.url)
        if not pid:
            raise RuntimeError(f"No projectId in URL after canvas loaded: {page.url}")
        print(f"  Project ID: {pid}", flush=True)
        if project_name:
            set_project_name(page, project_name)
        return pid


def dismiss_dialog(page) -> None:
    """Close any blocking dialog before interacting."""
    try:
        # Wait for dialog to appear (it may animate in after page load)
        page.wait_for_selector("[role='dialog'][data-state='open']", timeout=5000)
        dialog = page.locator("[role='dialog'][data-state='open']")
        print(f"  dismiss_dialog: found {dialog.count()} open dialog(s)", flush=True)
        close_btn = dialog.locator("button[aria-label='Close']")
        print(f"  dismiss_dialog: close buttons found: {close_btn.count()}", flush=True)
        close_btn.click()
        page.wait_for_selector(
            "[role='dialog'][data-state='open']", state="hidden", timeout=5000
        )
        print("  dismiss_dialog: dialog closed", flush=True)
        page.wait_for_selector(
            "div[data-state='open'][aria-hidden='true']", state="hidden", timeout=5000
        )
        print("  dismiss_dialog: overlay cleared", flush=True)
    except Exception as e:
        print(f"  dismiss_dialog: {e}", flush=True)


def send_prompt(page, prompt_text: str) -> None:
    dismiss_dialog(page)
    print("  Waiting for chat input...", flush=True)
    page.wait_for_selector(CHAT_INPUT_SELECTOR, timeout=20000)
    page.locator(CHAT_INPUT_SELECTOR).click()
    page.wait_for_timeout(300)  # let focus settle after dialog close

    # Lexical editor: inject text directly into the editor's paragraph node
    page.evaluate(
        """(text) => {
            const editor = document.querySelector('[data-lexical-editor="true"]');
            if (!editor) return;
            editor.focus();
            const p = editor.querySelector('p');
            if (p) {
                // Clear placeholder <br> and set text content
                p.innerHTML = '';
                // Insert as text node to trigger Lexical's mutation observer
                const range = document.createRange();
                const sel = window.getSelection();
                range.selectNodeContents(p);
                range.collapse(false);
                sel.removeAllRanges();
                sel.addRange(range);
            }
            document.execCommand('insertText', false, text);
        }""",
        prompt_text,
    )
    print(f"  Prompt pasted ({len(prompt_text)} chars)", flush=True)
    page.keyboard.press("Enter")
    print("  Prompt sent.", flush=True)


DOWNLOAD_BASE = "https://download.lovart.ai/artifacts/agent/"
IMAGE_CARD_SELECTOR = "[data-testid='image-generation-card']"


def wait_and_download_image(page, dest_path: Path, timeout: int = 300) -> bool:
    """
    Wait for image-generation-card, extract image filename from img src,
    construct download URL and fetch directly.
    """
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    print(f"  Waiting for image generation (timeout={timeout}s)...", flush=True)

    try:
        page.wait_for_selector(IMAGE_CARD_SELECTOR, timeout=timeout * 1000)
    except Exception:
        print("  Timed out waiting for image-generation-card.", flush=True)
        return False

    cards = page.locator(IMAGE_CARD_SELECTOR).all()
    last_card = cards[-1]
    print(
        f"  Image card found ({len(cards)} total), waiting for img src...", flush=True
    )

    # Wait until the img src contains the artifact URL (generation complete)
    img_locator = last_card.locator("img[src*='/artifacts/agent/']").first
    img_locator.wait_for(timeout=300000)

    # Extract image filename from img src, e.g. aOVGV3fdZaKHiUdJ.png
    src = img_locator.get_attribute("src") or ""
    m = re.search(r"/artifacts/agent/([^?]+)", src)
    if not m:
        print(f"  Could not extract image filename from src: {src}", flush=True)
        return False

    filename = m.group(1)  # e.g. aOVGV3fdZaKHiUdJ.png
    download_url = f"{DOWNLOAD_BASE}{filename}"
    ext = Path(filename).suffix or ".png"
    final_path = dest_path.with_suffix(ext)

    print(f"  Downloading: {download_url}", flush=True)
    # Firefox Xray restrictions prevent TypedArray manipulation across origins.
    # Use FileReader API to convert blob to base64 entirely within page context.
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
    print(f"  Saved: {final_path}", flush=True)
    return True


# ---------------------------------------------------------------------------
# Single job runner
# ---------------------------------------------------------------------------


def run_single(
    page, prompt_path: Path, jobs: list[dict], images_dir: Path = IMAGES_DIR
) -> dict:
    """Run one prompt → project → image job. Updates and returns the job."""
    prompt_file = str(prompt_path)
    prompt_text = read_prompt(prompt_path)

    job = find_job(jobs, prompt_file)
    if not job:
        job = new_job(prompt_file)
        upsert_job(jobs, job)

    # Derive image filename from prompt filename
    stem = prompt_path.stem
    image_path = images_dir / f"{stem}.png"

    print(f"\n[{stem}]", flush=True)

    # Skip if already done
    if job["status"] == STATUS_DONE and image_path.exists():
        print("  Already done, skipping.", flush=True)
        return job

    try:
        # New project: go to home and send prompt, then capture projectId from URL
        # Existing project: go directly to canvas
        project_id = job.get("project_id")
        result = open_page(
            page, project_id, project_name=stem if not project_id else None
        )
        if not project_id and result:
            project_id = result
            touch_job(job, project_id=project_id, project_url=page.url)
            upsert_job(jobs, job)
            save_jobs(jobs)

        # Send prompt — skip if image already generated or already submitted
        if job["status"] != STATUS_SUBMITTED:
            if page.locator(IMAGE_CARD_SELECTOR).count():
                print("  Image card already present, skipping prompt.", flush=True)
                touch_job(job, status=STATUS_SUBMITTED)
                upsert_job(jobs, job)
                save_jobs(jobs)
            else:
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
    group.add_argument(
        "--download-all", action="store_true", help="Download images for submitted jobs"
    )
    parser.add_argument("--headless", action="store_true")
    parser.add_argument(
        "--output-dir",
        help="Directory to save downloaded images (default: scripts/data/images)",
    )
    args = parser.parse_args()

    images_dir = Path(args.output_dir) if args.output_dir else IMAGES_DIR

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
            run_single(page, p, jobs, images_dir)

        elif args.batch:
            folder = Path(args.batch)
            md_files = sorted(folder.glob("*.md"))
            if not md_files:
                print(f"No .md files found in {folder}")
                return
            print(f"Batch: {len(md_files)} prompts", flush=True)
            for p in md_files:
                run_single(page, p, jobs, images_dir)

        elif args.download_all:
            pending = [
                j
                for j in jobs
                if j["status"] == STATUS_SUBMITTED and j.get("project_id")
            ]
            print(
                f"Downloading images for {len(pending)} submitted job(s)...", flush=True
            )
            for job in pending:
                p = Path(job["prompt_file"])
                image_path = images_dir / f"{p.stem}.png"
                print(f"\n[{p.stem}] project: {job['project_id']}", flush=True)
                open_page(page, job["project_id"])
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
        print(
            f"  {stem:30s}  {j['status']:10s}  {(j.get('project_id') or '')[:16]}",
            flush=True,
        )


if __name__ == "__main__":
    main()
