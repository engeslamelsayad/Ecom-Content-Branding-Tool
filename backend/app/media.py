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
import ipaddress
import json
import logging
import shutil
import socket
import subprocess
import uuid
from urllib.parse import urljoin, urlparse
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
    from .public_fetch import install_public_routes
    url = await asyncio.to_thread(assert_public_url, url)

    shot = storage_path(brand_id, f"lp_{uuid.uuid4().hex}.jpg")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
        try:
            page = await browser.new_page(
                viewport={"width": viewport_width, "height": 932},
                device_scale_factor=2,
                service_workers='block',
                user_agent=(
                    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
                ),
            )
            await install_public_routes(page)
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


# ---------------------------------------------------------------------------
# Outbound URL safety
# ---------------------------------------------------------------------------
# The server fetches URLs that users type. Without a guard that is an SSRF hole:
# a link to 169.254.169.254 or to a sibling service on the private network would
# be fetched with the server's own network access and the contents handed back.
class UnsafeURL(ValueError):
    pass


def assert_public_url(url: str) -> str:
    """Allow only http(s) URLs that resolve to public addresses."""
    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https"):
        raise UnsafeURL("الرابط لازم يبدأ بـ http:// أو https://")
    if not parsed.hostname:
        raise UnsafeURL("الرابط مش مكتمل")

    try:
        infos = socket.getaddrinfo(parsed.hostname, None)
    except socket.gaierror as exc:
        raise UnsafeURL(f"مش قادر أوصل للدومين ده: {parsed.hostname}") from exc

    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
            raise UnsafeURL("الرابط ده بيشاور على شبكة داخلية — مسموح بالمواقع العامة بس")

    return parsed.geturl()


# Paths worth reading on an e-commerce site, best first. A homepage alone rarely
# carries prices, the story, or a single real review.
_PAGE_HINTS = (
    ("product", 10), ("products", 10), ("shop", 9), ("collection", 8), ("collections", 8),
    ("store", 7), ("about", 7), ("our-story", 7), ("story", 6), ("review", 9),
    ("reviews", 9), ("testimonial", 9), ("faq", 5), ("منتج", 10), ("منتجات", 10),
    ("متجر", 8), ("من-نحن", 7), ("عن", 5), ("اراء", 9), ("تقييم", 9),
)


def _score_link(href: str) -> int:
    path = urlparse(href).path.lower()
    if not path or path == "/":
        return 0
    depth_penalty = path.count("/")
    return max((weight for token, weight in _PAGE_HINTS if token in path), default=0) - depth_penalty


async def crawl_site(url: str, max_pages: int = 5) -> tuple[str, str]:
    """Read a handful of a site's most informative pages.

    Returns (title, combined text). Same origin only, capped, and every page is
    labelled so the extractor knows what it is looking at.
    """
    from bs4 import BeautifulSoup
    from playwright.async_api import async_playwright
    from .public_fetch import install_public_routes

    start = assert_public_url(url)
    origin = urlparse(start).netloc

    def readable(html: str) -> str:
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "noscript", "svg"]):
            tag.decompose()
        return "\n".join(l.strip() for l in soup.get_text("\n").splitlines() if l.strip())

    chunks: list[str] = []
    site_title = ""

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
        try:
            page = await browser.new_page(service_workers='block')
            await install_public_routes(page)

            async def visit(target: str) -> str:
                await asyncio.to_thread(assert_public_url, target)
                await page.goto(target, wait_until="domcontentloaded", timeout=45_000)
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await asyncio.sleep(1.2)
                # A redirect could have landed somewhere private; re-check.
                assert_public_url(page.url)
                return await page.content()

            html = await visit(start)
            site_title = await page.title()
            chunks.append(f"### PAGE: {site_title or start} ({start})\n{readable(html)[:18000]}")

            soup = BeautifulSoup(html, "html.parser")
            candidates: dict[str, int] = {}
            for anchor in soup.find_all("a", href=True):
                link = urljoin(start, anchor["href"].split("#")[0])
                if urlparse(link).netloc != origin or link.rstrip("/") == start.rstrip("/"):
                    continue
                score = _score_link(link)
                if score > 0:
                    candidates[link] = max(candidates.get(link, 0), score)

            for link, _ in sorted(candidates.items(), key=lambda kv: -kv[1])[: max_pages - 1]:
                try:
                    inner = await visit(link)
                    title = await page.title()
                    chunks.append(f"### PAGE: {title or link} ({link})\n{readable(inner)[:12000]}")
                except Exception as exc:
                    log.warning("skipped %s: %s", link, exc)
        finally:
            await browser.close()

    return site_title, "\n\n".join(chunks)[:90_000]


async def fetch_page_text(url: str) -> tuple[str, str]:
    """Readable page copy, without the screenshot cost.

    Used by the brand bootstrap, which reads a site's words rather than looking
    at it. Returns (title, text).
    """
    from bs4 import BeautifulSoup
    from playwright.async_api import async_playwright
    from .public_fetch import install_public_routes

    url = assert_public_url(url)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
        try:
            page = await browser.new_page(service_workers='block')
            await install_public_routes(page)
            await page.goto(url, wait_until="networkidle", timeout=60_000)
            assert_public_url(page.url)
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
