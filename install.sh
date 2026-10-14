#!/usr/bin/env bash
# Instalador y actualizador de StackPanel.
#   curl -fsSL https://raw.githubusercontent.com/GaboByker/StackPanel/main/install.sh | bash
#
# Variables opcionales:
#   STACKPANEL_DIR                 carpeta de instalación (por defecto ~/stackpanel)
#   STACKPANEL_BRANCH              rama (por defecto main)
#   STACKPANEL_SRC                 carpeta local con el código, en lugar de descargarlo
#   PORTAL_PORT                    puerto del panel
#   STACKPANEL_GUARD=0             no instalar el firewall (stackpanel-guard)
#   STACKPANEL_SSHADM=0            no instalar la gestión de SSH (stackpanel-sshadm)
#   SSHADM_PROTECTED_USERS         usuarios que el panel no puede borrar (por defecto, quien instala)
#   STACKPANEL_MOTD=0              no mostrar el logo al entrar por SSH
#   STACKPANEL_KEEP_PROVIDER_MOTD=1  no ocultar el mensaje del proveedor (/etc/motd)
set -euo pipefail

REPO="GaboByker/StackPanel"
BRANCH="${STACKPANEL_BRANCH:-main}"
INSTALL_DIR="${STACKPANEL_DIR:-$HOME/stackpanel}"

if [ -t 1 ]; then printf '\033[1;34m'; fi
cat <<'BANNER'
                ▄▄██▄▄
            ▄▄██████████▄▄▄
       ▄▄▄███████████████████▄▄
   ▄▄████████████████████████████▄▄
  ██████████████████████████████████
  ██████████████████████████████████
  ▀▀██████████████████████████████▀▀
  ▄▄  ▀▀█████████▀▀▀▀█████████▀▀  ▄▄
  ████▄▄ ▀▀█████      █████▀▀ ▄▄████
  ███████▄▄ ████      ████ ▄▄███████
  ▀▀█████████████    █████████████▀▀
  ▄▄  ▀▀█████████    █████████▀▀  ▄▄
  ████▄▄  ▀▀████      ████▀▀  ▄▄████
  ████████▄▄████      ████▄▄████████
  ▀▀██████████████████████████████▀▀
      ▀████████████████████████▀
         ▀▀████████████████▀▀
             ▀██████████▀
                ▀▀██▀▀
BANNER
if [ -t 1 ]; then printf '\033[0m'; fi
echo

echo "==> Instalando StackPanel en ${INSTALL_DIR}"

port_in_use() {
    (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null && { exec 3>&-; return 0; } || return 1
}

if ! command -v docker >/dev/null 2>&1; then
    cat >&2 <<'MSG'
Docker no está instalado. Instálalo y vuelve a ejecutar este script:

  curl -fsSL https://get.docker.com | sh
  sudo usermod -aG docker "$USER"
  newgrp docker

Más opciones: https://docs.docker.com/engine/install/
MSG
    exit 1
fi
if ! docker compose version >/dev/null 2>&1; then
    echo "Falta el plugin 'docker compose' (v2): https://docs.docker.com/compose/install/" >&2
    exit 1
fi

TMP_DIR=$(mktemp -d)
trap 'rm -rf "${TMP_DIR}"' EXIT

mkdir -p "${INSTALL_DIR}"
if [ -n "${STACKPANEL_SRC:-}" ]; then
    echo "==> Copiando código desde ${STACKPANEL_SRC}..."
    tar -C "${STACKPANEL_SRC}" --exclude=./.git --exclude=./.venv --exclude=./instance \
        --exclude=./.env --exclude=./__pycache__ --exclude=./graphify-out -cf - . | tar -C "${INSTALL_DIR}" -xf -
else
    echo "==> Descargando código (${BRANCH})..."
    curl -fsSL "https://github.com/${REPO}/archive/refs/heads/${BRANCH}.tar.gz" -o "${TMP_DIR}/stackpanel.tar.gz"
    tar -xzf "${TMP_DIR}/stackpanel.tar.gz" -C "${TMP_DIR}"
    cp -a "${TMP_DIR}/${REPO#*/}-${BRANCH}/." "${INSTALL_DIR}/"
fi

cd "${INSTALL_DIR}"

echo "==> Creando carpetas de datos (html/, backups/, proxy/sites/, instance/)..."
mkdir -p html backups proxy/sites instance

# IP de la red local; detrás de un router la pública no funciona desde dentro.
is_docker_ip() {
    case "$1" in
        172.1[7-9].*|172.2[0-9].*|172.3[01].*) return 0 ;;
        *) return 1 ;;
    esac
}
detect_local_ip() {
    local ip dev
    if command -v ip >/dev/null 2>&1; then
        ip=$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="src") print $(i+1)}' | head -n1)
        dev=$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="dev") print $(i+1)}' | head -n1)
        case "${dev}" in docker*|br-*|veth*) ip="" ;; esac
        if [ -n "${ip}" ] && ! is_docker_ip "${ip}"; then
            echo "${ip}"; return
        fi
    fi
    for ip in $(hostname -I 2>/dev/null); do
        case "${ip}" in *:*|127.*) continue ;; esac
        is_docker_ip "${ip}" && continue
        echo "${ip}"; return
    done
}
LOCAL_IP=$(detect_local_ip || true)

