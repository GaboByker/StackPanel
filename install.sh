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
#   STACKPANEL_GUARD    0 = no instalar el agente de firewall (stackpanel-guard)
#   STACKPANEL_SSHADM   0 = no instalar la gestión de usuarios/claves/sshd (stackpanel-sshadm)
#   SSHADM_PROTECTED_USERS  usuarios que el panel nunca puede borrar (por defecto, quien instala)
#   STACKPANEL_SRC      carpeta local con el código, en vez de descargarlo
#                       (para probar cambios antes de publicarlos)
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
    # Aun así, nos aseguramos de que tenga una PORTAL_SECRET_KEY fuerte: un
    # .env viejo (o copiado a mano del .env.example) podría traerla con el
    # placeholder, vacía o sin la línea, y entonces el panel firmaría las
    # sesiones con una clave conocida (cualquiera podría falsificar un admin).
    CURRENT_SECRET=$(grep '^PORTAL_SECRET_KEY=' .env | cut -d= -f2- || true)
    case "${CURRENT_SECRET}" in
        ""|"cambia-esta-clave"|"portal-docker-dev"|"portal-dev-change-me")
            echo "==> PORTAL_SECRET_KEY ausente o insegura: genero una nueva."
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

# Puerto del SFTP (accesos por proyecto): mismo criterio que el del panel.
# Si el .env es de una instalación anterior a esta funcionalidad, no tiene
# la línea SFTP_PORT todavía — se agrega antes de intentar reemplazarla.
grep -q '^SFTP_PORT=' .env || echo 'SFTP_PORT=2222' >> .env
CONFIGURED_SFTP_PORT=$(grep '^SFTP_PORT=' .env | cut -d= -f2-)
SFTP_PORT_FINAL="${SFTP_PORT:-${CONFIGURED_SFTP_PORT:-2222}}"
if port_in_use "${SFTP_PORT_FINAL}"; then
    ORIGINAL_SFTP_PORT="${SFTP_PORT_FINAL}"
    while port_in_use "${SFTP_PORT_FINAL}"; do
        SFTP_PORT_FINAL=$((SFTP_PORT_FINAL + 1))
    done
    echo "==> El puerto SFTP ${ORIGINAL_SFTP_PORT} está ocupado, uso el ${SFTP_PORT_FINAL} en su lugar."
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

# Agente de firewall (stackpanel-guard): lleva los bloqueos y las reglas de
# puertos del panel al kernel (nftables), vigila SSH/SFTP/nginx y cubre los
# puertos de Docker, que UFW no ve. Necesita root: se instala con sudo.
# La IP desde la que se instala (sesión SSH) entra a su lista blanca de
# emergencia, para no quedarse fuera del servidor.
GUARD_STATUS="no instalado"
if [ "${STACKPANEL_GUARD:-1}" != "0" ]; then
    ADMIN_IP="${SSH_CLIENT:-}"; ADMIN_IP="${ADMIN_IP%% *}"
    GUARD_ARGS=("${INSTALL_DIR}/instance/portal.db")
    [ -n "${ADMIN_IP}" ] && GUARD_ARGS+=("${ADMIN_IP}")
    if [ "$(id -u)" = "0" ]; then
        SUDO=""
    else
        SUDO="sudo"
        echo "==> Instalando el agente de firewall (stackpanel-guard): puede pedirte tu contraseña de sudo."
    fi
    # Quien instala queda como usuario protegido de stackpanel-sshadm (no se
    # puede borrar ni quitar de sudo desde el panel).
    PROTECTED_USER="${SSHADM_PROTECTED_USERS:-$(id -un)}"
    [ "${PROTECTED_USER}" = "root" ] && PROTECTED_USER="${SUDO_USER:-}"
    if ${SUDO} env SSHADM_PROTECTED_USERS="${PROTECTED_USER}" STACKPANEL_SSHADM="${STACKPANEL_SSHADM:-1}" \
        bash "${INSTALL_DIR}/guard/install-guard.sh" "${GUARD_ARGS[@]}" >/dev/null; then
        GUARD_STATUS="activo"
        [ -n "${ADMIN_IP}" ] && GUARD_STATUS="activo (tu IP ${ADMIN_IP} quedó en la lista de emergencia)"
    else
        GUARD_STATUS="no se pudo instalar"
        echo "==> No se pudo instalar stackpanel-guard. El panel funciona igual, pero los bloqueos" >&2
        echo "    y las reglas de puertos no se aplicarán en el servidor hasta que corras:" >&2
        echo "        cd ${INSTALL_DIR} && sudo ./guard/install-guard.sh ${GUARD_ARGS[*]}" >&2
    fi
fi

PUBLIC_HOST=$(grep '^PUBLIC_HOST=' .env | cut -d= -f2-)

cat <<MSG

✅ StackPanel está corriendo en ${INSTALL_DIR}

Abrí en tu navegador:

    http://${PUBLIC_HOST}:${PORT}/setup

La primera vez te va a pedir crear el usuario administrador.

Firewall del servidor (stackpanel-guard): ${GUARD_STATUS}
    sudo stackpanel-guard status                  # estado del agente
    sudo touch /etc/stackpanel-guard/disabled     # emergencia: quita todos los bloqueos

Comandos útiles (desde ${INSTALL_DIR}):
    docker compose logs -f portal   # ver logs
    docker compose down             # apagar
    docker compose up -d --build    # actualizar/reiniciar
MSG
