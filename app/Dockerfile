FROM python:3.12-slim@sha256:cb33f7f771ecec2ef1225cf39b159591a040391bd73e4c01f00fdfc4c47611d2
WORKDIR /app
COPY requirements.lock .
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir --only-binary=:all: --require-hashes -r requirements.lock && mkdir /data && chown 1000:1000 /data
ARG SOURCE_REVISION=unknown
LABEL org.opencontainers.image.revision=$SOURCE_REVISION
COPY app ./app
COPY web ./web
COPY openapi.json ./
USER 1000:1000
ENV PORT=8799 DATA_DIR=/data PYTHONDONTWRITEBYTECODE=1 BIND_HOST=0.0.0.0
EXPOSE 8799
CMD ["python", "app/server.py"]
