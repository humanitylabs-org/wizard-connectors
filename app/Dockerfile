FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir -r requirements.txt && mkdir /data && chown 1000:1000 /data
ARG SOURCE_REVISION=unknown
LABEL org.opencontainers.image.revision=$SOURCE_REVISION
COPY app ./app
COPY web ./web
COPY openapi.json ./
USER 1000:1000
ENV PORT=8799 DATA_DIR=/data PYTHONDONTWRITEBYTECODE=1 BIND_HOST=0.0.0.0
EXPOSE 8799
CMD ["python", "app/server.py"]
