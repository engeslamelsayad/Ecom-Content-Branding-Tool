# ---------- Stage 1: build the dashboard ----------
FROM node:20-bookworm-slim AS web
WORKDIR /web
COPY frontend/package*.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---------- Stage 2: runtime ----------
# Pinned to bookworm (Debian 12) ON PURPOSE — do not move to a bare
# `python:3.12-slim`, which now resolves to trixie (Debian 13).
# Playwright 1.49 has no dependency list for trixie, silently falls back to its
# ubuntu20.04 list, and fails the build on `ttf-unifont` /
# `ttf-ubuntu-font-family`, which do not exist in Debian. Bookworm is a distro
# Playwright supports directly. Bump this only together with Playwright.
FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers

# ffmpeg  -> video frame extraction for the video-ad review
# pango/cairo -> WeasyPrint, for Arabic PDF export
# noto/amiri  -> Arabic glyphs in exported PDFs
RUN apt-get update && apt-get install -y --no-install-recommends \
      ffmpeg \
      libpango-1.0-0 libpangoft2-1.0-0 libcairo2 libgdk-pixbuf-2.0-0 \
      libffi8 shared-mime-info \
      fonts-noto-core fonts-hosny-amiri fonts-dejavu-core \
      curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

# Separate layer: browser download and its apt deps fail differently from pip,
# and this keeps the reason legible in the build log.
RUN playwright install --with-deps chromium \
    && rm -rf /var/lib/apt/lists/*

COPY backend/ ./backend/
# The skills are read at runtime — they are the tool's behaviour, not assets.
COPY conversion-copywriter/ ./conversion-copywriter/
COPY eyouth-branding-diploma/ ./eyouth-branding-diploma/
COPY marketing-plan/ ./marketing-plan/
COPY --from=web /web/dist ./frontend/dist

RUN mkdir -p /app/storage
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD curl -fsS http://127.0.0.1:${PORT:-8000}/api/health || exit 1

# One worker on purpose: a run's live stream buffer lives in process memory.
CMD ["sh", "-c", "cd /app/backend && exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1 --timeout-keep-alive 120"]
