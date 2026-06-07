# Hormozi Brain — full stack for Render (no persistent disk required).

# ── Stage 1: Vite UI ─────────────────────────────────────────
FROM node:20-slim AS webbuild
WORKDIR /app/web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

# ── Stage 2: Python API + static dist + data ─────────────────
FROM python:3.12-slim

WORKDIR /app

# Optional: public/signed URL to render-data.zip (see scripts/pack_render_data.bat)
ARG BUILD_DATA_URL=""

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential unzip curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.prod.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ backend/
COPY cofounder/ cofounder/
COPY app.py app.py
COPY scripts/render_install_data.sh /tmp/render_install_data.sh
RUN chmod +x /tmp/render_install_data.sh

# Full build context — data may be folders, render-data.zip, or fetched via BUILD_DATA_URL
COPY . /buildctx
RUN BUILD_DATA_URL="$BUILD_DATA_URL" sh /tmp/render_install_data.sh /buildctx /app

COPY --from=webbuild /app/web/dist /app/web/dist

ENV PORT=8000
EXPOSE 8000

CMD ["sh", "-c", "python -m uvicorn backend.server:app --host 0.0.0.0 --port ${PORT}"]
