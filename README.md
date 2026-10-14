# StackPanel

Panel web autoalojado para administrar proyectos en Docker desde un solo lugar. Se comunica directamente con `/var/run/docker.sock`, sin Portainer ni dependencias pesadas.

## Funciones

- **Proyectos**: crear, clonar desde Git, importar carpetas existentes e instalar apps de 1 clic (WordPress, Flask, Node, sitios estáticos). Acceso directo a `wp-admin` desde el panel.
- **Contenedores**: iniciar, detener, límites de CPU/RAM, logs y `git pull`.
- **Monitoreo**: CPU, memoria y disco del servidor y de cada proyecto, con historial de hasta 7 días.
- **Backups** manuales y programados por proyecto, con retención y restauración.
- **Bases de datos**: detección automática y visor (MySQL/MariaDB, Postgres), en solo lectura por defecto.
- **Proxy y SSL**: sitios Nginx y certificados de Let's Encrypt.
- **Archivos y SFTP** por proyecto, con usuarios aislados.
- **Notificaciones** por Discord, Slack o correo.
- **Seguridad**: 2FA, auditoría, bloqueo automático de IPs (panel, SSH, SFTP y web) y lista blanca.
- **Firewall** por puerto, incluidos los publicados por Docker; cada cambio se revierte solo si no se confirma.
- **SSH**: historial de accesos, sesiones abiertas, usuarios, claves, sudo, puertos y configuración de `sshd`.
- **Servidor**: estado de los servicios y reinicio del servidor.

Stack: Flask + Waitress, SQLite, API de Docker Engine y Nginx.

## Instalación

Requisitos: Linux con Docker y el plugin `docker compose` (v2).

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER && newgrp docker
```

Instalar el panel:

```bash
curl -fsSL https://raw.githubusercontent.com/GaboByker/StackPanel/main/install.sh | bash
```

El instalador descarga el código en `~/stackpanel`, genera el `.env`, inicia los contenedores, instala los agentes del host (pide `sudo`) y muestra la URL. La primera vez se crea el usuario administrador.

- Si el puerto del panel (5005) o del SFTP (2222) está ocupado, se usa el siguiente libre.
- El proxy necesita los puertos 80 y 443; si están ocupados, el panel se instala sin proxy.

Variables opcionales:

| Variable | Uso |
|---|---|
| `STACKPANEL_DIR` | Carpeta de instalación |
| `STACKPANEL_BRANCH` | Rama a instalar |
| `STACKPANEL_GUARD=0` | No instalar el firewall |
| `STACKPANEL_SSHADM=0` | No instalar la gestión de SSH |
| `SSHADM_PROTECTED_USERS` | Usuarios que el panel no puede borrar (por defecto, quien instala) |
| `STACKPANEL_MOTD=0` | No mostrar el logo al entrar por SSH |
| `STACKPANEL_KEEP_PROVIDER_MOTD=1` | No ocultar el mensaje del proveedor (`/etc/motd`) |

## Actualizar

Vuelve a ejecutar el comando de instalación: conserva el `.env` y los datos, y actualiza el panel y los agentes.

Comandos útiles desde la carpeta del panel:

```bash
docker compose logs -f portal          # logs
docker compose down                    # apagar
docker compose up -d --build portal    # reconstruir el panel
sudo ./guard/install-guard.sh          # actualizar los agentes del host
```

## Desinstalar

```bash
curl -fsSL https://raw.githubusercontent.com/GaboByker/StackPanel/main/uninstall.sh | bash
```

Quita los contenedores del panel, los agentes y el logo de SSH, y restaura el mensaje del proveedor. No toca los proyectos ni los usuarios del sistema. Los datos se conservan salvo que se use `--purge`; `--dry-run` muestra qué se haría.

La configuración de `sshd` hecha desde el panel se conserva para no perder el acceso. Para quitarla:

```bash
sudo rm /etc/ssh/sshd_config.d/05-stackpanel.conf && sudo sshd -t && sudo systemctl reload ssh
```

## HTTPS

Por defecto el panel funciona por HTTP y la cookie de sesión viaja sin cifrar. Cuando el panel tenga HTTPS (el proxy del panel puede emitir el certificado; sin dominio sirve `TU-IP.sslip.io`), define en `.env`:

```bash
PORTAL_COOKIE_SECURE=1
PORTAL_TRUSTED_PROXIES=    # IP o rango del proxy delante del panel, si lo hay
```

y aplica con `docker compose up -d --build portal`. Con `PORTAL_COOKIE_SECURE=1` y sin HTTPS no se puede iniciar sesión.

## Agentes del host

El panel corre en Docker sin permisos sobre el sistema. Dos servicios de systemd hacen los cambios:

**stackpanel-guard** aplica los bloqueos y las reglas de puertos con nftables (tabla `inet stackpanel`).

- Lista blanca de emergencia, solo editable por root: `/etc/stackpanel-guard/allow.conf`.
- Desactivar todos los bloqueos: `sudo touch /etc/stackpanel-guard/disabled`.
- Estado: `sudo stackpanel-guard status` · logs: `journalctl -u stackpanel-guard`.

**stackpanel-sshadm** administra usuarios, claves, sudo, puertos y configuración de `sshd`.

- Cada cambio pide otra vez la contraseña del panel (y 2FA).
- Siempre queda al menos un usuario con sudo que puede entrar.
- Los cambios de `sshd` se validan con `sshd -t` y se revierten solos si no se confirman en 5 minutos desde una conexión SSH nueva.
- Bloquear todos los cambios: `sudo touch /etc/stackpanel-sshadm/disabled` · logs: `journalctl -u stackpanel-sshadm`.

Si el instalador no pudo instalarlos, ejecuta desde la carpeta del panel:

```bash
sudo ./guard/install-guard.sh "$PWD/instance/portal.db" TU.IP.DE.CONFIANZA
```
