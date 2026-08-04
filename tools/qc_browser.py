from __future__ import annotations

import json
import sys
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

BASE_URL = "http://127.0.0.1:8000/screen-8f2c6d71/index.html?debug=1"


def check_view(page, width: int, height: int, native: bool) -> dict[str, object]:
    page.set_viewport_size({"width": width, "height": height})
    page.goto(BASE_URL, wait_until="networkidle")
    page.wait_for_function(
        "() => window.clockStats && window.clockStats.fps > 0",
        timeout=15000,
    )
    page.wait_for_timeout(1200)

    result = page.evaluate(
        """() => {
          const stage = document.getElementById('stage').getBoundingClientRect();
          const canvases = [...document.querySelectorAll('canvas')].map(canvas => ({
            width: canvas.width,
            height: canvas.height,
            cssWidth: canvas.getBoundingClientRect().width,
            cssHeight: canvas.getBoundingClientRect().height
          }));
          return {
            stage: {width: stage.width, height: stage.height, x: stage.x, y: stage.y},
            canvases,
            stats: window.clockStats,
            footerFont: document.fonts.check('700 20px "ClockFooter"'),
            sideFont: document.fonts.check('600 8px "ClockSide"')
          };
        }"""
    )

    assert len(result["canvases"]) == 3
    assert all(item["width"] == 1920 and item["height"] == 402 for item in result["canvases"])
    assert result["footerFont"], "PT Serif Bold did not load"
    assert result["sideFont"], "Open Sans did not load"
    assert result["stats"]["fps"] >= 18, result["stats"]
    ratio = result["stage"]["width"] / result["stage"]["height"]
    assert abs(ratio - (3840 / 804)) < 0.01, ratio
    if native:
        assert abs(result["stage"]["width"] - 3840) < 1.5
        assert abs(result["stage"]["height"] - 804) < 1.5
    else:
        assert result["stage"]["width"] <= width + 0.5
        assert result["stage"]["height"] <= height + 0.5
    return result


def main() -> None:
    console_errors: list[str] = []
    page_errors: list[str] = []
    remote_requests: list[str] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            args=["--disable-dev-shm-usage", "--no-sandbox"],
        )
        page = browser.new_page(viewport={"width": 3840, "height": 804})
        page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.on(
            "request",
            lambda request: remote_requests.append(request.url)
            if urlparse(request.url).hostname not in {"127.0.0.1", "localhost"}
            else None,
        )

        native = check_view(page, 3840, 804, native=True)
        mobile = check_view(page, 390, 844, native=False)
        browser.close()

    assert not console_errors, console_errors
    assert not page_errors, page_errors
    assert not remote_requests, remote_requests
    print(
        json.dumps(
            {
                "native": native,
                "mobile": mobile,
                "consoleErrors": console_errors,
                "pageErrors": page_errors,
                "remoteRequests": remote_requests,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"QC failed: {error}", file=sys.stderr)
        raise
