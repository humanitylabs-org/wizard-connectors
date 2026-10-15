FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && mkdir /data && chown 1000:1000 /data
COPY app ./app
COPY web ./web
COPY openapi.json ./
USER 1000:1000
ENV PORT=8799 DATA_DIR=/data PYTHONDONTWRITEBYTECODE=1
EXPOSE 8799
CMD ["python", "app/server.py"]
