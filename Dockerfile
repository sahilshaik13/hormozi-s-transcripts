# Hormozi Brain — full stack (UI + FastAPI + RAG). Built for Render / Railway / Fly.io.
# Vercel cannot fit this bundle (~350MB+ with vault + ChromaDB); use Render instead.

# ── Stage 1: Vite UI ─────────────────────────────────────────
FROM node:20-slim AS webbuild
WORKDIR /app/web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

# ── Stage 2: Python API + static dist ────────────────────────
FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.prod.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ backend/
COPY app.py app.py

COPY --from=webbuild /app/web/dist /app/web/dist

# Optional: bake vault + index into image (private deploy only).
# Uncomment after ensuring data exists locally:
# COPY hormozi-brain/ hormozi-brain/
# COPY hormozi-index/ hormozi-index/

ENV PORT=8000
EXPOSE 8000

CMD ["sh", "-c", "python -m uvicorn backend.server:app --host 0.0.0.0 --port ${PORT}"]
