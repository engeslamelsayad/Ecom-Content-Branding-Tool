"""Getting creative assets into a form the vision model can actually read.

Three paths:
  - images  -> downscaled and re-encoded, because an oversized upload costs
               tokens without adding detail
  - video   -> sampled to stills with ffmpeg, densely across the first three
               seconds where ads are won or lost, then at wider intervals
  - pages   -> a full-page screenshot plus the extracted copy, so the review
               sees layout and wording together
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from PIL import Image

from .config import settings

log = logging.getLogger(__name__)

# Claude gains nothing from an edge longer than ~1568px, and pays for it.
MAX_EDGE = 1568
HOOK_WINDOW_S = 3.0


@dataclass
class PreparedImage:
    media_type: str
    data: str  # base64
    label: str = ""


def storage_path(*parts: str) -> Path:
    path = settings.storage_dir.joinpath(*parts)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def save_upload(brand_id: str, filename: str, payload: bytes) -> Path:
    suffix = Path(filename).suffix.lower()[:10]
    path = storage_path(brand_id, f"{uuid.uuid4().hex}{suffix}")
    path.write_bytes(payload)
    return path


def prepare_image(source: Path | bytes, label: str = "") -> PreparedImage:
    raw = source.read_bytes() if isinstance(source, Path) else source
    with Image.open(BytesIO(raw)) as img:
        img = img.convert("RGB")
        if max(img.size) > MAX_EDGE:
            ratio = MAX_EDGE / max(img.size)
            img = img.resize((int(img.width * ratio), int(img.height * ratio)), Image.LANCZOS)
        buffer = BytesIO()
        img.save(buffer, format="JPEG", quality=85, optimize=True)

    return PreparedImage(
        media_type="image/jpeg",
        data=base64.standard_b64encode(buffer.getvalue()).decode("ascii"),
        label=label,
    )


# ---------------------------------------------------------------------------
# Video
# ---------------------------------------------------------------------------
def _ffprobe_duration(video: Path) -> float:
    if not shutil.which("ffprobe"):
        return 0.0
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "json", str(video)],
            capture_output=True, text=True, timeout=60, check=True,
        )
        return float(json.loads(out.stdout)["format"]["duration"])
    except (subprocess.SubprocessError, KeyError, ValueError, json.JSONDecodeError) as exc:
        log.warning("ffprobe failed for %s: %s", video.name, exc)
        return 0.0


def sample_timestamps(duration: float, max_frames: int) -> list[float]:
    """Dense through the hook window, then spread across the rest."""
    if duration <= 0:
        return [0.0]

    hook = [t for t in (0.0, 0.5, 1.0, 1.5, 2.0, 3.0) if t < duration]
    remaining = max_frames - len(hook)
    if remaining <= 0 or duration <= HOOK_WINDOW_S:
        return hook[:max_frames] or [0.0]

    # Spread the rest evenly over what is left, ending just before the cut.
    step = (duration - HOOK_WINDOW_S) / (remaining + 1)
    tail = [round(HOOK_WINDOW_S + step * (i + 1), 2) for i in range(remaining)]
    return hook + [t for t in tail if t < duration]


def extract_frames(video: Path, max_frames: int | None = None) -> list[tuple[float, Path]]:
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg is not installed — video review is unavailable.")

    limit = max_frames or settings.video_max_frames
    duration = _ffprobe_duration(video)
    frames: list[tuple[float, Path]] = []
    out_dir = video.parent / f"{video.stem}_frames"
    out_dir.mkdir(parents=True, exist_ok=True)

    for timestamp in sample_timestamps(duration, limit):
        target = out_dir / f"t{timestamp:07.2f}.jpg".replace(".", "_", 1)
        result = subprocess.run(
            ["ffmpeg", "-nostdin", "-y", "-ss", str(timestamp), "-i", str(video),
             "-frames:v", "1", "-q:v", "3", str(target)],
            capture_output=True, timeout=120,
        )
        if result.returncode == 0 and target.is_file() and target.stat().st_size > 0:
            frames.append((timestamp, target))
        else:
            log.warning("frame extraction failed at %.2fs", timestamp)

    if not frames:
        raise RuntimeError("تعذّر استخراج أي فريم من الفيديو — تأكد إن الملف سليم.")
    return frames


def frames_to_images(frames: list[tuple[float, Path]]) -> list[PreparedImage]:
    return [
        prepare_image(path, label=f"[FRAME @ {ts:.1f}s]")
        for ts, path in frames
    ]


# ---------------------------------------------------------------------------
# Landing pages
# ---------------------------------------------------------------------------
@dataclass
class PageCapture:
    screenshot: Path
    text: str
    title: str
    final_url: str


async def capture_page(url: str, brand_id: str, viewport_width: int = 430) -> PageCapture:
    """Full-page screenshot plus readable copy, at phone width.

    Phone width is deliberate: it is where the traffic is and where landing
    pages break.
    """
    from bs4 import BeautifulSoup
    from playwright.async_api import async_playwright

    shot = storage_path(brand_id, f"lp_{uuid.uuid4().hex}.jpg")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
        try:
            page = await browser.new_page(
                viewport={"width": viewport_width, "height": 932},
                device_scale_factor=2,
                user_agent=(
                    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
                ),
            )
            await page.goto(url, wait_until="networkidle", timeout=60_000)
            # Let lazy sections render before the capture.
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(2)
            await page.evaluate("window.scrollTo(0, 0)")
            await asyncio.sleep(1)

            await page.screenshot(path=str(shot), full_page=True, type="jpeg", quality=80)
            html = await page.content()
            title = await page.title()
            final_url = page.url
        finally:
            await browser.close()

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()
    text = "\n".join(line.strip() for line in soup.get_text("\n").splitlines() if line.strip())

    return PageCapture(screenshot=shot, text=text[:40_000], title=title, final_url=final_url)


async def fetch_page_text(url: str) -> tuple[str, str]:
    """Readable page copy, without the screenshot cost.

    Used by the brand bootstrap, which reads a site's words rather than looking
    at it. Returns (title, text).
    """
    from bs4 import BeautifulSoup
    from playwright.async_api import async_playwright

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
        try:
            page = await browser.new_page()
            await page.goto(url, wait_until="networkidle", timeout=60_000)
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(1.5)
            html, title = await page.content(), await page.title()
        finally:
            await browser.close()

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg", "header", "footer", "nav"]):
        tag.decompose()
    text = "\n".join(line.strip() for line in soup.get_text("\n").splitlines() if line.strip())
    return title, text[:60_000]


def slice_tall_screenshot(path: Path, max_slices: int = 4) -> list[PreparedImage]:
    """A full-page shot is far too tall to read in one piece; cut it into panels."""
    with Image.open(path) as img:
        img = img.convert("RGB")
        width, height = img.size
        if height <= width * 2:
            return [prepare_image(path, label="[LANDING PAGE — full]")]

        slices = min(max_slices, max(2, round(height / (width * 2))))
        step = height // slices
        out: list[PreparedImage] = []
        for i in range(slices):
            top = i * step
            bottom = height if i == slices - 1 else (i + 1) * step
            panel = img.crop((0, top, width, bottom))
            buffer = BytesIO()
            if panel.height > MAX_EDGE:
                ratio = MAX_EDGE / panel.height
                panel = panel.resize((int(panel.width * ratio), MAX_EDGE), Image.LANCZOS)
            panel.save(buffer, format="JPEG", quality=82, optimize=True)
            out.append(PreparedImage(
                media_type="image/jpeg",
                data=base64.standard_b64encode(buffer.getvalue()).decode("ascii"),
                label=f"[LANDING PAGE — panel {i + 1} of {slices}, top to bottom]",
            ))
        return out
