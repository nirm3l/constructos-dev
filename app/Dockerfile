FROM node:22-alpine AS frontend-builder

WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json /frontend/
RUN npm ci
COPY frontend /frontend
RUN npm run build

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HOME=/home/app \
    PATH="/home/app/.local/bin:${PATH}"

ARG APP_UID=10001
ARG APP_GID=10001

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends nodejs npm dumb-init ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt
RUN npm install -g @openai/codex && npm cache clean --force

COPY . /app
COPY --from=frontend-builder /frontend/dist /app/static

RUN groupadd --gid "${APP_GID}" app \
    && useradd --uid "${APP_UID}" --gid app --create-home --home-dir /home/app app \
    && mkdir -p /data/uploads /home/app/.codex \
    && chown -R app:app /app /data/uploads /home/app

USER app

EXPOSE 8000
ENTRYPOINT ["dumb-init", "--"]
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
