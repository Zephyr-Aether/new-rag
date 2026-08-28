# 多阶段构建：前端(node 构建产物) + 后端(python 运行时)

# --- Stage 1: 前端构建 ---
FROM node:20-alpine AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# --- Stage 2: 后端运行时 ---
FROM python:3.12-slim AS runtime
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1

COPY pyproject.toml ./
COPY app/ app/
COPY alembic/ alembic/
COPY alembic.ini ./
COPY --from=frontend /build/dist frontend/dist
RUN pip install .

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
