FROM node:22-alpine AS frontend-builder

WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json /frontend/
RUN npm ci
COPY frontend /frontend
RUN npm run build

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt

COPY . /app
COPY --from=frontend-builder /frontend/dist /app/static

RUN useradd --uid 10002 --create-home --home-dir /home/license license \
    && mkdir -p /data /backups \
    && chown -R license:license /app /data /backups /home/license

USER license

EXPOSE 8092
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8092"]
