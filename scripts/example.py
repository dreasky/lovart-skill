#!/usr/bin/env python3
"""
Example: how to use LovartSession for automation after login.
"""

from session import LovartSession


def example_navigate():
    with LovartSession(headless=False) as session:
        if not session.is_logged_in():
            print("Session expired, please re-authenticate.")
            return

        page = session.page
        print(f"Current URL: {page.url}")
        print("Session loaded successfully. Browser will close.")

        # --- put your automation logic here ---


if __name__ == "__main__":
    example_navigate()
