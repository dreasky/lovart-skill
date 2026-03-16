#!/usr/bin/env python3
"""
Universal runner for lovart-skill scripts.

Ensures all scripts run inside the skill's own virtual environment.
On first run: creates .venv, installs requirements.txt, installs patchright browser.
On subsequent runs: checks requirements hash and skips install if unchanged.

Usage:
    python run.py patchright_auth.py
    python run.py example.py
    python run.py --check-deps
"""

import hashlib
import json
import os
import sys
import subprocess
import venv
from datetime import datetime, timedelta, timezone
from pathlib import Path

SKILL_DIR = Path(__file__).parent.parent

VENV_DIR = SKILL_DIR / "scripts" / ".venv"
REQUIREMENTS_FILE = SKILL_DIR / "requirements.txt"
AUTH_FILE = SKILL_DIR / "scripts" / "data" / "auth" / "lovart.json"

AUTH_TTL_DAYS = 30

# Scripts that skip auth pre-check
SKIP_AUTH_CHECK = {
    "patchright_auth.py",
}

TIMEOUT_PIP = 600
TIMEOUT_PATCHRIGHT_BROWSER = 300
TIMEOUT_AUTH = 600


# ---------------------------------------------------------------------------
# Venv helpers
# ---------------------------------------------------------------------------


def _venv_python() -> Path:
    if os.name == "nt":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def ensure_venv() -> Path:
    """Create venv if missing. Returns path to venv python."""
    if not VENV_DIR.exists():
        print("Setting up virtual environment...", flush=True)
        try:
            venv.create(VENV_DIR, with_pip=True)
            print("   Virtual environment created.", flush=True)
        except Exception as e:
            print(f"Failed to create venv: {e}")
            sys.exit(1)
    return _venv_python()


# ---------------------------------------------------------------------------
# Pip dependency helpers
# ---------------------------------------------------------------------------


def _requirements_hash() -> str:
    if not REQUIREMENTS_FILE.exists():
        return ""
    return hashlib.sha256(REQUIREMENTS_FILE.read_bytes()).hexdigest()


def ensure_pip_deps():
    """Install pip deps if requirements.txt changed."""
    if not REQUIREMENTS_FILE.exists():
        return

    hash_file = VENV_DIR / ".requirements.hash"
    current_hash = _requirements_hash()

    if hash_file.exists() and hash_file.read_text().strip() == current_hash:
        return  # Up to date

    print("Installing Python dependencies...", flush=True)
    try:
        # Upgrade pip (best-effort, don't fail if it errors)
        subprocess.run(
            [
                str(_venv_python()),
                "-m",
                "pip",
                "install",
                "--upgrade",
                "pip",
                "--quiet",
            ],
            capture_output=True,
            timeout=60,
        )
        result = subprocess.run(
            [str(_venv_python()), "-m", "pip", "install", "-r", str(REQUIREMENTS_FILE)],
            capture_output=True,
            text=True,
            timeout=TIMEOUT_PIP,
        )
        if result.returncode != 0:
            print(f"pip install failed:\n{result.stderr}")
            return
    except subprocess.TimeoutExpired:
        print(f"pip install timed out. Try manually: pip install -r requirements.txt")
        return

    hash_file.write_text(current_hash)
    print("   Dependencies installed.", flush=True)
    _ensure_camoufox_browser()


def _ensure_camoufox_browser():
    """Download Camoufox Firefox binary if not already present."""
    marker = VENV_DIR / ".camoufox-browser-installed"
    if marker.exists():
        return

    # Check camoufox is importable
    result = subprocess.run(
        [str(_venv_python()), "-c", "import camoufox"],
        capture_output=True,
        timeout=10,
    )
    if result.returncode != 0:
        return

    print("Downloading Camoufox browser...", flush=True)
    try:
        result = subprocess.run(
            [str(_venv_python()), "-m", "camoufox", "fetch"],
            timeout=TIMEOUT_PATCHRIGHT_BROWSER,
            text=True,
        )
        if result.returncode == 0:
            marker.write_text("installed")
            print("   Camoufox browser ready.", flush=True)
        else:
            print("   Camoufox browser download failed. Try: python -m camoufox fetch")
    except subprocess.TimeoutExpired:
        print("   Camoufox download timed out.")
    except Exception as e:
        print(f"   Camoufox download error: {e}")


# ---------------------------------------------------------------------------
# Auth pre-check
# ---------------------------------------------------------------------------


def ensure_lovart_auth():
    """Check saved session exists and is not too old. Prompt re-auth if needed."""
    if not AUTH_FILE.exists():
        _prompt_auth()
        return

    try:
        payload = json.loads(AUTH_FILE.read_text())
    except (json.JSONDecodeError, IOError):
        _prompt_auth()
        return

    if not payload.get("cookies"):
        _prompt_auth()
        return

    updated_at = payload.get("updated_at")
    if updated_at:
        try:
            ts = datetime.fromisoformat(updated_at)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            age = datetime.now(timezone.utc) - ts
            if age > timedelta(days=AUTH_TTL_DAYS):
                print(f"Lovart session is {age.days} days old — re-authenticating...")
                _prompt_auth()
        except ValueError:
            pass  # Bad timestamp, proceed anyway


def _prompt_auth():
    print("Lovart.ai authentication required. Opening browser...", flush=True)
    auth_script = SKILL_DIR/ "scripts"  / "patchright_auth.py"
    try:
        result = subprocess.run(
            [str(_venv_python()), str(auth_script)],
            timeout=TIMEOUT_AUTH,
        )
    except subprocess.TimeoutExpired:
        print(
            f"Authentication timed out. Run manually: python run.py patchright_auth.py"
        )
        sys.exit(1)

    if result.returncode != 0:
        print("Authentication failed.")
        sys.exit(1)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    # --check-deps: install everything and exit
    if len(sys.argv) == 2 and sys.argv[1] == "--check-deps":
        ensure_venv()
        ensure_pip_deps()
        print("All dependencies ready.")
        sys.exit(0)

    if len(sys.argv) < 2:
        print("Usage: python run.py <script.py> [args...]")
        print()
        print("Available scripts:")
        print("  patchright_auth.py  - Authenticate with Lovart.ai")
        print("  session.py          - Session loader (import, not run directly)")
        print("  example.py          - Automation example")
        print()
        print("Other commands:")
        print("  --check-deps        - Install/verify all dependencies")
        sys.exit(1)

    script_name = sys.argv[1]
    script_args = sys.argv[2:]

    if not script_name.endswith(".py"):
        script_name += ".py"

    script_path = SKILL_DIR / "scripts"  / script_name
    if not script_path.exists():
        print(f"Script not found: {script_path}")
        sys.exit(1)

    # Ensure environment
    ensure_venv()
    ensure_pip_deps()

    # Auth pre-check (skip for auth script itself and --help)
    if (
        script_name not in SKIP_AUTH_CHECK
        and "--help" not in script_args
        and "-h" not in script_args
    ):
        ensure_lovart_auth()

    # Run
    cmd = [str(_venv_python()), str(script_path)] + script_args
    try:
        result = subprocess.run(cmd)
        sys.exit(result.returncode)
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(130)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
