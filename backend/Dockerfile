FROM python:3.12-slim

WORKDIR /app

# WeasyPrint (PDF export, T-USE-07) requires native pango/cairo/gobject.
# Without these the renderer raises OSError at import time.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libcairo2 \
        libpango-1.0-0 \
        libpangoft2-1.0-0 \
        libharfbuzz0b \
        libffi8 \
        fonts-dejavu \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY . .

RUN chmod +x entrypoint.sh

EXPOSE 8000

# Runtime: gunicorn with uvicorn.workers.UvicornWorker (see entrypoint.sh)
ENTRYPOINT ["sh", "entrypoint.sh"]
