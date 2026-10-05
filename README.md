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
- **Seguridad**: administradores con 2FA (TOTP, con código QR), gestión de admins y auditoría; bloqueo automático de IPs por intentos fallidos (login del panel, SSH, SFTP y escaneos web), lista blanca, bloqueos manuales, gráfico de ataques
- **Firewall**: decide quién entra a cada puerto (público, solo ciertas IPs o cerrado), incluidos los que publica Docker y que UFW no ve. Cada cambio queda a prueba 2 minutos y se revierte solo si no lo confirmás
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

### Firewall del servidor (stackpanel-guard)

El panel corre en Docker y no tiene permisos sobre la red. Los bloqueos y las reglas de puertos los aplica un agente pequeño en el host, `stackpanel-guard` (servicio de systemd, Python sin dependencias, nftables). El instalador lo instala solo, con `sudo`. Si no pudo, corré desde la carpeta del panel:

```bash
sudo ./guard/install-guard.sh "$PWD/instance/portal.db" TU.IP.DE.CONFIANZA
```

- Usa su propia tabla `inet stackpanel` y convive con UFW y fail2ban.
- `/etc/stackpanel-guard/allow.conf`: lista blanca de emergencia que el panel no puede tocar (una IP o rango por línea).
- Emergencia: `sudo touch /etc/stackpanel-guard/disabled` quita todos los bloqueos del servidor (y sigue así tras reiniciar) hasta borrar ese archivo.
- Estado y logs: `sudo stackpanel-guard status`, `sudo stackpanel-guard show`, `journalctl -u stackpanel-guard`.

### Actualizar o apagar

```bash
cd ~/stackpanel   # o el directorio que hayas elegido
docker compose logs -f portal   # ver logs
docker compose down             # apagar
docker compose up -d --build    # actualizar/reiniciar
```
