FROM python:3.15-slim

WORKDIR /app

RUN pip install --no-cache-dir uv

ENV UV_COMPILE_BYTECODE=1 UV_NO_CACHE=1

COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev

ENV PATH="/app/.venv/bin:$PATH"

COPY . .
RUN python -m compileall -q src

RUN useradd --system --no-create-home app
USER app

EXPOSE 8000

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "172.0.0.0/8"]
