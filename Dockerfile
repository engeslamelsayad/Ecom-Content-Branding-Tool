# ---------- Stage 1: build the dashboard ----------
FROM node:20-slim AS web
WORKDIR /web
COPY frontend/package*.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---------- Stage 2: runtime ----------
FROM python:3.12-slim

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
RUN pip install --no-cache-dir -r backend/requirements.txt \
    && playwright install --with-deps chromium \
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
