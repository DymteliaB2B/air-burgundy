FROM python:3.12-slim

WORKDIR /app
COPY server.py ./
COPY web ./web
COPY data/airports.json ./data/airports.json

# la base SQLite vit dans un volume persistant monté sur /data
ENV AIRBURGUNDY_DATA=/data \
    HOST=0.0.0.0 \
    PORT=8080 \
    PYTHONUNBUFFERED=1
VOLUME ["/data"]
EXPOSE 8080

CMD ["python", "server.py"]
