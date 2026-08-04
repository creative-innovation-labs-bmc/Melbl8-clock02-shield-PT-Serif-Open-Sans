from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLOCK_JS = ROOT / "screen-8f2c6d71" / "clock.js"

OLD_POSITION = "  y: 242       // 10 internal px lower, equal to 20 px on the wall"
NEW_POSITION = "  y: 232       // moved 10 internal px higher to prevent bottom cropping"


def main() -> None:
    text = CLOCK_JS.read_text(encoding="utf-8")

    if NEW_POSITION in text:
        print("Number position is already set to y: 232.")
        return

    if OLD_POSITION not in text:
        raise RuntimeError("Expected number layout position was not found in clock.js")

    CLOCK_JS.write_text(
        text.replace(OLD_POSITION, NEW_POSITION, 1),
        encoding="utf-8",
    )
    print("Moved the number centre from y: 242 to y: 232.")


if __name__ == "__main__":
    main()