if [ ! -f .env ]; then
    echo "==> Generando .env..."
    cp .env.example .env

    SECRET=$(openssl rand -hex 32 2>/dev/null || head -c32 /dev/urandom | od -An -tx1 | tr -d ' \n')

    # Primero IPv4: una IPv6 en la URL necesita corchetes.
    PUBLIC_IP=$(curl -fsSL --max-time 3 -4 ifconfig.me 2>/dev/null || true)
    if [ -z "${PUBLIC_IP}" ]; then
        PUBLIC_IP=$(curl -fsSL --max-time 3 -6 ifconfig.me 2>/dev/null || true)
    fi
    case "${PUBLIC_IP}" in
        "") PUBLIC_IP="${LOCAL_IP:-localhost}" ;;
        *:*) PUBLIC_IP="[${PUBLIC_IP}]" ;;
    esac

    sed -i.bak "s#^PORTAL_SECRET_KEY=.*#PORTAL_SECRET_KEY=${SECRET}#" .env
    sed -i.bak "s#^PUBLIC_HOST=.*#PUBLIC_HOST=${PUBLIC_IP}#" .env
    sed -i.bak "s#^STACK_ROOT=.*#STACK_ROOT=${INSTALL_DIR}#" .env
    rm -f .env.bak
else
    echo "==> Ya existe un .env; se conserva."
    # Con una clave conocida cualquiera podría falsificar la sesión de un admin.
    CURRENT_SECRET=$(grep '^PORTAL_SECRET_KEY=' .env | cut -d= -f2- || true)
    case "${CURRENT_SECRET}" in
        ""|"cambia-esta-clave"|"portal-docker-dev"|"portal-dev-change-me")
            echo "==> PORTAL_SECRET_KEY ausente o insegura: se genera una nueva."
            SECRET=$(openssl rand -hex 32 2>/dev/null || head -c32 /dev/urandom | od -An -tx1 | tr -d ' \n')
            if grep -q '^PORTAL_SECRET_KEY=' .env; then
                sed -i.bak "s#^PORTAL_SECRET_KEY=.*#PORTAL_SECRET_KEY=${SECRET}#" .env
                rm -f .env.bak
            else
                echo "PORTAL_SECRET_KEY=${SECRET}" >> .env
            fi
            ;;
    esac
fi

grep -q '^LOCAL_HOST=' .env || echo 'LOCAL_HOST=' >> .env
sed -i.bak "s#^LOCAL_HOST=.*#LOCAL_HOST=${LOCAL_IP}#" .env
rm -f .env.bak

# Si el puerto del panel o del SFTP está ocupado se usa el siguiente libre.
# 80/443 no se cambian: si están ocupados, se omite el proxy.
CONFIGURED_PORT=$(grep '^PORTAL_PORT=' .env | cut -d= -f2-)
PORT="${PORTAL_PORT:-${CONFIGURED_PORT:-5005}}"
if port_in_use "${PORT}"; then
    ORIGINAL_PORT="${PORT}"
    while port_in_use "${PORT}"; do
        PORT=$((PORT + 1))
    done
    echo "==> El puerto ${ORIGINAL_PORT} está ocupado; se usa el ${PORT}."
fi
sed -i.bak "s#^PORTAL_PORT=.*#PORTAL_PORT=${PORT}#" .env
rm -f .env.bak

