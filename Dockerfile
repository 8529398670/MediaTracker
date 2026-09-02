# syntax=docker/dockerfile:1
#
# Media Tracker
# -------------
# Alpine + CPython, stdlib only (no pip, no wheels, no third-party code).
# Runs as an unprivileged user, on a read-only root filesystem, with only
# /data (a bind mount) and /tmp writable.
#
FROM python:3.12-alpine

LABEL org.opencontainers.image.title="Media Tracker" \
      org.opencontainers.image.description="Mobile-first media queue / tracker / importer" \
      org.opencontainers.image.licenses="MIT"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONHASHSEED=random \
    MT_HOST=0.0.0.0 \
    MT_PORT=8080 \
    MT_DATA_DIR=/data \
    MT_PUBLIC_DIR=/app/public \
    MT_SEED_DIR=/app/seed

# Patch the base image, then create the unprivileged runtime user.
# No shell, no home, no login: the account exists only to own the process.
RUN apk --no-cache upgrade \
 && addgroup -g 10001 -S tracker \
 && adduser  -u 10001 -S -G tracker -H -h /nonexistent -s /sbin/nologin tracker \
 && mkdir -p /data \
 && chown 10001:10001 /data

WORKDIR /app

# Application code is owned by root and read-only to the runtime user:
# the server can never rewrite its own code, even if something goes wrong.
COPY server/ /app/server/
COPY public/ /app/public/
# The Markdown lists ride along and are imported into the library on start.
COPY *.md /app/seed/
RUN chown -R root:root /app && chmod -R a-w,a+rX /app

USER 10001:10001

EXPOSE 8080
STOPSIGNAL SIGTERM

# curl/wget are not guaranteed in a slim base — use the interpreter we already have.
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD ["python3", "-c", "import os,sys,urllib.request;sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('MT_PORT','8080')+'/api/health',timeout=4).status==200 else 1)"]

ENTRYPOINT ["python3", "-u", "/app/server/app.py"]
