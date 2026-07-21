FROM python:3.12-slim@sha256:57cd7c3a7a273101a6485ba99423ee568157882804b1124b4dd04266317710de

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

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

RUN pip install --no-cache-dir uv==0.11.8

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY . .

RUN chmod +x entrypoint.sh

# Runtime processes do not need root. Ownership is explicit because Railway,
# the API, migrations, PDF rendering, and both arq workers share this image.
RUN useradd --create-home --uid 10001 specforge \
    && chown -R specforge:specforge /app
USER specforge

EXPOSE 8000

# Runtime: gunicorn with uvicorn.workers.UvicornWorker (see entrypoint.sh)
ENTRYPOINT ["sh", "entrypoint.sh"]
