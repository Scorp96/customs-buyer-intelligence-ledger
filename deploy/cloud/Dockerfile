FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1

WORKDIR /app

RUN groupadd --gid 10001 cbi \
    && useradd --uid 10001 --gid 10001 --create-home --shell /bin/bash cbi \
    && mkdir -p /var/lib/cbi/sessions /var/lib/cbi/backups-v61 /home/cbi/.ssh \
    && chmod 0700 /home/cbi/.ssh \
    && chown -R cbi:cbi /var/lib/cbi /home/cbi/.ssh

COPY --chown=cbi:cbi . /app

USER cbi

ENV CBI_SESSION_ROOT=/var/lib/cbi/sessions \
    CBI_BACKUP_ROOT=/var/lib/cbi/backups-v61 \
    CBI_REMOTE_HOST=0.0.0.0 \
    CBI_REMOTE_AUTH_MODE=bearer

EXPOSE 8787
VOLUME ["/var/lib/cbi"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD ["python", "-c", "import json,os,urllib.request; p=os.environ.get('CBI_REMOTE_PORT') or os.environ.get('PORT') or '8787'; r=urllib.request.urlopen('http://127.0.0.1:'+p+'/healthz',timeout=3); d=json.load(r); raise SystemExit(0 if r.status==200 and d.get('status') in {'ok','bootstrap_required'} else 1)"]

CMD ["python", "-B", "-Xutf8", "mcp/server_v61_remote.py"]
