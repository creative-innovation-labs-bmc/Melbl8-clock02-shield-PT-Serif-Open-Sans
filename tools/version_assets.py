from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCREEN = ROOT / "screen-8f2c6d71"
INDEX_HTML = SCREEN / "index.html"
CLOCK_JS = SCREEN / "clock.js"
ASSET_VERSION = "20260805-1425-centre-v1"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"Expected one {label} occurrence, found {count}")
    return text.replace(old, new, 1)


def version_index() -> None:
    text = INDEX_HTML.read_text(encoding="utf-8")

    text = replace_once(
        text,
        '  <meta name="referrer" content="no-referrer">\n',
        '  <meta name="referrer" content="no-referrer">\n'
        '  <meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">\n'
        '  <meta http-equiv="Pragma" content="no-cache">\n'
        '  <meta http-equiv="Expires" content="0">\n',
        "cache-control meta block",
    )

    assets = (
        "fonts/PTSerif-Bold.ttf",
        "fonts/OpenSans-SemiBold.ttf",
        "digit_outlines_grey.png",
        "digit_outlines_green.png",
        "leaf_atlas.png",
        "style.css",
        "digit_targets.js",
        "clock.js",
    )
    for asset in assets:
        text = replace_once(
            text,
            asset,
            f"{asset}?v={ASSET_VERSION}",
            f"index reference for {asset}",
        )

    INDEX_HTML.write_text(text, encoding="utf-8")


def version_runtime_assets() -> None:
    text = CLOCK_JS.read_text(encoding="utf-8")

    anchor = "const BG = '#1C1B1C';\n"
    replacement = (
        "const BG = '#1C1B1C';\n"
        f"const ASSET_VERSION = '{ASSET_VERSION}';\n"
        "window.CLOCK_ASSET_VERSION = ASSET_VERSION;\n"
        "function assetUrl(path) {\n"
        "  return `${path}?v=${ASSET_VERSION}`;\n"
        "}\n"
    )
    text = replace_once(text, anchor, replacement, "runtime asset version block")

    runtime_assets = (
        "digit_outlines_grey.png",
        "digit_outlines_green.png",
        "leaf_atlas.png",
        "fonts/PTSerif-Bold.ttf",
        "fonts/OpenSans-SemiBold.ttf",
    )
    for asset in runtime_assets:
        text = replace_once(
            text,
            f"'{asset}'",
            f"assetUrl('{asset}')",
            f"runtime reference for {asset}",
        )

    CLOCK_JS.write_text(text, encoding="utf-8")


def main() -> None:
    version_index()
    version_runtime_assets()
    print(f"Versioned all browser assets with {ASSET_VERSION}.")


if __name__ == "__main__":
    main()
