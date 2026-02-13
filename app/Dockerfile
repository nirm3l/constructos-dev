FROM node:22-alpine AS frontend-builder

WORKDIR /frontend
COPY frontend/package.json /frontend/package.json
RUN npm install
COPY frontend /frontend
RUN npm run build

FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY . /app
COPY --from=frontend-builder /frontend/dist /app/static

ENV DB_PATH=/data/app.db
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
