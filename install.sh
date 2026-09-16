#!/usr/bin/env bash
# Instalador de StackPanel: descarga el código (sin necesitar git), crea la
# estructura de carpetas y levanta los contenedores con Docker Compose.
#
# Uso:
#   curl -fsSL https://raw.githubusercontent.com/GaboByker/StackPanel/main/install.sh | bash
#
# Variables opcionales:
#   STACKPANEL_DIR     directorio de instalación (default: ~/stackpanel)
#   STACKPANEL_BRANCH  rama a instalar (default: main)
#   PORTAL_PORT         puerto del panel si no querés que se elija solo
set -euo pipefail

REPO="GaboByker/StackPanel"
BRANCH="${STACKPANEL_BRANCH:-main}"
INSTALL_DIR="${STACKPANEL_DIR:-$HOME/stackpanel}"

echo "==> Instalando StackPanel en ${INSTALL_DIR}"

port_in_use() {
    (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null && { exec 3>&-; return 0; } || return 1
}

if ! command -v docker >/dev/null 2>&1; then
    cat >&2 <<'MSG'
Docker no está instalado. Instalalo primero y volvé a correr este script.

  curl -fsSL https://get.docker.com | sh
  sudo usermod -aG docker "$USER"
  newgrp docker   # activa el grupo ya, sin cerrar sesión

El paso de usermod/newgrp es obligatorio: sin él, "docker" falla con
"permission denied" aunque ya hayas agregado el usuario al grupo, porque
Linux solo revisa la membresía de grupos al iniciar sesión.

Nota: ese script es para desarrollo/pruebas rápidas. Para producción, Docker
recomienda el repositorio apt oficial de tu distro en su lugar:
https://docs.docker.com/engine/install/
MSG
    exit 1
fi
if ! docker compose version >/dev/null 2>&1; then
    echo "Necesitás el plugin 'docker compose' (v2): https://docs.docker.com/compose/install/" >&2
    exit 1
fi

TMP_DIR=$(mktemp -d)
trap 'rm -rf "${TMP_DIR}"' EXIT

echo "==> Descargando código (${BRANCH})..."
curl -fsSL "https://github.com/${REPO}/archive/refs/heads/${BRANCH}.tar.gz" -o "${TMP_DIR}/stackpanel.tar.gz"
tar -xzf "${TMP_DIR}/stackpanel.tar.gz" -C "${TMP_DIR}"

mkdir -p "${INSTALL_DIR}"
cp -a "${TMP_DIR}/${REPO#*/}-${BRANCH}/." "${INSTALL_DIR}/"

cd "${INSTALL_DIR}"

echo "==> Creando carpetas de datos (html/, backups/, proxy/sites/, instance/)..."
mkdir -p html backups proxy/sites instance

if [ ! -f .env ]; then
    echo "==> Generando .env..."
    cp .env.example .env

    SECRET=$(openssl rand -hex 32 2>/dev/null || head -c32 /dev/urandom | od -An -tx1 | tr -d ' \n')

    # Preferimos IPv4: en hosts con IPv4 e IPv6, "curl ifconfig.me" sin forzar
    # protocolo suele devolver la IPv6, y esa URL rompe sin corchetes ([::1]).
    PUBLIC_IP=$(curl -fsSL --max-time 3 -4 ifconfig.me 2>/dev/null || true)
    if [ -z "${PUBLIC_IP}" ]; then
        PUBLIC_IP=$(curl -fsSL --max-time 3 -6 ifconfig.me 2>/dev/null || true)
    fi
    case "${PUBLIC_IP}" in
        "") PUBLIC_IP="localhost" ;;
        *:*) PUBLIC_IP="[${PUBLIC_IP}]" ;;  # IPv6: necesita corchetes en una URL
    esac

    sed -i.bak "s#^PORTAL_SECRET_KEY=.*#PORTAL_SECRET_KEY=${SECRET}#" .env
    sed -i.bak "s#^PUBLIC_HOST=.*#PUBLIC_HOST=${PUBLIC_IP}#" .env
    sed -i.bak "s#^STACK_ROOT=.*#STACK_ROOT=${INSTALL_DIR}#" .env
    rm -f .env.bak
else
    echo "==> Ya existe un .env, lo dejo como está."
fi

# Puerto del panel: si el que hay en .env (o el default 5005) está ocupado,
# busca el próximo libre y lo deja anotado. 80/443 (nginx del proxy) NO se
# reasignan solos: certificados SSL y muchos servicios esperan esos puertos
# fijos, así que si están ocupados avisamos y salteamos el proxy.
CONFIGURED_PORT=$(grep '^PORTAL_PORT=' .env | cut -d= -f2-)
PORT="${PORTAL_PORT:-${CONFIGURED_PORT:-5005}}"
if port_in_use "${PORT}"; then
    ORIGINAL_PORT="${PORT}"
    while port_in_use "${PORT}"; do
        PORT=$((PORT + 1))
    done
    echo "==> El puerto ${ORIGINAL_PORT} está ocupado, uso el ${PORT} en su lugar."
fi
sed -i.bak "s#^PORTAL_PORT=.*#PORTAL_PORT=${PORT}#" .env
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
    echo "==> Puerto(s)${BUSY_PORTS} ocupados: salteo el proxy/SSL (nginx + certbot)."
    echo "    El panel arranca igual. Cuando liberes esos puertos, corré:"
    echo "        docker compose up -d --build proxy proxy-certbot"
fi

echo "==> Levantando contenedores (esto puede tardar un par de minutos la primera vez)..."
if [ "${SKIP_PROXY}" = "1" ]; then
    docker compose up -d --build portal
else
    docker compose up -d --build
fi

PUBLIC_HOST=$(grep '^PUBLIC_HOST=' .env | cut -d= -f2-)

cat <<MSG

✅ StackPanel está corriendo en ${INSTALL_DIR}

Abrí en tu navegador:

    http://${PUBLIC_HOST}:${PORT}/setup

La primera vez te va a pedir crear el usuario administrador.

Comandos útiles (desde ${INSTALL_DIR}):
    docker compose logs -f portal   # ver logs
    docker compose down             # apagar
    docker compose up -d --build    # actualizar/reiniciar
MSG
