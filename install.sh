#!/usr/bin/env bash
# Instalador de StackPanel: descarga el código (sin necesitar git), crea la
# estructura de carpetas y levanta los contenedores con Docker Compose.
#
# Uso:
#   curl -fsSL https://raw.githubusercontent.com/GaboByker/StackPanel/main/install.sh | bash
#
# Variables opcionales:
#   STACKPANEL_DIR    directorio de instalación (default: ~/stackpanel)
#   STACKPANEL_BRANCH  rama a instalar (default: main)
set -euo pipefail

REPO="GaboByker/StackPanel"
BRANCH="${STACKPANEL_BRANCH:-main}"
INSTALL_DIR="${STACKPANEL_DIR:-$HOME/stackpanel}"

echo "==> Instalando StackPanel en ${INSTALL_DIR}"

command -v docker >/dev/null 2>&1 || {
    echo "Docker no está instalado. Instalalo primero: https://docs.docker.com/engine/install/" >&2
    exit 1
}
docker compose version >/dev/null 2>&1 || {
    echo "Necesitás el plugin 'docker compose' (v2). https://docs.docker.com/compose/install/" >&2
    exit 1
}

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
    PUBLIC_IP=$(curl -fsSL --max-time 3 ifconfig.me 2>/dev/null || echo "localhost")

    sed -i.bak "s#^PORTAL_SECRET_KEY=.*#PORTAL_SECRET_KEY=${SECRET}#" .env
    sed -i.bak "s#^PUBLIC_HOST=.*#PUBLIC_HOST=${PUBLIC_IP}#" .env
    sed -i.bak "s#^STACK_ROOT=.*#STACK_ROOT=${INSTALL_DIR}#" .env
    rm -f .env.bak
else
    echo "==> Ya existe un .env, lo dejo como está."
fi

echo "==> Levantando contenedores (esto puede tardar un par de minutos la primera vez)..."
docker compose up -d --build

PUBLIC_HOST=$(grep '^PUBLIC_HOST=' .env | cut -d= -f2-)
PORTAL_PORT=$(grep '^PORTAL_PORT=' .env | cut -d= -f2-)
PORTAL_PORT="${PORTAL_PORT:-5005}"

cat <<MSG

✅ StackPanel está corriendo en ${INSTALL_DIR}

Abrí en tu navegador:

    http://${PUBLIC_HOST}:${PORTAL_PORT}/setup

La primera vez te va a pedir crear el usuario administrador.

Comandos útiles (desde ${INSTALL_DIR}):
    docker compose logs -f portal   # ver logs
    docker compose down             # apagar
    docker compose up -d --build    # actualizar/reiniciar
MSG
