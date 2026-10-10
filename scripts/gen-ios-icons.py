#!/usr/bin/env python3
"""Generate the nanoMuse app icon for android/src/ios from assets/brand/.

Idempotent; re-run after every upstream pull (CONTRIBUTING.md). Writes 1024x1024 PNGs:

- Assets.xcassets/AppIcon.appiconset/Icon-1024.png       the one-stroke N in the brand gradient
                                                          on a white tile (the default icon)
- Assets.xcassets/AppIcon.appiconset/Icon-1024-Dark.png  the same mark on the dark tile (the
                                                          automatic dark appearance)
- Resources/AlternateIcons/AppIcon-{Light,Dark,LegacyLight,LegacyDark}.png  the four skins the
  in-app icon picker offers (Info.plist CFBundleAlternateIcons): light / dark with the gradient
  mark, "legacy" light with the flat brand blue, "legacy" dark with a white mark (the same
  pairing as the Android classic skins).

iOS applies its own corner mask, so the tiles are full squares. The mark sits in the same frame
as the Android legacy launcher icon (assets/brand/nanomuse-mark.svg is drawn on a 100-unit tile).
Needs Playwright with Chromium (`pip install playwright && playwright install chromium`).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IOS = ROOT / "android" / "src" / "ios"
ICONSET = IOS / "Assets.xcassets" / "AppIcon.appiconset"
ALTERNATE = IOS / "Resources" / "AlternateIcons"
SIZE = 1024


def android_icons():  # noqa: ANN201  (module name has a hyphen)
    spec = importlib.util.spec_from_file_location(
        "gen_android_icons", ROOT / "scripts" / "gen-android-icons.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def tile(d: str, background: str, stroke_start: str, stroke_end: str | None = None) -> str:
    """A full-square tile with the mark; a gradient when two stroke colours are given."""
    grad = (
        f'<linearGradient id="g" gradientUnits="userSpaceOnUse" x1="12.6" y1="50" x2="87.8" y2="50">'
        f'<stop offset="0" stop-color="{stroke_start}"/><stop offset="1" stop-color="{stroke_end}"/></linearGradient>'
        if stroke_end
        else ""
    )
    fill = "url(#g)" if stroke_end else stroke_start
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><defs>{grad}</defs>'
        f'<rect width="100" height="100" fill="{background}"/><path d="{d}" fill="{fill}"/></svg>'
    )


def main() -> int:
    if not ICONSET.is_dir():
        sys.exit(f"{ICONSET} not found (restore the iOS tree first)")
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        sys.exit("playwright not installed: pip install playwright && playwright install chromium")
    icons = android_icons()
    d = icons.mark_path()
    light = tile(d, icons.TILE_LIGHT, icons.STROKE_START, icons.STROKE_END)
    dark = tile(d, icons.TILE_DARK, icons.STROKE_START, icons.STROKE_END)
    jobs = {
        ICONSET / "Icon-1024.png": light,
        ICONSET / "Icon-1024-Dark.png": dark,
        ALTERNATE / "AppIcon-Light.png": light,
        ALTERNATE / "AppIcon-Dark.png": dark,
        ALTERNATE / "AppIcon-LegacyLight.png": tile(d, icons.TILE_LIGHT, icons.STROKE_START),
        ALTERNATE / "AppIcon-LegacyDark.png": tile(d, icons.TILE_DARK, "#FFFFFF"),
    }
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": SIZE, "height": SIZE}, device_scale_factor=1)
        for target, svg in jobs.items():
            if not target.parent.is_dir():
                continue
            page.set_content(f'<body style="margin:0">{svg}</body>')
            page.locator("svg").evaluate(
                "(e, s) => { e.setAttribute('width', s); e.setAttribute('height', s); }", str(SIZE)
            )
            page.screenshot(path=str(target), clip={"x": 0, "y": 0, "width": SIZE, "height": SIZE})
            print(f"  wrote {target.relative_to(ROOT)}")
        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
