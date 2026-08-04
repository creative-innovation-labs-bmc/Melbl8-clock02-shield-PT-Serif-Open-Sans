from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import Page, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
BASE_URL = "http://127.0.0.1:8000/screen-8f2c6d71/index.html?debug=1"
REPORT_PATH = ROOT / "BROWSER_QC_REPORT.json"
SCREENSHOT_PATH = ROOT / "QC_NATIVE.png"
CANVAS_W = 1920
CANVAS_H = 402
ZONE_W = CANVAS_W / 4
EXPECTED_CENTRE_Y = CANVAS_H / 2

FIXED_DATE_SCRIPT = """
(() => {
  const NativeDate = globalThis.Date;
  const fixedTime = new NativeDate(2026, 7, 5, 8, 8, 8, 0).valueOf();
  class FixedDate extends NativeDate {
    constructor(...args) {
      super(...(args.length ? args : [fixedTime]));
    }
    static now() {
      return fixedTime;
    }
  }
  globalThis.Date = FixedDate;
})();
"""


def check_view(page: Page, width: int, height: int, native: bool) -> dict[str, object]:
    page.set_viewport_size({"width": width, "height": height})
    page.goto(BASE_URL, wait_until="networkidle")
    page.wait_for_function(
        "() => window.clockStats && window.clockStats.fps > 0",
        timeout=15000,
    )
    page.wait_for_timeout(1600)

    result = page.evaluate(
        """() => {
          function targetBounds(points) {
            const xs = points.map(point => point[0]);
            const ys = points.map(point => point[1]);
            const minX = Math.min(...xs);
            const maxX = Math.max(...xs);
            const minY = Math.min(...ys);
            const maxY = Math.max(...ys);
            return {
              minX,
              maxX,
              minY,
              maxY,
              centreX: (minX + maxX) / 2,
              centreY: (minY + maxY) / 2
            };
          }

          function alphaBounds(canvas, x0, x1, threshold = 6) {
            const context = canvas.getContext('2d');
            const width = Math.max(0, Math.floor(x1 - x0));
            const height = canvas.height;
            const pixels = context.getImageData(Math.floor(x0), 0, width, height).data;
            let minX = width;
            let maxX = -1;
            let minY = height;
            let maxY = -1;
            for (let y = 0; y < height; y++) {
              for (let x = 0; x < width; x++) {
                if (pixels[(y * width + x) * 4 + 3] <= threshold) continue;
                if (x < minX) minX = x;
                if (x > maxX) maxX = x;
                if (y < minY) minY = y;
                if (y > maxY) maxY = y;
              }
            }
            if (maxX < 0) return null;
            const globalMinX = minX + x0;
            const globalMaxX = maxX + x0;
            return {
              minX: globalMinX,
              maxX: globalMaxX,
              minY,
              maxY,
              centreX: (globalMinX + globalMaxX) / 2,
              centreY: (minY + maxY) / 2,
              width: maxX - minX + 1,
              height: maxY - minY + 1
            };
          }

          const stage = document.getElementById('stage').getBoundingClientRect();
          const canvases = [...document.querySelectorAll('canvas')].map(canvas => ({
            width: canvas.width,
            height: canvas.height,
            cssWidth: canvas.getBoundingClientRect().width,
            cssHeight: canvas.getBoundingClientRect().height
          }));
          const leafCanvas = document.getElementById('leaf-layer');
          const blueprintCanvas = document.getElementById('blueprint-layer');
          const leafBounds = [];
          const blueprintBounds = [];
          for (let zone = 0; zone < 4; zone++) {
            const x0 = zone * 480;
            const x1 = x0 + 480;
            leafBounds.push(alphaBounds(leafCanvas, x0, x1));
            blueprintBounds.push(alphaBounds(blueprintCanvas, x0, x1));
          }

          return {
            stage: {width: stage.width, height: stage.height, x: stage.x, y: stage.y},
            canvases,
            stats: window.clockStats,
            footerFont: document.fonts.check('700 20px "ClockFooter"'),
            sideFont: document.fonts.check('600 8px "ClockSide"'),
            numberLayout: {...window.NUMBER_LAYOUT_CONFIG},
            digitMeta: {...window.DIGIT_ASSETS.meta},
            targetBounds: window.DIGIT_ASSETS.targets.map(targetBounds),
            leafBounds,
            blueprintBounds
          };
        }"""
    )

    assert len(result["canvases"]) == 3
    assert all(item["width"] == CANVAS_W and item["height"] == CANVAS_H for item in result["canvases"])
    assert result["footerFont"], "PT Serif Bold did not load"
    assert result["sideFont"], "Open Sans did not load"
    assert result["stats"]["fps"] >= 18, result["stats"]
    ratio = result["stage"]["width"] / result["stage"]["height"]
    assert abs(ratio - (3840 / 804)) < 0.01, ratio

    assert result["numberLayout"]["y"] == EXPECTED_CENTRE_Y, result["numberLayout"]
    assert result["digitMeta"]["digitY"] == 240, result["digitMeta"]
    assert result["digitMeta"]["opticallyCentred"] is True, result["digitMeta"]

    for digit, bounds in enumerate(result["targetBounds"]):
        assert abs(bounds["centreX"]) <= 10, (digit, bounds)
        assert abs(bounds["centreY"]) <= 10, (digit, bounds)

    for zone, bounds in enumerate(result["leafBounds"]):
        assert bounds is not None, f"No leaves rendered in zone {zone}"
        expected_x = zone * ZONE_W + ZONE_W / 2
        assert abs(bounds["centreX"] - expected_x) <= 14, (zone, bounds, expected_x)
        assert abs(bounds["centreY"] - EXPECTED_CENTRE_Y) <= 14, (zone, bounds)
        assert bounds["minY"] >= 8, (zone, bounds)
        assert bounds["maxY"] <= CANVAS_H - 8, (zone, bounds)

    if native:
        assert abs(result["stage"]["width"] - 3840) < 1.5
        assert abs(result["stage"]["height"] - 804) < 1.5
        page.evaluate("document.getElementById('debug').hidden = true")
        page.screenshot(path=str(SCREENSHOT_PATH), full_page=True)
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
        page.add_init_script(FIXED_DATE_SCRIPT)
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
    report = {
        "fixedDisplayTime": "08:08:08",
        "native": native,
        "mobile": mobile,
        "consoleErrors": console_errors,
        "pageErrors": page_errors,
        "remoteRequests": remote_requests,
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"QC failed: {error}", file=sys.stderr)
        raise
