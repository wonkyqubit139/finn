# Stage 1: build the frontend
FROM node:22-slim AS web
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build          # outputs to /app/backend/static

# Stage 2: Python API that also serves the built frontend
FROM python:3.12-slim
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend/ backend/
COPY data/ data/
COPY --from=web /app/backend/static backend/static
ENV PYTHONUNBUFFERED=1
WORKDIR /app/backend
EXPOSE 8000
CMD ["sh", "-c", "uvicorn finn.api:app --host 0.0.0.0 --port ${PORT:-8000}"]
