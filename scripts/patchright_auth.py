#!/usr/bin/env python3
"""
Camoufox-based Lovart.ai Authentication

Uses Camoufox (Firefox-based anti-detection browser) which reliably passes
Cloudflare Turnstile verification — Chromium-based tools are detected by CF.

Opens browser for manual login (email + password + email verification code).
Waits for redirect to /zh/home, then extracts and saves session cookies.
"""

import sys

from lovart import Authenticator, AuthStore


def main():
    authenticator = Authenticator()
    store = AuthStore()

    success, state = authenticator.authenticate()
    if success and state:
        store.save(state)
        sys.exit(0)
    sys.exit(1)


if __name__ == "__main__":
    main()