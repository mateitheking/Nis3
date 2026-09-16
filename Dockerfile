# syntax=docker/dockerfile:1

# ---- фронт: React/Vite собирается отдельно, в финальный образ идёт только
# готовый dist — не node_modules и не исходники ------------------------------
FROM node:20-slim AS frontend
WORKDIR /web
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci
COPY apps/web ./
RUN npm run build

# ---- бэк: FastAPI + собранный фронт как статика -----------------------------
FROM python:3.12-slim AS backend
WORKDIR /app
ENV PYTHONPATH=/app PYTHONUNBUFFERED=1

COPY pyproject.toml ./
# Список ниже дублирует [project.dependencies] из pyproject.toml — держать в
# синхроне при добавлении новых зависимостей. `pip install -e .` тут не
# используем: apps/ — implicit namespace-пакет без __init__.py (см.
# PYTHONPATH выше, он и делает apps.api.main импортируемым), а полноценная
# сборка wheel ради одного сервиса — лишняя сложность.
RUN pip install --no-cache-dir \
    "httpx>=0.28" "pydantic>=2.10" "bcrypt>=4.1" "python-multipart>=0.0.9" \
    "openai>=1.50" "python-dotenv>=1.0" "fastapi>=0.115" "uvicorn[standard]>=0.30" \
    "sqlalchemy>=2.0" "cryptography>=42" "edupage_api>=0.12.5" "curl_cffi>=0.16"

COPY apps/api ./apps/api
COPY --from=frontend /web/dist ./apps/api/static

# nis.db (SQLite) и .env/секреты сюда НЕ копируются — БД живёт на
# смонтированном томе (см. DATABASE_URL в README), секреты приходят
# переменными окружения хоста, не файлом в образе.
EXPOSE 8000
# Railway (и большинство PaaS) сами назначают порт через $PORT и ждут, что
# контейнер слушает именно его — 8000 остаётся дефолтом только для локального
# `docker run` без этой переменной. Shell-форма CMD (не JSON-массив) нужна
# специально для подстановки $PORT — в exec-форме её никто не раскрывает.
CMD uvicorn apps.api.main:app --host 0.0.0.0 --port ${PORT:-8000}
