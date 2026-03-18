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
        if (
            j["prompt_file"] == prompt_file
            or Path(j["prompt_file"]).stem == Path(prompt_file).stem
        ):
            return j
    return None


def upsert_job(jobs: list[dict], job: dict) -> None:
    stem = Path(job["prompt_file"]).stem
    for i, j in enumerate(jobs):
        if (
            j["prompt_file"] == job["prompt_file"]
            or Path(j["prompt_file"]).stem == stem
        ):
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

DOWNLOAD_BASE = "https://download.lovart.ai/artifacts/agent/"
IMAGE_CARD_SELECTOR = "[data-testid='image-generation-card']"


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
        inp.click()
        inp.press("Tab")
        page.wait_for_timeout(500)  # let save request fire
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


def _do_download(page, src: str, dest_path: Path) -> Path:
    """Extract filename from img src, fetch via page context, write to disk. Returns final path."""
    m = re.search(r"/artifacts/agent/([^?]+)", src)
    if not m:
        raise ValueError(f"Could not extract filename from src: {src}")
    filename = m.group(1)
    download_url = f"{DOWNLOAD_BASE}{filename}"
    ext = Path(filename).suffix or ".png"
    final_path = dest_path.with_suffix(ext)
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
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
    return final_path


def try_download_image(page, dest_path: Path) -> Path | None:
    """
    Non-blocking check: if image card with artifact src is present, download and return path.
    Returns None if image is not ready yet.
    """
    cards = page.locator(IMAGE_CARD_SELECTOR).all()
    if not cards:
        return None
    img = cards[-1].locator("img[src*='/artifacts/agent/']").first
    if img.count() == 0:
        return None
    src = img.get_attribute("src") or ""
    if not src:
        return None
    return _do_download(page, src, dest_path)


