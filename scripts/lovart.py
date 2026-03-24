#!/usr/bin/env python3
"""
Lovart.ai Canvas Automation

Each job = one prompt file → one Lovart project → one generated image.
All jobs are tracked in data/jobs.json for full traceability.

Usage:
    # Single image (first run — creates new project)
    python run.py lovart.py --prompt prompts/01_city.md

    # Batch: submit all .md files in a folder (one project each)
    python run.py lovart.py --batch prompts/

    # Download images for all submitted jobs
    python run.py lovart.py --download-all

    # Retry all failed jobs
    python run.py lovart.py --retry-failed
"""

import argparse
from pathlib import Path

from lovart import (
    Config,
    ImageDownloader,
    JobStore,
    LovartSession,
    SingleExecutor,
    BatchExecutor,
    SubmitHandler,
    WaitHandler,
)


def print_summary(store: JobStore) -> None:
    """Print job summary."""
    print("\n--- Jobs Summary ---", flush=True)
    status_counts = {}
    for job in store.all():
        status_counts[job.status.value] = status_counts.get(job.status.value, 0) + 1
        error_info = f"  [{job.error}]" if job.error else ""
        print(
            f"  {job.stem:30s}  {job.status.value:10s}  {(job.project_id or '')[:16]}{error_info}",
            flush=True,
        )
    print(f"\nStatus counts: {status_counts}", flush=True)


def create_handlers(
    store: JobStore,
    images_dir: Path,
    timeout: int,
    poll_interval: int,
):
    """Create handler instances."""
    downloader = ImageDownloader(images_dir)

    submit_handler = SubmitHandler(
        store=store,
        downloader=downloader,
        images_dir=images_dir,
    )

    wait_handler = WaitHandler(
        store=store,
        downloader=downloader,
        images_dir=images_dir,
        timeout=timeout,
        poll_interval=poll_interval,
    )

    return submit_handler, wait_handler, downloader


def main():
    parser = argparse.ArgumentParser(description="Lovart.ai canvas automation")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--prompt", help="Single prompt .md file")
    group.add_argument("--batch", help="Folder of prompt .md files")
    group.add_argument(
        "--download-all", action="store_true", help="Download images for submitted jobs"
    )
    group.add_argument(
        "--retry-failed", action="store_true", help="Reset and retry all failed jobs"
    )
    parser.add_argument("--headless", action="store_true")
    parser.add_argument(
        "--output-dir",
        help="Directory to save downloaded images (default: scripts/data/images)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="Max wait time for image generation in seconds (default: 300)",
    )
    parser.add_argument(
        "--poll-interval",
        type=int,
        default=10,
        help="Polling interval in seconds (default: 10)",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=10,
        help="Max concurrent browser pages for batch mode (default: 10)",
    )
    args = parser.parse_args()

    images_dir = Path(args.output_dir) if args.output_dir else Config.IMAGES_DIR
    store = JobStore()

    # Create handlers
    submit_handler, wait_handler, downloader = create_handlers(
        store=store,
        images_dir=images_dir,
        timeout=args.timeout,
        poll_interval=args.poll_interval,
    )

    # Handle --retry-failed separately (doesn't need session)
    failed_jobs = []
    if args.retry_failed:
        failed_jobs = store.find_failed()
        if not failed_jobs:
            print("No failed jobs to retry.", flush=True)
            return

        print(f"Resetting {len(failed_jobs)} failed job(s)...", flush=True)
        count = store.reset_failed()
        print(f"Reset {count} job(s) to pending status.", flush=True)

    with LovartSession(headless=args.headless) as session:
        if not session.is_logged_in():
            print("Session expired. Please re-authenticate.")
            return

        if args.prompt:
            p = Path(args.prompt)
            if not p.exists():
                print(f"File not found: {p}")
                return

            executor = SingleExecutor(
                store=store,
                submit_handler=submit_handler,
                wait_handler=wait_handler,
                session=session,
            )
            executor.execute(p)

        elif args.batch:
            folder = Path(args.batch)
            md_files = sorted(folder.glob("*.md"))
            if not md_files:
                print(f"No .md files found in {folder}")
                return
            print(f"Batch: {len(md_files)} prompts", flush=True)

            executor = BatchExecutor(
                store=store,
                submit_handler=submit_handler,
                wait_handler=wait_handler,
                session=session,
                max_concurrent_pages=args.max_pages,
            )
            executor.execute(md_files)

        elif args.download_all:
            pending = store.find_submitted()
            print(f"Downloading images for {len(pending)} submitted job(s)...", flush=True)

            from lovart.handlers import HandlerContext

            for job in pending:
                p = Path(job.prompt_file)
                image_path = images_dir / f"{p.stem}.png"
                print(f"\n[{p.stem}] project: {job.project_id}", flush=True)

                wh = WaitHandler(
                    store=store,
                    downloader=downloader,
                    images_dir=images_dir,
                    timeout=args.timeout,
                    poll_interval=args.poll_interval,
                )
                ctx = HandlerContext(
                    job=job,
                    page_factory=session.new_page,
                    image_path=image_path,
                )
                wh.execute(ctx)

        elif args.retry_failed:
            # Get prompt paths for the failed jobs we reset earlier
            prompt_paths = [Path(job.prompt_file) for job in failed_jobs if Path(job.prompt_file).exists()]

            if prompt_paths:
                print(f"Retrying {len(prompt_paths)} job(s)...", flush=True)
                executor = BatchExecutor(
                    store=store,
                    submit_handler=submit_handler,
                    wait_handler=wait_handler,
                    session=session,
                    max_concurrent_pages=args.max_pages,
                )
                executor.execute(prompt_paths)

    print_summary(store)


if __name__ == "__main__":
    main()