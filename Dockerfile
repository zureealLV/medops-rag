FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATABASE_URL=sqlite:///./data/runtime/medops.db

WORKDIR /app
COPY pyproject.toml README.md ./
COPY app ./app
COPY scripts ./scripts
COPY sample_data ./sample_data
RUN pip install --no-cache-dir . \
    && useradd --create-home --uid 10001 medops \
    && mkdir -p /app/data/runtime \
    && chown -R medops:medops /app

USER medops
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
