from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import urllib.request
from pathlib import Path
from typing import Iterable

import numpy as np
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[1]
SCREEN = ROOT / "screen-8f2c6d71"
SOURCE_REPO = "https://github.com/creative-innovation-labs-bmc/Melbl8-clock02-shield.git"
SOURCE_REF = "bc0416e62e711af0d3aaa3af2ac2cb30cfd77a8f"

OPEN_SANS_URL = "https://raw.githubusercontent.com/google/fonts/main/ofl/opensans/OpenSans%5Bwdth,wght%5D.ttf"
OPEN_SANS_LICENSE_URL = "https://raw.githubusercontent.com/google/fonts/main/ofl/opensans/OFL.txt"
PT_SERIF_REGULAR_URL = "https://raw.githubusercontent.com/google/fonts/main/ofl/ptserif/PT_Serif-Web-Regular.ttf"
PT_SERIF_BOLD_URL = "https://raw.githubusercontent.com/google/fonts/main/ofl/ptserif/PT_Serif-Web-Bold.ttf"
PT_SERIF_LICENSE_URL = "https://raw.githubusercontent.com/google/fonts/main/ofl/ptserif/OFL.txt"

TILE_W = 360
TILE_H = 480
DIGIT_Y = 222
PARTICLE_COUNT = 220
GRID_SPACING = 9
GREY = (187, 198, 195)
GREEN = (137, 201, 37)


def run(*args: str, cwd: Path | None = None) -> None:
    subprocess.run(args, cwd=cwd, check=True)


def download(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "aurecon-clock-font-build"})
    with urllib.request.urlopen(request, timeout=90) as response:
        destination.write_bytes(response.read())


def font_name(path: Path) -> str:
    font = TTFont(path)
    try:
        names = font["name"].names
        for name_id in (4, 6, 1):
            for item in names:
                if item.nameID == name_id:
                    try:
                        return item.toUnicode()
                    except Exception:
                        continue
    finally:
        font.close()
    return path.name


def instantiate_open_sans(variable_path: Path, output_path: Path, weight: int) -> None:
    variable_font = TTFont(variable_path)
    static_font = instantiateVariableFont(
        variable_font,
        {"wght": float(weight), "wdth": 100.0},
        inplace=False,
        optimize=True,
    )
    static_font.save(output_path)
    static_font.close()
    variable_font.close()


def mulberry32_sequence(seed: int, count: int) -> list[float]:
    # Exact unsigned 32-bit equivalent of the generator previously used in clock.js.
    values: list[float] = []
    state = seed & 0xFFFFFFFF
    for _ in range(count):
        state = (state + 0x6D2B79F5) & 0xFFFFFFFF
        t = state
        t = ((t ^ (t >> 15)) * (t | 1)) & 0xFFFFFFFF
        t ^= (t + (((t ^ (t >> 7)) * (t | 61)) & 0xFFFFFFFF)) & 0xFFFFFFFF
        values.append(((t ^ (t >> 14)) & 0xFFFFFFFF) / 4294967296.0)
    return values


def shuffle_js(values: list[tuple[float, float]], seed: int) -> None:
    random_values = iter(mulberry32_sequence(seed, max(0, len(values) - 1)))
    for i in range(len(values) - 1, 0, -1):
        j = int(next(random_values) * (i + 1))
        values[i], values[j] = values[j], values[i]


