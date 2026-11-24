"""LinkedIn images: 1080x1350 (4:5) at 2x, one per view."""
import pathlib
from playwright.sync_api import sync_playwright
here = pathlib.Path(__file__).parent
out = here.parent / "ContentDrafts"
with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True, args=["--enable-gpu", "--ignore-gpu-blocklist", "--use-angle=d3d11"])
    for i, v in enumerate(["lang", "geo"], 1):
        pg = b.new_context(viewport={"width": 1080, "height": 1350}, device_scale_factor=2).new_page()
        pg.goto(f"{(here / 'index.html').as_uri()}?shot={v}")
        pg.wait_for_function("document.body.dataset.ready==='1'", timeout=120000)
        pg.wait_for_timeout(4000)
        pg.screenshot(path=str(out / f"25-IS-THIS-A-MAP-TaxonomyOfBorders-{i}-{v}.png"))
    b.close()
