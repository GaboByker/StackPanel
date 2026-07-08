FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY portal-server.py auth.py docker_control.py system_monitor.py projects.json ./
COPY templates/ templates/
COPY static/ static/

RUN mkdir -p instance

ENV PORTAL_PORT=5005
ENV DOCKER_SOCK=/var/run/docker.sock
EXPOSE 5005

CMD ["python", "portal-server.py"]