grep -q '^SFTP_PORT=' .env || echo 'SFTP_PORT=2222' >> .env
CONFIGURED_SFTP_PORT=$(grep '^SFTP_PORT=' .env | cut -d= -f2-)
SFTP_PORT_FINAL="${SFTP_PORT:-${CONFIGURED_SFTP_PORT:-2222}}"
if port_in_use "${SFTP_PORT_FINAL}"; then
    ORIGINAL_SFTP_PORT="${SFTP_PORT_FINAL}"
    while port_in_use "${SFTP_PORT_FINAL}"; do
        SFTP_PORT_FINAL=$((SFTP_PORT_FINAL + 1))
    done
    echo "==> El puerto SFTP ${ORIGINAL_SFTP_PORT} está ocupado; se usa el ${SFTP_PORT_FINAL}."
fi
sed -i.bak "s#^SFTP_PORT=.*#SFTP_PORT=${SFTP_PORT_FINAL}#" .env
rm -f .env.bak

SKIP_PROXY=0
BUSY_PORTS=""
for p in 80 443; do
    if port_in_use "${p}"; then
        BUSY_PORTS="${BUSY_PORTS} ${p}"
        SKIP_PROXY=1
    fi
done
if [ "${SKIP_PROXY}" = "1" ]; then
    echo "==> Puerto(s)${BUSY_PORTS} ocupado(s): se omite el proxy/SSL (nginx + certbot)."
    echo "    El panel funciona igual. Cuando se liberen, ejecuta:"
    echo "        docker compose up -d --build proxy proxy-certbot"
fi

echo "==> Iniciando contenedores (la primera vez puede tardar unos minutos)..."
if [ "${SKIP_PROXY}" = "1" ]; then
    docker compose up -d --build portal
else
    docker compose up -d --build
fi

# Agentes del host (necesitan root). Se reinstalan en cada ejecución para actualizarlos.
# La IP de la sesión SSH actual entra en la lista blanca de emergencia.
GUARD_STATUS="no instalado"
if [ "${STACKPANEL_GUARD:-1}" != "0" ]; then
    ADMIN_IP="${SSH_CLIENT:-}"; ADMIN_IP="${ADMIN_IP%% *}"
    GUARD_ARGS=("${INSTALL_DIR}/instance/portal.db")
    [ -n "${ADMIN_IP}" ] && GUARD_ARGS+=("${ADMIN_IP}")
    if [ "$(id -u)" = "0" ]; then
        SUDO=""
    else
        SUDO="sudo"
        echo "==> Instalando los agentes del host: puede pedir la contraseña de sudo."
    fi
    PROTECTED_USER="${SSHADM_PROTECTED_USERS:-$(id -un)}"
    [ "${PROTECTED_USER}" = "root" ] && PROTECTED_USER="${SUDO_USER:-}"
    if ${SUDO} env SSHADM_PROTECTED_USERS="${PROTECTED_USER}" STACKPANEL_SSHADM="${STACKPANEL_SSHADM:-1}" \
        bash "${INSTALL_DIR}/guard/install-guard.sh" "${GUARD_ARGS[@]}" >/dev/null; then
        GUARD_STATUS="activo"
        [ -n "${ADMIN_IP}" ] && GUARD_STATUS="activo (la IP ${ADMIN_IP} está en la lista de emergencia)"
    else
        GUARD_STATUS="no se pudo instalar"
        echo "==> No se pudo instalar stackpanel-guard. El panel funciona, pero los bloqueos" >&2
        echo "    y las reglas de puertos no se aplicarán hasta ejecutar:" >&2
        echo "        cd ${INSTALL_DIR} && sudo ./guard/install-guard.sh ${GUARD_ARGS[*]}" >&2
    fi
fi

# Logo al entrar por SSH, justo antes del prompt.
if [ "${STACKPANEL_MOTD:-1}" != "0" ] && [ -d /etc/profile.d ]; then
    if [ "$(id -u)" = "0" ]; then MOTD_SUDO=""; else MOTD_SUDO="sudo"; fi
    if ! ${MOTD_SUDO} install -m 0644 "${INSTALL_DIR}/motd/stackpanel-logo.sh" /etc/profile.d/stackpanel-logo.sh; then
        echo "==> No se pudo instalar el logo de SSH (no afecta al panel)." >&2
    fi
    # Ubicación de versiones anteriores.
    if grep -qs 'StackPanel' /etc/update-motd.d/05-stackpanel; then
        ${MOTD_SUDO} rm -f /etc/update-motd.d/05-stackpanel || true
    fi
    # Oculta el mensaje del proveedor guardando una copia que restaura uninstall.sh.
    # Si /etc/motd es un enlace no se toca: truncate vaciaría el archivo destino.
    if [ "${STACKPANEL_KEEP_PROVIDER_MOTD:-0}" != "1" ] && [ -s /etc/motd ] \
        && [ ! -L /etc/motd ] && [ ! -e /etc/motd.stackpanel-backup ]; then
        if ${MOTD_SUDO} cp -a /etc/motd /etc/motd.stackpanel-backup; then
            ${MOTD_SUDO} truncate -s 0 /etc/motd || true
        fi
    fi
