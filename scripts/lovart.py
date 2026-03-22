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

Options:
    --wait-seconds SECONDS   Wait time between checks (default: 180)
    --max-retries COUNT      Max retry attempts (default: 3)
"""

import argparse
from pathlib import Path

from lovart import Config, JobRunner, JobStore, JobStatus, LovartSession


def print_summary(store: JobStore) -> None:
    """Print job summary."""
    print("\n--- Jobs Summary ---", flush=True)
    for job in store.all():
        print(
            f"  {job.stem:30s}  {job.status.value:10s}  {(job.project_id or '')[:16]}",
            flush=True,
        )


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
    parser.add_argument(
        "--wait-seconds",
        type=int,
        default=180,
        help="Wait time between checks in seconds (default: 180)",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=3,
        help="Max retry attempts (default: 3)",
    )
    args = parser.parse_args()

    images_dir = Path(args.output_dir) if args.output_dir else Config.IMAGES_DIR
    store = JobStore()
    runner = JobRunner(
        store,
        images_dir,
        wait_seconds=args.wait_seconds,
        max_retries=args.max_retries,
    )

    with LovartSession(headless=args.headless) as session:
        if not session.is_logged_in():
            print("Session expired. Please re-authenticate.")
            return

        if args.prompt:
            p = Path(args.prompt)
            if not p.exists():
                print(f"File not found: {p}")
                return
            runner.run_single(session.page, p, session)

        elif args.batch:
            folder = Path(args.batch)
            md_files = sorted(folder.glob("*.md"))
            if not md_files:
                print(f"No .md files found in {folder}")
                return
            print(f"Batch: {len(md_files)} prompts — submit, close, wait, retry", flush=True)
            runner.run_batch(md_files, session)

        elif args.download_all:
            runner.download_all_submitted(session)

    print_summary(store)


if __name__ == "__main__":
    main()