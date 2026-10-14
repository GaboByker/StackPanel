#!/usr/bin/env bash
# Desinstalador de StackPanel: quita lo que instaló install.sh.
#   curl -fsSL https://raw.githubusercontent.com/GaboByker/StackPanel/main/uninstall.sh | bash
#
# Opciones:
#   --yes       no pedir confirmación
#   --purge     borrar también la carpeta del panel, sus datos y los certificados SSL
#   --dry-run   mostrar qué se haría sin cambiar nada
# STACKPANEL_DIR: carpeta de instalación (por defecto ~/stackpanel).
#
# No toca los proyectos, los usuarios del sistema ni sus claves. La configuración de
# sshd hecha desde el panel se conserva, porque quitarla podría dejar el servidor sin acceso.
set -euo pipefail

INSTALL_DIR="${STACKPANEL_DIR:-$HOME/stackpanel}"
ASSUME_YES=0
PURGE=0
DRY_RUN=0
for arg in "$@"; do
    case "${arg}" in
        --yes|-y) ASSUME_YES=1 ;;
        --purge) PURGE=1 ;;
        --dry-run) DRY_RUN=1 ;;
        *) echo "Opción desconocida: ${arg}" >&2; exit 1 ;;
    esac
done

if [ "$(id -u)" = "0" ]; then SUDO=""; else SUDO="sudo"; fi

# Un paso que falla no detiene los demás; se avisa al final.
FAILED=0
run() {
    if [ "${DRY_RUN}" = "1" ]; then
        echo "    [dry-run] $*"
        return 0
    fi
    "$@" || { echo "    ⚠️  Falló: $*" >&2; FAILED=1; }
}

SSHD_DROPIN=/etc/ssh/sshd_config.d/05-stackpanel.conf
CONTAINERS="stackpanel stackpanel-proxy stackpanel-certbot stackpanel-sftp"

echo "==> Desinstalando StackPanel (${INSTALL_DIR})"
echo
echo "Se va a quitar:"
echo "  - Los contenedores del panel: ${CONTAINERS}"
echo "  - Los agentes del host stackpanel-guard y stackpanel-sshadm (y sus reglas de firewall)"
echo "  - El logo de StackPanel del mensaje de bienvenida de SSH (y vuelve el mensaje del proveedor)"
if [ "${PURGE}" = "1" ]; then
    echo "  - La carpeta ${INSTALL_DIR} con TODOS sus datos y los certificados SSL (--purge)"
elif [ -d "${INSTALL_DIR}" ]; then
    echo "Se conserva la carpeta ${INSTALL_DIR} con sus datos (usa --purge para borrarla)."
fi
echo "No se tocan los proyectos ni los usuarios del sistema."
echo

if [ "${ASSUME_YES}" != "1" ] && [ "${DRY_RUN}" != "1" ]; then
    # Con "curl | bash" la entrada estándar es el script: se lee de la terminal.
    if ! { exec 3</dev/tty; } 2>/dev/null; then
        echo "No hay terminal para confirmar. Vuelve a ejecutarlo con --yes." >&2
        exit 1
    fi
    printf '¿Continuar? [s/N] '
    read -r answer <&3 || answer=""
    exec 3<&-
    case "${answer}" in
        s|S|si|SI|sí|Sí|y|Y) ;;
        *) echo "Cancelado, no se cambió nada."; exit 0 ;;
    esac
fi

# --- Contenedores del panel (los proyectos siguen funcionando) -------------------
if command -v docker >/dev/null 2>&1; then
    echo "==> Quitando los contenedores del panel..."
    if [ -f "${INSTALL_DIR}/docker-compose.yml" ] && docker compose version >/dev/null 2>&1; then
        if [ "${PURGE}" = "1" ]; then
            run docker compose --project-directory "${INSTALL_DIR}" -f "${INSTALL_DIR}/docker-compose.yml" down --volumes
        else
            run docker compose --project-directory "${INSTALL_DIR}" -f "${INSTALL_DIR}/docker-compose.yml" down
        fi
    fi
    for name in ${CONTAINERS}; do
        if docker inspect "${name}" >/dev/null 2>&1; then
            run docker rm -f "${name}"
        fi
    done
    if [ "${PURGE}" = "1" ]; then
        for vol in stackpanel-sftp-host-keys stackpanel_proxy-certbot-etc stackpanel_proxy-certbot-www; do
            if docker volume inspect "${vol}" >/dev/null 2>&1; then
                run docker volume rm "${vol}"
            fi
        done
    fi
