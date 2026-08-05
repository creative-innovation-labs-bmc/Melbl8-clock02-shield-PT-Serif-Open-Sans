from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
BASE_URL = "http://127.0.0.1:8000/screen-8f2c6d71/index.html?debug=1&qc=1425"
SCREENSHOT_PATH = ROOT / "QC_1425.png"
REPORT_PATH = ROOT / "QC_1425_REPORT.json"
ASSET_VERSION = "20260805-1425-centre-v1"
CANVAS_W = 1920
CANVAS_H = 402
ZONE_W = 480
EXPECTED_Y = 201

FIXED_DATE_SCRIPT = """
(() => {
  const NativeDate = globalThis.Date;
  const fixedTime = new NativeDate(2026, 7, 5, 14, 25, 54, 0).valueOf();
  class FixedDate extends NativeDate {
    constructor(...args) {
      super(...(args.length ? args : [fixedTime]));
    }
    static now() { return fixedTime; }
  }
  globalThis.Date = FixedDate;
})();
"""


def main() -> None:
    console_errors: list[str] = []
    page_errors: list[str] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            args=["--disable-dev-shm-usage", "--no-sandbox"],
        )
        page = browser.new_page(viewport={"width": 3840, "height": 804})
        page.add_init_script(FIXED_DATE_SCRIPT)
        page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.goto(BASE_URL, wait_until="networkidle")
        page.wait_for_function(
            "() => window.clockStats && window.clockStats.fps > 0 && window.CLOCK_ASSET_VERSION",
            timeout=15000,
        )
        page.wait_for_timeout(1900)

        result = page.evaluate(
            """() => {
              function alphaBounds(canvas, x0, x1, threshold = 6) {
                const context = canvas.getContext('2d');
                const width = x1 - x0;
                const height = canvas.height;
                const pixels = context.getImageData(x0, 0, width, height).data;
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
                minX += x0;
                maxX += x0;
                return {
                  minX, maxX, minY, maxY,
                  centreX: (minX + maxX) / 2,
                  centreY: (minY + maxY) / 2,
                  width: maxX - minX + 1,
                  height: maxY - minY + 1
                };
              }

              const stage = document.getElementById('stage').getBoundingClientRect();
              const leaf = document.getElementById('leaf-layer');
              const blueprint = document.getElementById('blueprint-layer');
              const leaves = [];
              const outlines = [];
              for (let zone = 0; zone < 4; zone++) {
                leaves.push(alphaBounds(leaf, zone * 480, zone * 480 + 480));
                outlines.push(alphaBounds(blueprint, zone * 480, zone * 480 + 480));
              }
              return {
                stage: {width: stage.width, height: stage.height, x: stage.x, y: stage.y},
                canvas: {width: leaf.width, height: leaf.height},
                stats: window.clockStats,
                assetVersion: window.CLOCK_ASSET_VERSION,
                numberLayout: {...window.NUMBER_LAYOUT_CONFIG},
                digitMeta: {...window.DIGIT_ASSETS.meta},
                leaves,
                outlines,
                resourceUrls: performance.getEntriesByType('resource').map(entry => entry.name)
              };
            }"""
        )

        assert result["stage"]["width"] == 3840, result["stage"]
        assert result["stage"]["height"] == 804, result["stage"]
        assert result["canvas"] == {"width": CANVAS_W, "height": CANVAS_H}, result["canvas"]
        assert result["assetVersion"] == ASSET_VERSION, result["assetVersion"]
        assert result["numberLayout"]["y"] == EXPECTED_Y, result["numberLayout"]
        assert result["digitMeta"]["opticallyCentred"] is True, result["digitMeta"]
        assert result["stats"]["fps"] >= 18, result["stats"]

        expected_assets = {
            "style.css",
            "digit_targets.js",
            "clock.js",
            "digit_outlines_grey.png",
            "digit_outlines_green.png",
            "leaf_atlas.png",
            "PTSerif-Bold.ttf",
            "OpenSans-SemiBold.ttf",
        }
        found_assets: set[str] = set()
        for url in result["resourceUrls"]:
            parsed = urlparse(url)
            name = Path(parsed.path).name
            if name not in expected_assets:
                continue
            found_assets.add(name)
            version = parse_qs(parsed.query).get("v", [None])[0]
            assert version == ASSET_VERSION, (name, url)
        assert expected_assets <= found_assets, sorted(expected_assets - found_assets)

        for zone in range(4):
            expected_x = zone * ZONE_W + ZONE_W / 2
            outline = result["outlines"][zone]
            leaves = result["leaves"][zone]
            assert outline is not None and leaves is not None, (zone, outline, leaves)
            assert abs(outline["centreX"] - expected_x) <= 8, (zone, outline, expected_x)
            assert abs(outline["centreY"] - EXPECTED_Y) <= 8, (zone, outline)
            assert abs(leaves["centreX"] - expected_x) <= 14, (zone, leaves, expected_x)
            assert abs(leaves["centreY"] - EXPECTED_Y) <= 14, (zone, leaves)
            assert outline["minY"] >= 8 and outline["maxY"] <= CANVAS_H - 8, (zone, outline)
            assert leaves["minY"] >= 8 and leaves["maxY"] <= CANVAS_H - 8, (zone, leaves)

        page.evaluate("document.getElementById('debug').hidden = true")
        page.screenshot(path=str(SCREENSHOT_PATH), full_page=True)
        browser.close()

    assert not console_errors, console_errors
    assert not page_errors, page_errors

    report = {
        "fixedDisplayTime": "14:25:54",
        "assetVersion": ASSET_VERSION,
        "result": result,
        "consoleErrors": console_errors,
        "pageErrors": page_errors,
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"14:25 QC failed: {error}", file=sys.stderr)
        raise
