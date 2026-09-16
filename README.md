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

- **Docker** con el plugin `docker compose` (v2). Si no lo tenés, el instalador te lo dice y corta — instalalo primero con el [script oficial de Docker](https://docs.docker.com/engine/install/) (funciona en la mayoría de las distros Linux):
  ```bash
  curl -fsSL https://get.docker.com | sh
  sudo usermod -aG docker "$USER"
  newgrp docker   # activa el grupo ya, sin tener que cerrar sesión
  ```
  El paso de `usermod`/`newgrp` **es necesario**: Linux solo revisa a qué grupos pertenecés al iniciar sesión, así que aunque el usuario ya quede en el grupo `docker`, la sesión/terminal actual no se entera hasta que la refrescás — con `newgrp docker` (inmediato, en la misma terminal) o cerrando sesión y volviendo a entrar. Sin este paso, `docker` va a fallar con "permission denied" salvo que uses `sudo docker ...`.

  > Docker aclara que este script de conveniencia es para desarrollo/pruebas, no lo recomienda para producción. Para un servidor de producción, usá el [repositorio apt oficial de tu distro](https://docs.docker.com/engine/install/debian/) en su lugar (más pasos, pero controlás la versión exacta).
- **Puertos 80 y 443 libres.** Los usa el proxy nginx/SSL del panel (certificados Let's Encrypt incluidos) — no son configurables. Si ya tenés algo corriendo ahí (otro nginx, Apache, Caddy, etc.), liberalos o el instalador va a saltear el proxy automáticamente y solo levantar el panel.
- El puerto del panel en sí (**5005** por defecto) **sí es flexible**: si está ocupado, el instalador elige automáticamente el próximo puerto libre.

```bash
curl -fsSL https://raw.githubusercontent.com/GaboByker/StackPanel/main/install.sh | bash
```

Esto descarga el código (sin necesitar `git`), crea las carpetas de datos (`html/`, `backups/`, `proxy/sites/`, `instance/`), genera un `.env` con una clave nueva, elige un puerto libre para el panel y levanta los contenedores. Al terminar te muestra la URL para abrir el panel — la primera vez te lleva directo al asistente de configuración (`/setup`) para crear el usuario administrador.

Por defecto instala en `~/stackpanel` desde la rama `main`. Si querés otra carpeta u otra rama, definí esas variables de entorno antes del `curl` (en la misma línea, así solo aplican a ese comando):

```bash
STACKPANEL_DIR=/otra/ruta STACKPANEL_BRANCH=main \
  curl -fsSL https://raw.githubusercontent.com/GaboByker/StackPanel/main/install.sh | bash
```

- `STACKPANEL_DIR` — dónde se instala (default: `~/stackpanel`)
- `STACKPANEL_BRANCH` — qué rama del repo descargar (default: `main`)

### Actualizar o apagar

```bash
cd ~/stackpanel   # o el directorio que hayas elegido
docker compose logs -f portal   # ver logs
docker compose down             # apagar
docker compose up -d --build    # actualizar/reiniciar
```
