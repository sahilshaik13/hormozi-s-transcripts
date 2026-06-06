# Hormozi Brain API — deploy on Railway, Render, Fly.io, etc.
# Vercel hosts the React UI only; this image runs the Python RAG backend.

FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ backend/
COPY tools/ tools/

# Mount vault + index at runtime, or COPY if baking into image (large):
# COPY hormozi-brain/ hormozi-brain/
# COPY hormozi-index/ hormozi-index/

ENV PORT=8000
EXPOSE 8000

CMD ["sh", "-c", "python -m uvicorn backend.server:app --host 0.0.0.0 --port ${PORT}"]
