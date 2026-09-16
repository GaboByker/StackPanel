# StackPanel

Un panel de administración autoalojado (self-hosted) para gestionar múltiples proyectos/contenedores Docker desde una sola interfaz web, sin depender de Portainer ni de dependencias pesadas — habla directo con `/var/run/docker.sock`.

## Funcionalidades

- **Gestión de proyectos**: alta/baja, clonado, detección/escaneo de proyectos existentes, instalación de apps "de 1 clic" (WordPress, Flask, Node, estáticos)
- **Control de contenedores**: start/stop/estado de servicios Docker, límites de recursos, logs, `git pull` por proyecto
- **Monitoreo**: métricas de CPU/memoria en tiempo real estilo *htop* por proyecto y del host
- **Backups**: respaldo/restauración automática y manual con retención, programados en background
- **Bases de datos**: visor/autodetección de BDs por proyecto (SQLite/MySQL/Postgres), toggle de escritura
- **Proxy reverso + SSL**: generación de sitios Nginx y emisión de certificados SSL hablando directo con el socket de Docker
- **Explorador de archivos** por proyecto
- **Notificaciones**: alertas a Discord/Slack/Email configurables por el propio admin
- **Seguridad**: autenticación de administradores con 2FA (TOTP), gestión de admins, auditoría, firewall
- **Grafos de código**: integración con Graphify para visualizar la estructura de cada proyecto desde el panel

## Stack

Flask + Waitress, SQLite, Docker Engine API (socket directo), Nginx.

## Instalación rápida

### Requisitos

- **Docker** con el plugin `docker compose` (v2). Si no lo tenés, el instalador te lo dice y corta — instalalo primero:
  ```bash
  sudo apt update && sudo apt install -y docker.io docker-compose-v2
  sudo usermod -aG docker "$USER"   # cerrá sesión y volvé a entrar después
  ```
  (en otras distros: `curl -fsSL https://get.docker.com | sh`)
- **Puertos 80 y 443 libres.** Los usa el proxy nginx/SSL del panel (certificados Let's Encrypt incluidos) — no son configurables. Si ya tenés algo corriendo ahí (otro nginx, Apache, Caddy, etc.), liberalos o el instalador va a saltear el proxy automáticamente y solo levantar el panel.
- El puerto del panel en sí (**5005** por defecto) **sí es flexible**: si está ocupado, el instalador elige automáticamente el próximo puerto libre.

```bash
curl -fsSL https://raw.githubusercontent.com/GaboByker/StackPanel/main/install.sh | bash
```

Esto descarga el código (sin necesitar `git`), crea las carpetas de datos (`html/`, `backups/`, `proxy/sites/`, `instance/`), genera un `.env` con una clave nueva, elige un puerto libre para el panel y levanta los contenedores. Al terminar te muestra la URL para abrir el panel — la primera vez te lleva directo al asistente de configuración (`/setup`) para crear el usuario administrador.

Variables opcionales antes de instalar:

```bash
STACKPANEL_DIR=/otra/ruta STACKPANEL_BRANCH=main \
  curl -fsSL https://raw.githubusercontent.com/GaboByker/StackPanel/main/install.sh | bash
```

### Actualizar o apagar

```bash
cd ~/stackpanel   # o el directorio que hayas elegido
docker compose logs -f portal   # ver logs
docker compose down             # apagar
docker compose up -d --build    # actualizar/reiniciar
```
