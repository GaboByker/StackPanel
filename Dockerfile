FROM python:3.12-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY portal-server.py auth.py docker_control.py system_monitor.py panel_db.py proxy_control.py \
     docker_ops.py backup_control.py files_control.py app_templates.py project_scan.py \
     notification_control.py db_viewer.py db_autodetect.py scheduler.py projects.json ./
COPY templates/ templates/
COPY static/ static/

RUN mkdir -p instance

ENV PORTAL_PORT=5005
ENV DOCKER_SOCK=/var/run/docker.sock
EXPOSE 5005

CMD ["python", "portal-server.py"]
