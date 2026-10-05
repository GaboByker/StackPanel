# StackPanel

Un panel de administración autoalojado (self-hosted) para gestionar múltiples proyectos/contenedores Docker desde una sola interfaz web, sin depender de Portainer ni de dependencias pesadas — habla directo con `/var/run/docker.sock`.

## Funcionalidades

- **Gestión de proyectos**: alta/baja, clonado, detección/escaneo de proyectos existentes, instalación de apps "de 1 clic" (WordPress, Flask, Node, estáticos). Los WordPress quedan instalados y se entra a `wp-admin` con un clic desde el panel (enlace firmado de un solo uso)
- **Control de contenedores**: start/stop/estado de servicios Docker, límites de recursos, logs, `git pull` por proyecto
- **Monitoreo**: métricas de CPU/memoria en tiempo real estilo *htop* por proyecto y del host, con gráficas históricas (1 h, 6 h, 24 h, 7 días) del servidor y de cada proyecto
- **Backups**: respaldo/restauración automática y manual con retención, programados en background
- **Bases de datos**: visor/autodetección de BDs por proyecto (SQLite/MySQL/Postgres), toggle de escritura
- **Proxy reverso + SSL**: generación de sitios Nginx y emisión de certificados SSL hablando directo con el socket de Docker
- **Explorador de archivos** por proyecto
- **Accesos SFTP por proyecto**: usuarios aislados (chroot, uno no ve la carpeta del otro) con lectura/escritura configurable, sin tocar código ni `docker-compose.yml`
- **Notificaciones**: alertas a Discord/Slack/Email configurables por el propio admin
- **Seguridad**: administradores con 2FA (TOTP, con código QR), gestión de admins y auditoría; bloqueo automático de IPs por intentos fallidos (login del panel, SSH, SFTP y escaneos web), lista blanca, bloqueos manuales, gráfico de ataques
- **Firewall**: decide quién entra a cada puerto (público, solo ciertas IPs o cerrado), incluidos los que publica Docker y que UFW no ve. Cada cambio queda a prueba 2 minutos y se revierte solo si no lo confirmás
- **Accesos SSH**: historial de quién entra por SSH/SFTP y aviso de IPs nuevas, sesiones abiertas que se pueden cerrar, usuarios del servidor (crear, borrar, sudo, contraseña, claves SSH) y endurecimiento de `sshd` con cambios a prueba que se revierten solos
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

### Accesos SSH, usuarios y claves (stackpanel-sshadm)

En **Accesos SSH** del panel se ve quién entra por SSH/SFTP (historial, IPs nuevas, sesiones abiertas que se pueden cerrar) y se administran las cuentas del servidor: crear y borrar usuarios, darles o quitarles `sudo`, sus claves SSH y su contraseña, y endurecer `sshd` (root, contraseñas, intentos, X11).

Lo hace un segundo agente del host, `stackpanel-sshadm`, que `install-guard.sh` instala junto con el firewall. Para no quedarte fuera del servidor:

- Cada cambio pide otra vez tu contraseña del panel (y el código 2FA si lo tienes).
- Ningún cambio puede dejar el servidor sin al menos un usuario con `sudo` que pueda entrar.
- Los usuarios protegidos no se pueden borrar ni quitar de `sudo`. Por defecto es quien instala; para elegir otros: `sudo SSHADM_PROTECTED_USERS="ana luis" ./guard/install-guard.sh` (queda en `/etc/stackpanel-sshadm/sshadm.conf`).
- Los cambios de `sshd` van en `/etc/ssh/sshd_config.d/05-stackpanel.conf`, se validan con `sshd -t` y se aplican a prueba: si en 5 minutos no se confirman (y solo se puede confirmar tras entrar por SSH en una conexión nueva), vuelven solos a lo anterior.
- Emergencia: `sudo touch /etc/stackpanel-sshadm/disabled` bloquea todos los cambios. Para quitar la configuración de sshd del panel: `sudo rm /etc/ssh/sshd_config.d/05-stackpanel.conf && sudo systemctl reload ssh`.
- Para no instalarlo: `STACKPANEL_SSHADM=0` al correr el instalador. Logs: `journalctl -u stackpanel-sshadm`.

### Actualizar o apagar

```bash
cd ~/stackpanel   # o el directorio que hayas elegido
docker compose logs -f portal   # ver logs
docker compose down             # apagar
docker compose up -d --build    # actualizar/reiniciar
```
