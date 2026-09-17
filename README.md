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
- **Accesos SFTP por proyecto**: usuarios aislados (chroot, uno no ve la carpeta del otro) con lectura/escritura configurable, sin tocar código ni `docker-compose.yml`
- **Notificaciones**: alertas a Discord/Slack/Email configurables por el propio admin
- **Seguridad**: autenticación de administradores con 2FA (TOTP), gestión de admins, auditoría, firewall
- **Grafos de código**: integración con Graphify para visualizar la estructura de cada proyecto desde el panel

## Stack

Flask + Waitress, SQLite, Docker Engine API (socket directo), Nginx.

## Instalación rápida

Necesitás Docker con el plugin `docker compose` (v2). Si no lo tenés:

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER && newgrp docker
```

(el `newgrp` es para que el grupo `docker` quede activo sin tener que cerrar sesión)

Después, instalá el panel:

```bash
curl -fsSL https://raw.githubusercontent.com/GaboByker/StackPanel/main/install.sh | bash
```

Descarga el código, crea las carpetas de datos (`html/`, `backups/`, `proxy/sites/`, `instance/`), genera un `.env` con una clave nueva y levanta los contenedores. Al final te tira la URL — la primera vez entra al asistente de configuración para crear el admin.

**Puertos:** el del panel (5005 por defecto) y el de SFTP (2222 por defecto, solo se usa si creás algún acceso) se pueden cambiar solos si están ocupados. El 80 y 443 los necesita el proxy/SSL y sí tienen que estar libres — si no, el instalador arranca igual pero sin proxy.

Para instalar en otra carpeta o rama:

```bash
STACKPANEL_DIR=/otra/ruta STACKPANEL_BRANCH=main curl -fsSL https://raw.githubusercontent.com/GaboByker/StackPanel/main/install.sh | bash
```

### Actualizar o apagar

```bash
cd ~/stackpanel   # o el directorio que hayas elegido
docker compose logs -f portal   # ver logs
docker compose down             # apagar
docker compose up -d --build    # actualizar/reiniciar
```
