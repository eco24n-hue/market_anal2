# 건강보험 담보 레이더 웹앱
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends poppler-utils && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY webapp/requirements.txt webapp/requirements.txt
RUN pip install --no-cache-dir -r webapp/requirements.txt
COPY collectors collectors
COPY pipeline pipeline
COPY webapp webapp
COPY data data
ENV DB_PATH=/app/data/health_coverage_db.sqlite \
    DOCS_ROOT=/docs \
    STATE_DIR=/app/state \
    WORK_DIR=/app/work \
    PORT=8080
EXPOSE 8080
CMD ["sh", "-c", "uvicorn webapp.server:app --host 0.0.0.0 --port ${PORT}"]
