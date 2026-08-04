from __future__ import annotations

import json
import re
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SCREEN = ROOT / "screen-8f2c6d71"
CLOCK_JS = SCREEN / "clock.js"
TARGETS_JS = SCREEN / "digit_targets.js"
GREY_ATLAS = SCREEN / "digit_outlines_grey.png"
GREEN_ATLAS = SCREEN / "digit_outlines_green.png"
QC_REPORT = ROOT / "QC_REPORT.json"

TILE_W = 360
TILE_H = 480
NEW_ORIGIN_X = TILE_W / 2
NEW_ORIGIN_Y = TILE_H / 2
NUMBER_Y = 201

LAYOUT_PATTERN = re.compile(
    r"// ={60}\n"
    r"// NUMBER LAYOUT TUNING\n"
    r".*?"
    r"window\.NUMBER_LAYOUT_CONFIG = NUMBER_LAYOUT;",
    flags=re.S,
)

LAYOUT_REPLACEMENT = """// ============================================================
// NUMBER LAYOUT TUNING
// The generated glyph artwork is optically centred in each 480 x 402 zone.
// Internal y: 201 is the exact centre of the 402 px canvas.
// On the 3840 x 804 wall this places the visual centre at y: 402.
// ============================================================
const NUMBER_LAYOUT = {
  scale: 0.88,
  y: 201
};

window.NUMBER_LAYOUT_CONFIG = NUMBER_LAYOUT;"""


def update_runtime_layout() -> None:
    text = CLOCK_JS.read_text(encoding="utf-8")
    updated, count = LAYOUT_PATTERN.subn(LAYOUT_REPLACEMENT, text, count=1)
    if count != 1:
        raise RuntimeError("Expected NUMBER_LAYOUT block was not found in clock.js")
    CLOCK_JS.write_text(updated, encoding="utf-8")


def load_targets() -> dict[str, object]:
    text = TARGETS_JS.read_text(encoding="utf-8")
    match = re.search(r"window\.DIGIT_ASSETS\s*=\s*(\{.*\})\s*;?\s*$", text, flags=re.S)
    if not match:
        raise RuntimeError("Could not parse digit_targets.js")
    return json.loads(match.group(1))


def save_targets(payload: dict[str, object]) -> None:
    TARGETS_JS.write_text(
        "'use strict';\nwindow.DIGIT_ASSETS = "
        + json.dumps(payload, separators=(",", ":"))
        + ";\n",
        encoding="utf-8",
    )


def shifted_tile(tile: Image.Image, dx: int, dy: int) -> Image.Image:
    output = Image.new("RGBA", tile.size, (0, 0, 0, 0))
    output.paste(tile, (dx, dy), tile)
    return output


def centre_digit_assets(payload: dict[str, object]) -> list[dict[str, object]]:
    meta = payload.get("meta")
    targets = payload.get("targets")
    if not isinstance(meta, dict) or not isinstance(targets, list) or len(targets) != 10:
        raise RuntimeError("Digit asset payload is malformed")

    old_origin_y = float(meta.get("digitY", 222))
    grey = Image.open(GREY_ATLAS).convert("RGBA")
    green = Image.open(GREEN_ATLAS).convert("RGBA")
    centred_grey = Image.new("RGBA", grey.size, (0, 0, 0, 0))
    centred_green = Image.new("RGBA", green.size, (0, 0, 0, 0))
    shifts: list[dict[str, object]] = []

    for digit in range(10):
        left = digit * TILE_W
        grey_tile = grey.crop((left, 0, left + TILE_W, TILE_H))
        green_tile = green.crop((left, 0, left + TILE_W, TILE_H))
        bbox = grey_tile.getchannel("A").getbbox()
        if bbox is None:
            raise RuntimeError(f"Digit {digit} outline is empty")

        bbox_left, bbox_top, bbox_right, bbox_bottom = bbox
        source_centre_x = (bbox_left + bbox_right) / 2
        source_centre_y = (bbox_top + bbox_bottom) / 2
        dx = int(round(NEW_ORIGIN_X - source_centre_x))
        dy = int(round(NEW_ORIGIN_Y - source_centre_y))

        shifted_grey = shifted_tile(grey_tile, dx, dy)
        shifted_green = shifted_tile(green_tile, dx, dy)
        centred_grey.paste(shifted_grey, (left, 0), shifted_grey)
        centred_green.paste(shifted_green, (left, 0), shifted_green)

        digit_targets = targets[digit]
        if not isinstance(digit_targets, list):
            raise RuntimeError(f"Digit {digit} target list is malformed")
        targets[digit] = [
            [
                round(float(point[0]) + dx, 4),
                round(float(point[1]) + old_origin_y + dy - NEW_ORIGIN_Y, 4),
            ]
            for point in digit_targets
        ]

        new_bbox = shifted_grey.getchannel("A").getbbox()
        if new_bbox is None:
            raise RuntimeError(f"Digit {digit} disappeared while centring")
        new_left, new_top, new_right, new_bottom = new_bbox
        residual_x = (new_left + new_right) / 2 - NEW_ORIGIN_X
        residual_y = (new_top + new_bottom) / 2 - NEW_ORIGIN_Y
        if abs(residual_x) > 0.51 or abs(residual_y) > 0.51:
            raise RuntimeError(
                f"Digit {digit} centring residual is too large: {residual_x}, {residual_y}"
            )

        shifts.append(
            {
                "digit": digit,
                "x": dx,
                "y": dy,
                "residualX": residual_x,
                "residualY": residual_y,
            }
        )

    centred_grey.save(GREY_ATLAS, optimize=True)
    centred_green.save(GREEN_ATLAS, optimize=True)
    meta["digitY"] = int(NEW_ORIGIN_Y)
    meta["opticallyCentred"] = True
    meta["tileCentre"] = [NEW_ORIGIN_X, NEW_ORIGIN_Y]
    meta["perDigitShift"] = shifts
    return shifts


def update_qc_report(shifts: list[dict[str, object]]) -> None:
    report: dict[str, object] = {}
    if QC_REPORT.exists():
        report = json.loads(QC_REPORT.read_text(encoding="utf-8"))
    report["numberLayout"] = {
        "internalCanvas": [1920, 402],
        "zoneSize": [480, 402],
        "scale": 0.88,
        "centreY": NUMBER_Y,
        "physicalCentreY": NUMBER_Y * 2,
    }
    report["opticalCentering"] = {
        "tileCentre": [NEW_ORIGIN_X, NEW_ORIGIN_Y],
        "perDigitShift": shifts,
        "outlineAndParticleOriginsAligned": True,
    }
    QC_REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    update_runtime_layout()
    payload = load_targets()
    shifts = centre_digit_assets(payload)
    save_targets(payload)
    update_qc_report(shifts)
    print("Optically centred all ten large numeral assets at canvas y: 201.")


if __name__ == "__main__":
    main()