def render_digit_mask(
    font_path: Path,
    digit: str,
    font_size: int,
    centre_y: int,
    x_scale: float,
) -> Image.Image:
    # Render at high resolution before downsampling to keep the outlines stable.
    supersample = 2
    font = ImageFont.truetype(str(font_path), font_size * supersample)
    large = Image.new("L", (TILE_W * supersample, TILE_H * supersample), 0)
    draw = ImageDraw.Draw(large)

    # Pillow's "mm" anchor centres the visible glyph. The vertical offset is
    # searched against the source target geometry below.
    draw.text(
        (TILE_W * supersample / 2, centre_y * supersample),
        digit,
        font=font,
        fill=255,
        anchor="mm",
    )

    if abs(x_scale - 1.0) > 1e-6:
        scaled_w = max(1, round(large.width * x_scale))
        scaled = large.resize((scaled_w, large.height), Image.Resampling.LANCZOS)
        if scaled_w >= large.width:
            left = (scaled_w - large.width) // 2
            large = scaled.crop((left, 0, left + large.width, large.height))
        else:
            fitted = Image.new("L", large.size, 0)
            fitted.paste(scaled, ((large.width - scaled_w) // 2, 0))
            large = fitted

    return large.resize((TILE_W, TILE_H), Image.Resampling.LANCZOS)


def sampled_targets(mask: Image.Image, digit: int) -> list[tuple[float, float]]:
    pixels = np.asarray(mask)
    candidates: list[tuple[float, float]] = []
    row = 0
    py = 3
    while py < TILE_H - 3:
        offset = GRID_SPACING / 2 if row & 1 else 0
        px = 3 + offset
        while px < TILE_W - 3:
            sample_x = int(round(px))
            sample_y = int(round(py))
            if pixels[sample_y, sample_x] > 110:
                candidates.append((px - TILE_W / 2, py - DIGIT_Y))
            px += GRID_SPACING
        row += 1
        py += GRID_SPACING

    if not candidates:
        raise RuntimeError(f"No target candidates generated for digit {digit}")

    shuffle_js(candidates, 9001 + digit * 311)
    step = len(candidates) / PARTICLE_COUNT
    return [candidates[int(i * step) % len(candidates)] for i in range(PARTICLE_COUNT)]


def load_original_targets(path: Path) -> list[list[list[float]]]:
    text = path.read_text(encoding="utf-8")
    match = re.search(r"window\.DIGIT_ASSETS\s*=\s*(\{.*\})\s*;?\s*$", text, flags=re.S)
    if not match:
        raise RuntimeError("Could not parse original digit_targets.js")
    data = json.loads(match.group(1))
    return data["targets"]


def point_signature(points: Iterable[Iterable[float]]) -> np.ndarray:
    arr = np.asarray(list(points), dtype=np.float64)
    x = arr[:, 0]
    y = arr[:, 1]
    return np.array(
        [
            np.quantile(x, 0.02),
            np.quantile(x, 0.25),
            np.median(x),
            np.quantile(x, 0.75),
            np.quantile(x, 0.98),
            np.quantile(y, 0.02),
            np.quantile(y, 0.25),
            np.median(y),
            np.quantile(y, 0.75),
            np.quantile(y, 0.98),
            x.std(),
            y.std(),
        ],
        dtype=np.float64,
    )


def geometry_score(
    original_targets: list[list[list[float]]],
    font_path: Path,
    font_size: int,
    centre_y: int,
    x_scale: float,
) -> float:
    scores: list[float] = []
    for digit in range(10):
        mask = render_digit_mask(font_path, str(digit), font_size, centre_y, x_scale)
        candidate = sampled_targets(mask, digit)
        original_signature = point_signature(original_targets[digit])
        candidate_signature = point_signature(candidate)
        # Normalise pixel-scale differences to keep width, height and placement balanced.
        delta = (candidate_signature - original_signature) / np.array(
            [80, 80, 80, 80, 80, 150, 150, 150, 150, 150, 80, 150],
            dtype=np.float64,
        )
        scores.append(float(np.mean(delta * delta)))
    return float(np.mean(scores))


def choose_digit_geometry(
    original_targets: list[list[list[float]]],
    fonts: dict[int, Path],
) -> tuple[int, int, int, float, float]:
    candidates: list[tuple[float, int, int, int, float]] = []
    for weight, path in fonts.items():
        for font_size in (444, 456, 468, 480):
            for centre_y in (218, 226, 234):
                for x_scale in (0.92, 0.98, 1.04, 1.10):
                    score = geometry_score(original_targets, path, font_size, centre_y, x_scale)
                    candidates.append((score, weight, font_size, centre_y, x_scale))

    candidates.sort(key=lambda item: item[0])
    _, weight, coarse_size, coarse_y, coarse_scale = candidates[0]

    refined: list[tuple[float, int, int, int, float]] = []
    for font_size in range(coarse_size - 4, coarse_size + 5, 2):
        for centre_y in range(coarse_y - 3, coarse_y + 4, 3):
            for x_scale in np.arange(coarse_scale - 0.02, coarse_scale + 0.021, 0.01):
                score = geometry_score(
                    original_targets,
                    fonts[weight],
                    font_size,
                    centre_y,
                    float(round(x_scale, 3)),
                )
                refined.append((score, weight, font_size, centre_y, float(round(x_scale, 3))))

    refined.sort(key=lambda item: item[0])
    return refined[0][1], refined[0][2], refined[0][3], refined[0][4], refined[0][0]


def colourise_outline(mask: Image.Image, colour: tuple[int, int, int]) -> Image.Image:
    # A two-pixel internal/external contour stays clear after the runtime's
    # repeated low-alpha transforms.
    expanded = mask.filter(ImageFilter.MaxFilter(5))
    contracted = mask.filter(ImageFilter.MinFilter(5))
    outer = np.asarray(expanded, dtype=np.int16)
    inner = np.asarray(contracted, dtype=np.int16)
    alpha = np.clip(outer - inner, 0, 255).astype(np.uint8)
    image = Image.new("RGBA", mask.size, (*colour, 0))
    image.putalpha(Image.fromarray(alpha, mode="L"))
    return image


def build_digit_assets(
    output_dir: Path,
    font_path: Path,
    font_size: int,
    centre_y: int,
    x_scale: float,
    weight: int,
    score: float,
) -> None:
    grey_atlas = Image.new("RGBA", (TILE_W * 10, TILE_H), (0, 0, 0, 0))
    green_atlas = Image.new("RGBA", (TILE_W * 10, TILE_H), (0, 0, 0, 0))
    all_targets: list[list[list[float]]] = []

    for digit in range(10):
        mask = render_digit_mask(font_path, str(digit), font_size, centre_y, x_scale)
        targets = sampled_targets(mask, digit)
        all_targets.append([[x, y] for x, y in targets])
        grey_atlas.paste(colourise_outline(mask, GREY), (digit * TILE_W, 0))
        green_atlas.paste(colourise_outline(mask, GREEN), (digit * TILE_W, 0))

    grey_atlas.save(output_dir / "digit_outlines_grey.png", optimize=True)
    green_atlas.save(output_dir / "digit_outlines_green.png", optimize=True)
    payload = {
        "targets": all_targets,
        "meta": {
            "tileWidth": TILE_W,
            "tileHeight": TILE_H,
            "digitY": DIGIT_Y,
            "particleCount": PARTICLE_COUNT,
            "fontFamily": "Open Sans",
            "fontWeight": weight,
            "fontSize": font_size,
            "renderCentreY": centre_y,
            "horizontalScale": x_scale,
            "geometryScore": round(score, 8),
        },
    }
    (output_dir / "digit_targets.js").write_text(
        "'use strict';\nwindow.DIGIT_ASSETS = "
        + json.dumps(payload, separators=(",", ":"))
        + ";\n",
        encoding="utf-8",
    )


def measured_width(font_path: Path, size: int, text: str) -> float:
    font = ImageFont.truetype(str(font_path), size)
    left, _, right, _ = font.getbbox(text)
    return float(right - left)


def replace_clock_fonts(clock_js: str, footer_scale: float, side_scale: float) -> str:
    clock_js = clock_js.replace(
        "let footerFont = '700 20px Georgia, serif';",
        "let footerFont = '400 20px Georgia, serif';",
    )
    clock_js = clock_js.replace(
        "let sideFont = '600 8px Arial, sans-serif';",
        "let sideFont = '600 8px Arial, sans-serif';",
    )
    clock_js = clock_js.replace(
        "let lastSecond = -1;",
        f"const FOOTER_X_SCALE = {footer_scale:.4f};\n"
        f"const SIDE_X_SCALE = {side_scale:.4f};\n"
        "let lastSecond = -1;",
        1,
    )

    old_loader = """async function loadOptionalFont(name, url, cssValue) {
  if (!('FontFace' in window)) return false;
  try {
    const face = new FontFace(name, `url(${url})`);
    await face.load();
    document.fonts.add(face);
    if (name === 'ClockFooter') footerFont = `${cssValue}px \"${name}\"`;
    if (name === 'ClockSide') sideFont = `${cssValue}px \"${name}\"`;
    return true;
  } catch {
    return false;
  }
}"""
    new_loader = """async function loadOptionalFont(name, url, cssValue, weight) {
  if (!('FontFace' in window)) return false;
  try {
    const face = new FontFace(name, `url(${url})`, {
      style: 'normal',
      weight: String(weight)
    });
    await face.load();
    document.fonts.add(face);
    if (name === 'ClockFooter') footerFont = `${weight} ${cssValue}px \"${name}\"`;
    if (name === 'ClockSide') sideFont = `${weight} ${cssValue}px \"${name}\"`;
    return true;
  } catch {
    return false;
  }
}"""
    if old_loader not in clock_js:
        raise RuntimeError("Font loader block was not found in source clock.js")
    clock_js = clock_js.replace(old_loader, new_loader)

    old_footer_draw = """  for (let zone = 0; zone < 4; zone++) {
    layoutCtx.fillText(time, zone * ZONE_W + 20, BASE_H - 15);
  }"""
    new_footer_draw = """  for (let zone = 0; zone < 4; zone++) {
    layoutCtx.save();
    layoutCtx.translate(zone * ZONE_W + 20, BASE_H - 15);
    layoutCtx.scale(FOOTER_X_SCALE, 1);
    layoutCtx.fillText(time, 0, 0);
    layoutCtx.restore();
  }"""
    if old_footer_draw not in clock_js:
        raise RuntimeError("Footer draw block was not found in source clock.js")
    clock_js = clock_js.replace(old_footer_draw, new_footer_draw)

    clock_js = clock_js.replace(
        "    layoutCtx.translate(sideX, 20);\n    layoutCtx.rotate(-Math.PI / 2);",
        "    layoutCtx.translate(sideX, 20);\n"
        "    layoutCtx.rotate(-Math.PI / 2);\n"
        "    layoutCtx.scale(SIDE_X_SCALE, 1);",
    )
    clock_js = clock_js.replace(
        "    layoutCtx.translate(sideX, BASE_H - 20);\n    layoutCtx.rotate(-Math.PI / 2);",
        "    layoutCtx.translate(sideX, BASE_H - 20);\n"
        "    layoutCtx.rotate(-Math.PI / 2);\n"
        "    layoutCtx.scale(SIDE_X_SCALE, 1);",
    )

    old_loads = """  await Promise.all([
    loadOptionalFont('ClockFooter', 'MS-Bk.otf', 20),
    loadOptionalFont('ClockSide', 'MP-M.ttf', 8)
  ]);"""
    new_loads = """  await Promise.all([
    loadOptionalFont('ClockFooter', 'fonts/PTSerif-Regular.ttf', 20, 400),
    loadOptionalFont('ClockSide', 'fonts/OpenSans-SemiBold.ttf', 8, 600)
  ]);"""
    if old_loads not in clock_js:
        raise RuntimeError("Font load calls were not found in source clock.js")
    return clock_js.replace(old_loads, new_loads)


def enhance_index(index_html: str) -> str:
    preloads = """  <link rel="preload" href="fonts/PTSerif-Regular.ttf" as="font" type="font/ttf" crossorigin>
  <link rel="preload" href="fonts/OpenSans-SemiBold.ttf" as="font" type="font/ttf" crossorigin>
  <link rel="preload" href="digit_outlines_grey.png" as="image" type="image/png">
  <link rel="preload" href="digit_outlines_green.png" as="image" type="image/png">
  <link rel="preload" href="leaf_atlas.png" as="image" type="image/png">
"""
    return index_html.replace(
        '  <link rel="stylesheet" href="style.css">\n',
        preloads + '  <link rel="stylesheet" href="style.css">\n',
    ).replace(
        '<main id="stage" aria-label="Particle clock">',
        '<main id="stage" aria-label="Melbourne particle clock">',
    )


def build_readme(
    original_names: dict[str, str],
    chosen_weight: int,
    chosen_size: int,
    chosen_y: int,
    chosen_scale: float,
) -> str:
    return f"""# Melbourne Clock 02, Aurecon font variant

Shield-optimised 3840 × 804 particle clock using locally hosted Aurecon web-brand font substitutes.

## Production screen

`/screen-8f2c6d71/`

## Typography

| Role | Source role | Replacement |
|---|---|---|
| Large particle numerals | {original_names['main']} | Open Sans {chosen_weight} |
| Footer time | {original_names['footer']} | PT Serif Regular 400 |
| Vertical labels and date | {original_names['side']} | Open Sans SemiBold 600 |

The font files and their OFL licences are committed under `screen-8f2c6d71/fonts/`. Runtime playback makes no external font or network requests.

The large digit target points and outline atlases were regenerated from Open Sans. Geometry matching selected a {chosen_size}px render, centre Y {chosen_y}, and horizontal scale {chosen_scale:.3f} against the source target distribution.

## Display

- Production canvas: 3840 × 804
- Internal render: 1920 × 402
- Runtime: vanilla HTML, CSS and Canvas 2D JavaScript
- Shield profile: 30 fps target, 220 particles per digit zone
- Mobile/browser preview: automatically scales while preserving the 3840:804 aspect ratio
- Debug view: append `?debug=1`
- Lower-load profile remains available in the source code as `safe`

## Privacy and discovery

The root page remains blank. The production screen uses a non-descriptive path, robots directives block indexing, and `robots.txt` disallows crawling. This reduces discovery but is not access control.

## Build and QC

`tools/build_clock.py` copies the production source, downloads the official Google Fonts files, creates static Open Sans instances, regenerates the digit assets and updates the local font loading.

`tools/qc_browser.py` checks the native and mobile layouts, local-only requests, font loading, canvas dimensions, console errors and animation frame statistics.
"""


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="clock-font-build-") as temp_name:
        temp = Path(temp_name)
        source = temp / "source"
        run("git", "clone", "--depth", "1", SOURCE_REPO, str(source))
        run("git", "fetch", "--depth", "1", "origin", SOURCE_REF, cwd=source)
        run("git", "checkout", "--detach", SOURCE_REF, cwd=source)

        source_screen = source / SCREEN.name
        if not source_screen.exists():
            raise RuntimeError("Source screen directory is missing")

        SCREEN.mkdir(parents=True, exist_ok=True)
        for name in ("index.html", "style.css", "clock.js", "leaf_atlas.png"):
            shutil.copy2(source_screen / name, SCREEN / name)

        for name in ("index.html", "404.html", "robots.txt"):
            shutil.copy2(source / name, ROOT / name)
        (ROOT / ".nojekyll").touch()

        # Remove starter files and obsolete runtime assets from this variant.
        for relative in ("styles.css", "app.js", "PROJECT_BRIEF.md", ".factory-complete"):
            path = ROOT / relative
            if path.exists():
                path.unlink()
        for relative in (
            "MP-B.ttf",
            "MP-M.ttf",
            "MS-Bk.otf",
            "p5.min.js",
            "sketch.js",
            "sprite_32.png",
            "leaves_32",
            "leaves_64",
        ):
            path = SCREEN / relative
            if path.is_dir():
                shutil.rmtree(path)
            elif path.exists():
                path.unlink()

        fonts_dir = SCREEN / "fonts"
        fonts_dir.mkdir(parents=True, exist_ok=True)
        variable_open_sans = temp / "OpenSans-variable.ttf"
        download(OPEN_SANS_URL, variable_open_sans)
        download(OPEN_SANS_LICENSE_URL, fonts_dir / "OFL-Open-Sans.txt")
        download(PT_SERIF_REGULAR_URL, fonts_dir / "PTSerif-Regular.ttf")
        download(PT_SERIF_BOLD_URL, fonts_dir / "PTSerif-Bold.ttf")
        download(PT_SERIF_LICENSE_URL, fonts_dir / "OFL-PT-Serif.txt")

        open_sans_fonts: dict[int, Path] = {}
        for weight, filename in ((600, "OpenSans-SemiBold.ttf"), (700, "OpenSans-Bold.ttf"), (800, "OpenSans-ExtraBold.ttf")):
            output = fonts_dir / filename
            instantiate_open_sans(variable_open_sans, output, weight)
            open_sans_fonts[weight] = output

        original_names = {
            "main": font_name(source_screen / "MP-B.ttf"),
            "footer": font_name(source_screen / "MS-Bk.otf"),
            "side": font_name(source_screen / "MP-M.ttf"),
        }
        original_targets = load_original_targets(source_screen / "digit_targets.js")
        chosen_weight, chosen_size, chosen_y, chosen_scale, score = choose_digit_geometry(
            original_targets,
            {700: open_sans_fonts[700], 800: open_sans_fonts[800]},
        )
        build_digit_assets(
            SCREEN,
            open_sans_fonts[chosen_weight],
            chosen_size,
            chosen_y,
            chosen_scale,
            chosen_weight,
            score,
        )

        # Match text widths to their source roles while retaining each replacement's real vertical metrics.
        original_footer_width = measured_width(source_screen / "MS-Bk.otf", 20, "00:00:00")
        new_footer_width = measured_width(fonts_dir / "PTSerif-Regular.ttf", 20, "00:00:00")
        footer_scale = max(0.82, min(1.18, original_footer_width / max(1.0, new_footer_width)))

        side_sample = "30 SEPTEMBER 2026 WEDNESDAY"
        original_side_width = measured_width(source_screen / "MP-M.ttf", 8, side_sample)
        new_side_width = measured_width(fonts_dir / "OpenSans-SemiBold.ttf", 8, side_sample)
        side_scale = max(0.82, min(1.18, original_side_width / max(1.0, new_side_width)))

        clock_js = (SCREEN / "clock.js").read_text(encoding="utf-8")
        (SCREEN / "clock.js").write_text(
            replace_clock_fonts(clock_js, footer_scale, side_scale),
            encoding="utf-8",
        )
        index_html = (SCREEN / "index.html").read_text(encoding="utf-8")
        (SCREEN / "index.html").write_text(enhance_index(index_html), encoding="utf-8")

        (ROOT / "README.md").write_text(
            build_readme(original_names, chosen_weight, chosen_size, chosen_y, chosen_scale),
            encoding="utf-8",
        )
        report = {
            "sourceCommit": SOURCE_REF,
            "sourceFonts": original_names,
            "replacementFonts": {
                "main": f"Open Sans {chosen_weight}",
                "footer": "PT Serif Regular 400",
                "side": "Open Sans SemiBold 600",
            },
            "digitGeometry": {
                "fontSize": chosen_size,
                "renderCentreY": chosen_y,
                "horizontalScale": chosen_scale,
                "score": score,
            },
            "textWidthCompensation": {
                "footer": footer_scale,
                "side": side_scale,
            },
            "runtime": {
                "canvas": [1920, 402],
                "physicalDisplay": [3840, 804],
                "targetFps": 30,
                "particlesPerZone": 220,
                "externalRuntimeRequests": 0,
            },
        }
        (ROOT / "QC_REPORT.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