fi

# El contenedor puede reiniciarse en bucle aunque compose termine bien.
echo "==> Esperando a que el panel responda en el puerto ${PORT}..."
PANEL_OK=0
for _ in $(seq 1 60); do
    HTTP_CODE=$(curl -s -o /dev/null --max-time 2 -w '%{http_code}' "http://127.0.0.1:${PORT}/setup" 2>/dev/null || true)
    case "${HTTP_CODE}" in
        200|302) PANEL_OK=1; break ;;
    esac
    sleep 1
done
if [ "${PANEL_OK}" != "1" ]; then
    {
        echo
        echo "❌ El panel no respondió en http://127.0.0.1:${PORT}/setup después de 60 segundos."
        echo "   Estado del contenedor: $(docker inspect -f '{{.State.Status}}' stackpanel 2>/dev/null || echo 'desconocido')"
        echo "   Últimas líneas del log (docker logs --tail 30 stackpanel):"
        echo
        docker logs --tail 30 stackpanel 2>&1 | sed 's/^/    /'
        echo
        echo "   Revisa el error anterior y vuelve a ejecutar el instalador, o consulta los logs:"
        echo "       cd ${INSTALL_DIR} && docker compose logs -f portal"
    } >&2
    exit 1
fi

PUBLIC_HOST=$(grep '^PUBLIC_HOST=' .env | cut -d= -f2-)
PUBLIC_PLAIN="${PUBLIC_HOST#[}"; PUBLIC_PLAIN="${PUBLIC_PLAIN%]}"
[ "${PUBLIC_HOST}" = "localhost" ] && PUBLIC_HOST=""

is_private_ip() {
    case "$1" in
        10.*|192.168.*|172.1[6-9].*|172.2[0-9].*|172.3[01].*) return 0 ;;
        *) return 1 ;;
    esac
}

if [ -n "${LOCAL_IP}" ] && [ -n "${PUBLIC_HOST}" ] && [ "${LOCAL_IP}" != "${PUBLIC_PLAIN}" ]; then
    URLS="    Red local (desde esta red / esta PC):  http://${LOCAL_IP}:${PORT}/setup
    Pública (desde internet):              http://${PUBLIC_HOST}:${PORT}/setup

En un equipo local usa la URL de red local. La pública solo funciona si el puerto
${PORT} está redirigido en el router (y el proveedor no usa CGNAT)."
    if is_private_ip "${LOCAL_IP}"; then
        URLS="${URLS}

⚠️  Parece una instalación detrás de un router: la IP ${LOCAL_IP} es privada."
    fi
elif [ -n "${LOCAL_IP}" ] || [ -n "${PUBLIC_HOST}" ]; then
    URLS="    http://${PUBLIC_HOST:-${LOCAL_IP}}:${PORT}/setup"
else
    URLS="    http://localhost:${PORT}/setup"
fi

cat <<MSG

✅ StackPanel está corriendo en ${INSTALL_DIR}

Abre en el navegador:

${URLS}

La primera vez se pide crear el usuario administrador.

Firewall del servidor (stackpanel-guard): ${GUARD_STATUS}
    sudo stackpanel-guard status                  # estado del agente
    sudo touch /etc/stackpanel-guard/disabled     # emergencia: quita todos los bloqueos

Comandos útiles (desde ${INSTALL_DIR}):
    docker compose logs -f portal              # ver logs
    docker compose down                        # apagar
    docker compose up -d --build portal        # reconstruir el panel
    sudo ./guard/install-guard.sh              # actualizar los agentes del host
    ./uninstall.sh                             # desinstalar

Para actualizar a la última versión, vuelve a ejecutar el comando de instalación.
MSG
