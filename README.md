# Melbourne Clock 02, Aurecon font variant

Shield-optimised 3840 × 804 particle clock using locally hosted Aurecon web-brand font substitutes.

## Production screen

`/screen-8f2c6d71/`

## Typography

| Role | Source role | Replacement |
|---|---|---|
| Large particle numerals | TEST-MetaPro-Bold | Open Sans 700 |
| Footer time | MetaSerifWeb W06 Black | PT Serif Regular 400 |
| Vertical labels and date | TEST-MetaPro-Medium | Open Sans SemiBold 600 |

The font files and their OFL licences are committed under `screen-8f2c6d71/fonts/`. Runtime playback makes no external font or network requests.

The large digit target points and outline atlases were regenerated from Open Sans. Geometry matching selected a 460px render, centre Y 215, and horizontal scale 0.970 against the source target distribution.

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
