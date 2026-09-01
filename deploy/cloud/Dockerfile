FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1

WORKDIR /app

RUN groupadd --gid 10001 cbi \
    && useradd --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin cbi \
    && mkdir -p /var/lib/cbi/sessions /var/lib/cbi/backups-v61 \
    && chown -R cbi:cbi /var/lib/cbi

COPY --chown=cbi:cbi . /app

USER cbi

ENV CBI_SESSION_ROOT=/var/lib/cbi/sessions \
    CBI_BACKUP_ROOT=/var/lib/cbi/backups-v61 \
    CBI_REMOTE_HOST=0.0.0.0 \
    CBI_REMOTE_PORT=8787 \
    CBI_REMOTE_AUTH_MODE=bearer

EXPOSE 8787
VOLUME ["/var/lib/cbi"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD ["python", "-c", "import json,urllib.request; r=urllib.request.urlopen('http://127.0.0.1:8787/healthz',timeout=3); d=json.load(r); raise SystemExit(0 if r.status==200 and d.get('status')=='ok' else 1)"]

CMD ["python", "-B", "-Xutf8", "mcp/server_v61_remote.py", "--host", "0.0.0.0", "--port", "8787"]
