FROM node:24-alpine AS frontend-builder

WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend ./
RUN npm run build

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATABASE_URL=sqlite:///./data/runtime/medops.db \
    MODEL_CACHE_DIR=/app/data/models/fastembed

WORKDIR /app
COPY pyproject.toml README.md ./
COPY app ./app
COPY web ./web
COPY --from=frontend-builder /src/frontend/dist ./frontend/dist
COPY scripts ./scripts
COPY sample_data ./sample_data
RUN pip install --no-cache-dir . \
    && useradd --create-home --uid 10001 medops \
    && mkdir -p /app/data/runtime /app/data/models \
    && chown -R medops:medops /app

USER medops
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
