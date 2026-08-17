#!/usr/bin/env python3
"""Four-tab smoke check for Stack Ranker.

Visits each top tab, confirms the page loads with a non-empty <title> and no
"Something went wrong" error text. Not part of the pytest suite (CI is
pytest-only); run standalone: `python scripts/smoke_tabs.py`.
"""
import os
import sys

from playwright.sync_api import sync_playwright, Error as PWError

BASE = os.environ.get("BASE_URL", "http://127.0.0.1:8000").rstrip("/")
PATHS = ["/projects", "/optimize", "/pool", "/contest"]


def main() -> int:
    try:
        with sync_playwright() as p:
            browser = p.webkit.launch()
            page = browser.new_page()

            # A quick reachability probe; if the server is down, exit 2.
            probe = None
            try:
                probe = page.goto(BASE + "/")
            except PWError as e:
                print(f"ERROR server unreachable at {BASE}: {e}")
                browser.close()
                return 2

            if probe is not None and probe.status >= 500:
                print(f"ERROR server at {BASE} returned status "
                      f"{probe.status}")
                browser.close()
                return 2

            ok = True
            for path in PATHS:
                response = page.goto(BASE + path)
                title = (page.title() or "").strip()
                body = page.inner_text("body", timeout=5000)

                loaded = response is not None and response.status < 400
                no_error = "Something went wrong" not in body
                good = bool(title) and no_error and loaded

                if good:
                    print(f"OK {path} {title}")
                else:
                    reason = []
                    if not loaded:
                        reason.append("no-load")
                    if not title:
                        reason.append("empty-title")
                    if not no_error:
                        reason.append("error-text")
                    print(f"FAIL {path} [{','.join(reason)}] "
                          f"title={title!r}")
                ok = ok and good

            browser.close()
    except PWError as e:
        print(f"ERROR playwright/browser failure: {e}")
        return 2

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
