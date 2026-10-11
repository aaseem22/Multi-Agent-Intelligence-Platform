# Single service: FastAPI serves the API and the built React app from one origin.

# --- 1. Build the frontend ---
FROM node:24-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# --- 2. Backend runtime ---
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.10.9 /uv /usr/local/bin/uv
ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/backend/.venv/bin:$PATH" \
    FRONTEND_DIST=/app/frontend/dist \
    DATABASE_URL=sqlite:////data/org.db \
    CHECKPOINT_DB_PATH=/data/checkpoints.db \
    EVALS_DIR=/data/evals

WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock backend/.python-version ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/ ./
RUN uv sync --frozen --no-dev
COPY --from=frontend /app/frontend/dist /app/frontend/dist

# /data is where the Railway volume is mounted (databases, checkpoints, eval runs).
RUN mkdir -p /data && chmod +x /app/backend/start.sh
EXPOSE 8000
CMD ["/app/backend/start.sh"]
