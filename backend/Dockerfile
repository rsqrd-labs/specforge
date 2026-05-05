FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY . .

RUN chmod +x entrypoint.sh

EXPOSE 8000

# Runtime: gunicorn with uvicorn.workers.UvicornWorker (see entrypoint.sh)
ENTRYPOINT ["sh", "entrypoint.sh"]