else
    echo "==> Docker no está instalado: no hay contenedores que quitar."
fi

# --- Agentes del host (necesitan root) ------------------------------------------
if command -v systemctl >/dev/null 2>&1; then
    if [ -n "${SUDO}" ] && [ "${DRY_RUN}" != "1" ]; then
        echo "==> Los pasos siguientes necesitan root: puede pedir la contraseña de sudo."
    fi

    echo "==> Quitando stackpanel-guard y stackpanel-sshadm..."
    for unit in stackpanel-guard stackpanel-sshadm; do
        if [ -f "/etc/systemd/system/${unit}.service" ]; then
            run ${SUDO} systemctl disable --now "${unit}"
        fi
    done
    # Solo la tabla propia; las reglas de Docker y del proveedor quedan igual.
    if command -v nft >/dev/null 2>&1 && ${SUDO} nft list table inet stackpanel >/dev/null 2>&1; then
        run ${SUDO} nft delete table inet stackpanel
    fi
    for path in \
        /etc/systemd/system/stackpanel-guard.service \
        /etc/systemd/system/stackpanel-guard.service.d \
        /etc/systemd/system/stackpanel-sshadm.service \
        /etc/systemd/system/ssh.service.d/stackpanel-rundir.conf \
        /usr/local/sbin/stackpanel-guard \
        /usr/local/lib/stackpanel-guard \
        /etc/stackpanel-guard \
        /etc/stackpanel-sshadm \
        /var/lib/stackpanel-guard \
        /var/lib/stackpanel-sshadm \
        /run/stackpanel-guard \
        /run/stackpanel-sshadm; do
        if [ -e "${path}" ] || [ -L "${path}" ]; then
            run ${SUDO} rm -rf "${path}"
        fi
    done
    run ${SUDO} systemctl daemon-reload
fi

# --- Logo del mensaje de bienvenida de SSH ---------------------------------------
# Solo si es de StackPanel (05-stackpanel es de versiones anteriores).
for logo in /etc/profile.d/stackpanel-logo.sh /etc/update-motd.d/05-stackpanel; do
    [ -f "${logo}" ] || continue
    if grep -q 'StackPanel' "${logo}" 2>/dev/null; then
        echo "==> Quitando el logo del mensaje de bienvenida de SSH (${logo})..."
        run ${SUDO} rm -f "${logo}"
    else
        echo "==> ${logo} no es de StackPanel; se conserva."
    fi
done
if [ -f /etc/motd.stackpanel-backup ]; then
    echo "==> Restaurando el mensaje de bienvenida del proveedor (/etc/motd)..."
    run ${SUDO} mv -f /etc/motd.stackpanel-backup /etc/motd
fi

# --- Carpeta del panel ---------------------------------------------------------
if [ "${PURGE}" = "1" ] && [ -d "${INSTALL_DIR}" ]; then
    # Evita borrar otra carpeta si STACKPANEL_DIR está mal.
    if [ -f "${INSTALL_DIR}/install.sh" ] && [ -f "${INSTALL_DIR}/portal-server.py" ]; then
        echo "==> Borrando ${INSTALL_DIR}..."
        # html/ puede tener archivos creados por contenedores como root.
        run ${SUDO} rm -rf "${INSTALL_DIR}"
    else
        echo "==> ${INSTALL_DIR} no parece una instalación de StackPanel; no se borra." >&2
        FAILED=1
    fi
fi

echo
if [ "${DRY_RUN}" = "1" ]; then
    echo "Fin del dry-run: no se cambió nada."
elif [ "${FAILED}" = "1" ]; then
    echo "⚠️  StackPanel se desinstaló, pero algún paso falló (revisa los avisos anteriores)."
else
    echo "✅ StackPanel se desinstaló."
fi
if [ "${PURGE}" != "1" ] && [ -d "${INSTALL_DIR}" ]; then
    echo "   Los datos siguen en ${INSTALL_DIR} (bórrala a mano o usa --purge)."
fi
if [ -f "${SSHD_DROPIN}" ]; then
    cat <<MSG

   La configuración de SSH hecha desde el panel sigue activa (${SSHD_DROPIN}).
   Para volver a la original, con otra sesión SSH abierta por si algo falla:
       sudo rm ${SSHD_DROPIN} && sudo sshd -t && sudo systemctl reload ssh
MSG
fi
[ "${FAILED}" = "1" ] && exit 1
exit 0
