FROM node:22-alpine AS frontend-builder

WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json /frontend/
RUN npm ci
COPY frontend /frontend
RUN npm run build

FROM node:22-bookworm-slim AS agent-cli-builder
RUN npm install -g --include=optional "@openai/codex@latest" "@anthropic-ai/claude-code@latest" \
    && npm cache clean --force

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HOME=/home/app \
    PATH="/home/app/.local/bin:${PATH}" \
    APP_ENCRYPTED_BUNDLE_ENABLED=false \
    APP_ENCRYPTED_BUNDLE_PATH=/opt/constructos/app.tar.gz.enc \
    APP_BUNDLE_KDF_ITERATIONS=200000 \
    APP_BUNDLE_TOKEN_SEGMENT_INDEX=2 \
    APP_BUNDLE_TOKEN_DELIMITER=. \
    APP_RUNTIME_APP_DIR=/app \
    APP_DECRYPTED_APP_DIR=/tmp/constructos-app

ARG APP_UID=10001
ARG APP_GID=10001
ARG APP_BUNDLE_ENCRYPT=false
ARG APP_BUNDLE_PASSWORD=""
ARG APP_BUNDLE_KDF_ITERATIONS=200000

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends dumb-init ca-certificates openssl bash git curl ripgrep docker-cli docker-compose \
    && rm -rf /var/lib/apt/lists/*

COPY --from=agent-cli-builder /usr/local/bin/node /usr/local/bin/node
COPY --from=agent-cli-builder /usr/local/lib/node_modules /usr/local/lib/node_modules
# Keep the same global bin layout npm creates so the agent CLIs can resolve platform packages.
RUN ln -sf ../lib/node_modules/@openai/codex/bin/codex.js /usr/local/bin/codex
RUN ln -sf ../lib/node_modules/@anthropic-ai/claude-code/cli.js /usr/local/bin/claude

COPY requirements.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt

COPY . /app
COPY --from=frontend-builder /frontend/dist /app/static
COPY scripts/runtime_entrypoint.sh /usr/local/bin/constructos-entrypoint.sh
COPY scripts/docker_wrapper.sh /usr/local/bin/docker
COPY scripts/docker_compose_wrapper.sh /usr/local/bin/docker-compose

RUN chmod 0755 /usr/local/bin/constructos-entrypoint.sh /usr/local/bin/docker \
    /usr/local/bin/docker-compose \
    && mv /usr/bin/docker /usr/bin/docker-real \
    && if [ -x /usr/bin/docker-compose ]; then mv /usr/bin/docker-compose /usr/bin/docker-compose-real; fi \
    && ln -sf /usr/local/bin/docker /usr/bin/docker \
    && ln -sf /usr/local/bin/docker-compose /usr/bin/docker-compose \
    && if [ "${APP_BUNDLE_ENCRYPT}" = "true" ]; then \
        if [ -z "${APP_BUNDLE_PASSWORD}" ]; then \
          echo "APP_BUNDLE_PASSWORD is required when APP_BUNDLE_ENCRYPT=true" >&2; \
          exit 1; \
        fi; \
        mkdir -p /opt/constructos; \
        tar -czf /tmp/constructos-app.tar.gz -C /app .; \
        openssl enc \
          -aes-256-cbc \
          -pbkdf2 \
          -iter "${APP_BUNDLE_KDF_ITERATIONS}" \
          -in /tmp/constructos-app.tar.gz \
          -out /opt/constructos/app.tar.gz.enc \
          -pass "pass:${APP_BUNDLE_PASSWORD}"; \
        rm -f /tmp/constructos-app.tar.gz; \
        find /app -mindepth 1 -delete; \
        touch /app/.encrypted_bundle_placeholder; \
      fi \
    && mkdir -p /opt/constructos \
    && groupadd --gid "${APP_GID}" app \
    && useradd --uid "${APP_UID}" --gid app --create-home --home-dir /home/app app \
    && mkdir -p /data/uploads /home/app/.codex /home/app/.claude /home/app/agent-home /home/app/workspace \
    && chown -R app:app /app /data/uploads /home/app /opt/constructos

USER app

EXPOSE 8000
ENTRYPOINT ["dumb-init", "--", "/usr/local/bin/constructos-entrypoint.sh"]
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