def wait_and_download_image(page, dest_path: Path, timeout: int = 300) -> bool:
    """
    Blocking wait for image-generation-card, then download.
    Used by single-job mode.
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

    img_locator = last_card.locator("img[src*='/artifacts/agent/']").first
    img_locator.wait_for(timeout=300000)

    src = img_locator.get_attribute("src") or ""
    try:
        _do_download(page, src, dest_path)
        return True
    except Exception as e:
        print(f"  Download error: {e}", flush=True)
        return False


# ---------------------------------------------------------------------------
# Single job runner
# ---------------------------------------------------------------------------


def submit_job(
    page, prompt_path: Path, jobs: list[dict], images_dir: Path
) -> tuple[dict, Path]:
    """
    Phase 1 (serial): open project, send prompt, mark submitted.
    Returns (job, image_path). Does NOT wait for image generation.
    """
    prompt_file = str(prompt_path.resolve())
    prompt_text = read_prompt(prompt_path)
    stem = prompt_path.stem
    image_path = images_dir.resolve() / f"{stem}.png"

    job = find_job(jobs, prompt_file)
    if not job:
        job = new_job(prompt_file)
    else:
        # Normalize stored path to absolute
        job["prompt_file"] = prompt_file
        if job.get("image_path"):
            job["image_path"] = str(Path(job["image_path"]).resolve())
    upsert_job(jobs, job)

    print(f"\n[{stem}] submitting...", flush=True)

    if job["status"] == STATUS_DONE and image_path.exists():
        print(f"  [{stem}] already done, skipping.", flush=True)
        return job, image_path

    try:
        project_id = job.get("project_id")
        result = open_page(page, project_id)

        if not project_id and result:
            project_id = result
            touch_job(job, project_id=project_id, project_url=page.url)
            upsert_job(jobs, job)
            save_jobs(jobs)

        # Check if image already generated (handles failed jobs that actually completed)
        # Wait briefly for page to render before checking — avoids false negatives on slow loads
        if project_id:
            page.wait_for_timeout(5000)

        # 关闭弹窗
        dismiss_dialog(page)

        existing = try_download_image(page, image_path)
        if existing:
            print(f"  [{stem}] image already present, downloading.", flush=True)
            touch_job(job, status=STATUS_DONE, image_path=str(existing))
            upsert_job(jobs, job)
            save_jobs(jobs)
            return job, image_path

        # Send prompt if not yet submitted
        if job["status"] != STATUS_SUBMITTED:

            # 设置项目名称
            set_project_name(page, stem)

            # 发送消息
            send_prompt(page, prompt_text)
            # Check for paywall immediately after sending — insufficient credits
            page.wait_for_timeout(2000)
            if page.locator("[data-testid='paywall-container']").count():
                print(
                    f"  [{stem}] paywall detected — insufficient credits, marking failed.",
                    flush=True,
                )
                touch_job(job, status=STATUS_FAILED)
                upsert_job(jobs, job)
                save_jobs(jobs)
                return job, image_path
        else:
            print(f"  [{stem}] already submitted, will wait for image.", flush=True)
        touch_job(job, status=STATUS_SUBMITTED)
        upsert_job(jobs, job)
        save_jobs(jobs)

    except Exception as e:
        print(f"  [{stem}] submit error: {e}", flush=True)
        touch_job(job, status=STATUS_FAILED)
        upsert_job(jobs, job)
        save_jobs(jobs)

    return job, image_path


def run_single(
    page, prompt_path: Path, jobs: list[dict], images_dir: Path = IMAGES_DIR
) -> dict:
    """Run one prompt → project → image job. Updates and returns the job."""
    job, image_path = submit_job(page, prompt_path, jobs, images_dir)
    if job["status"] not in (STATUS_DONE, STATUS_FAILED):
        ok = wait_and_download_image(page, image_path)
        if ok:
            touch_job(job, status=STATUS_DONE, image_path=str(image_path))
        else:
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

        if args.prompt:
            p = Path(args.prompt)
            if not p.exists():
                print(f"File not found: {p}")
                return
            run_single(session.page, p, jobs, images_dir)

        elif args.batch:
            folder = Path(args.batch)
            md_files = sorted(folder.glob("*.md"))
            if not md_files:
                print(f"No .md files found in {folder}")
                return
            print(
                f"Batch: {len(md_files)} prompts — serial submit, parallel download",
                flush=True,
            )

            # Phase 1: serial submit — create projects and send prompts one by one
            submitted: list[tuple[dict, Path, object]] = []  # (job, image_path, page)
            for p in md_files:
                prompt_file = str(p.resolve())
                image_path = images_dir.resolve() / f"{p.stem}.png"
                existing = find_job(jobs, prompt_file)
                if (
                    existing
                    and existing["status"] == STATUS_DONE
                    and image_path.exists()
                ):
                    print(f"\n[{p.stem}] already done, skipping.", flush=True)
                    # Normalize path in-place and persist
                    existing["prompt_file"] = prompt_file
                    if existing.get("image_path"):
                        existing["image_path"] = str(
                            Path(existing["image_path"]).resolve()
                        )
                    upsert_job(jobs, existing)
                    continue
                page = session.new_page()
                job, image_path = submit_job(page, p, jobs, images_dir)
                if job["status"] in (STATUS_DONE, STATUS_FAILED):
                    page.close()
                else:
                    submitted.append((job, image_path, page))

            # Phase 2: single-threaded polling — check all pages in turn until all done
            POLL_INTERVAL = 10  # seconds between rounds
            POLL_TIMEOUT = 360  # 6 min max per job
            deadline = time.time() + POLL_TIMEOUT
            pending = list(submitted)  # [(job, image_path, page), ...]

            print(
                f"\nAll prompts submitted. Polling {len(pending)} job(s) for images...",
                flush=True,
            )

            while pending and time.time() < deadline:
                still_pending = []
                for job, image_path, page in pending:
                    stem = Path(job["prompt_file"]).stem
                    try:
                        final_path = try_download_image(page, image_path)
                        if final_path:
                            touch_job(
                                job, status=STATUS_DONE, image_path=str(final_path)
                            )
                            upsert_job(jobs, job)
                            save_jobs(jobs)
                            print(f"  [{stem}] done.", flush=True)
                            try:
                                page.close()
                            except Exception:
                                pass
                        else:
                            still_pending.append((job, image_path, page))
                    except Exception as e:
                        print(f"  [{stem}] error: {e}", flush=True)
                        touch_job(job, status=STATUS_FAILED)
                        upsert_job(jobs, job)
                        save_jobs(jobs)
                        try:
                            page.close()
                        except Exception:
                            pass

                pending = still_pending
                if pending:
                    print(
                        f"  {len(pending)} job(s) still generating, next check in {POLL_INTERVAL}s...",
                        flush=True,
                    )
                    time.sleep(POLL_INTERVAL)

            # Mark timed-out jobs as failed
            for job, image_path, page in pending:
                stem = Path(job["prompt_file"]).stem
                print(f"  [{stem}] timed out.", flush=True)
                touch_job(job, status=STATUS_FAILED)
                upsert_job(jobs, job)
                save_jobs(jobs)
                try:
                    page.close()
                except Exception:
                    pass

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
                image_path = images_dir.resolve() / f"{p.stem}.png"
                print(f"\n[{p.stem}] project: {job['project_id']}", flush=True)
                open_page(session.page, job["project_id"])
                ok = wait_and_download_image(session.page, image_path)
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
