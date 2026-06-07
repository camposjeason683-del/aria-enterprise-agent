FROM python:3.11-slim

# WeasyPrint system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpango-1.0-0 libpangocairo-1.0-0 libgdk-pixbuf-2.0-0 \
    libffi-dev shared-mime-info && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml .
RUN pip install --no-cache-dir .

COPY src/ src/

EXPOSE 8080
# Shell form so the platform's injected $PORT wins (Render/Fly), falling back to 8080
# (Cloud Run sets PORT=8080; local Docker uses 8080).
CMD uvicorn src.main:app --host 0.0.0.0 --port ${PORT:-8080}
