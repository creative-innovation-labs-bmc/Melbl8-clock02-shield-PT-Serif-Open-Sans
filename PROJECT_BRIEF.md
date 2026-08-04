# Project brief

## Description

Aurecon web-brand font variant of the Shield-optimised Melbourne Clock 02 installation.

## Build brief

Purpose:
Create a separate production repository based on https://github.com/creative-innovation-labs-bmc/Melbl8-clock02-shield while preserving its visual design and behaviour as closely as possible.

Main changes:
- Replace all serif typography with locally hosted PT Serif.
- Replace all sans-serif typography with locally hosted Open Sans.
- Select the closest available weights and tune font size, line height, letter spacing and positional offsets to match the original visual.
- Download and commit the required font files into the repository. Do not depend on Google Fonts at runtime.
- Preserve the fixed 3840 × 804 production canvas and automatic viewport scaling for mobile/browser testing.
- Preserve existing clock animation, timing and screen layout.

Quality and deployment requirements:
- Keep the implementation lightweight and compatible with NVIDIA Shield signage playback.
- Prefer vanilla HTML, CSS and JavaScript with no new runtime dependencies.
- Avoid external network requests during playback.
- Include noindex, nofollow and noarchive directives plus robots.txt.
- Enable GitHub Pages.
- QC at 3840 × 804 and common mobile preview sizes.

Source repository:
https://github.com/creative-innovation-labs-bmc/Melbl8-clock02-shield
