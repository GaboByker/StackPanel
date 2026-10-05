#!/usr/bin/env bash
# Instala o actualiza stackpanel-guard en el host (requiere root).
#   sudo ./guard/install-guard.sh [ruta/a/portal.db] [IP-o-rango-de-confianza ...]
# Las IPs extra se agregan a /etc/stackpanel-guard/allow.conf (lista blanca
# que el panel no puede modificar). Se respeta lo que ya exista.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DB_PATH="${1:-$(cd "$HERE/.." && pwd)/instance/portal.db}"
shift || true

if [[ $EUID -ne 0 ]]; then
	echo "Ejecutalo con sudo." >&2
	exit 1
fi
command -v nft >/dev/null || { apt-get update && apt-get install -y nftables; }
command -v python3 >/dev/null || { apt-get update && apt-get install -y python3; }

install -d -m 0755 /usr/local/lib/stackpanel-guard
install -m 0755 "$HERE/stackpanel_guard.py" /usr/local/lib/stackpanel-guard/stackpanel_guard.py
install -m 0644 "$HERE/detector.py" /usr/local/lib/stackpanel-guard/detector.py
install -m 0644 "$HERE/sessions.py" /usr/local/lib/stackpanel-guard/sessions.py
ln -sf /usr/local/lib/stackpanel-guard/stackpanel_guard.py /usr/local/sbin/stackpanel-guard
install -m 0755 "$HERE/stackpanel_sshadm.py" /usr/local/lib/stackpanel-guard/stackpanel_sshadm.py

install -d -m 0700 /etc/stackpanel-guard
if [[ ! -f /etc/stackpanel-guard/guard.conf ]]; then
	cat > /etc/stackpanel-guard/guard.conf <<CONF
# Base de datos del panel (solo lectura).
DB_PATH=$DB_PATH
# Cada cuántos segundos se revisan cambios (además del aviso inmediato del panel).
POLL_SECONDS=10
# Rango más amplio que se acepta bloquear.
MIN_PREFIX_V4=16
MIN_PREFIX_V6=48
CONF
fi
if [[ ! -f /etc/stackpanel-guard/allow.conf ]]; then
	cat > /etc/stackpanel-guard/allow.conf <<CONF
# Lista blanca de emergencia: estas IPs/rangos NUNCA se bloquean.
# Solo root puede editar este archivo; el panel no tiene acceso.
# Una IP o rango CIDR por línea. Tras editar: sudo stackpanel-guard sync
CONF
fi
for ip in "$@"; do
	grep -qxF "$ip" /etc/stackpanel-guard/allow.conf || echo "$ip" >> /etc/stackpanel-guard/allow.conf
done
chmod 0600 /etc/stackpanel-guard/guard.conf /etc/stackpanel-guard/allow.conf

install -m 0644 "$HERE/stackpanel-guard.service" /etc/systemd/system/stackpanel-guard.service
# El detector escribe en la base del panel: solo esa carpeta queda con escritura.
DB_DIR="$(dirname "$(grep -E '^DB_PATH=' /etc/stackpanel-guard/guard.conf | cut -d= -f2-)")"
install -d -m 0755 /etc/systemd/system/stackpanel-guard.service.d
printf '[Service]\nReadWritePaths=%s\n' "$DB_DIR" > /etc/systemd/system/stackpanel-guard.service.d/db-path.conf

# --- stackpanel-sshadm: usuarios, claves y sshd desde el panel ---
# Se omite con STACKPANEL_SSHADM=0 (el panel muestra entonces esa sección
# como no disponible). Usuarios protegidos (nunca se borran ni pierden sudo):
# por defecto quien ejecuta este instalador con sudo. Para indicar otros:
#   sudo SSHADM_PROTECTED_USERS="ana luis" ./guard/install-guard.sh
SSHADM_UNITS=""
if [[ "${STACKPANEL_SSHADM:-1}" != "0" ]]; then
SSHADM_UNITS="stackpanel-sshadm"
install -d -m 0700 /etc/stackpanel-sshadm
PROTECTED="${SSHADM_PROTECTED_USERS:-${SUDO_USER:-}}"
if [[ ! "$PROTECTED" =~ ^[a-z_][a-z0-9_\ -]*$ && -n "$PROTECTED" ]]; then
	echo "SSHADM_PROTECTED_USERS no válido: $PROTECTED" >&2
	exit 1
fi
if [[ ! -f /etc/stackpanel-sshadm/sshadm.conf ]]; then
	if [[ -z "$PROTECTED" ]]; then
		echo "Aviso: no se detectó el usuario administrador; define SSHADM_PROTECTED_USERS." >&2
	fi
	cat > /etc/stackpanel-sshadm/sshadm.conf <<CONF
# Usuarios que el panel nunca puede borrar ni quitar de sudo (separados por espacios).
PROTECTED_USERS=$PROTECTED
CONF
elif [[ -n "${SSHADM_PROTECTED_USERS:-}" ]]; then
	sed -i "s/^PROTECTED_USERS=.*/PROTECTED_USERS=$PROTECTED/" /etc/stackpanel-sshadm/sshadm.conf
fi
chmod 0600 /etc/stackpanel-sshadm/sshadm.conf
install -m 0644 "$HERE/stackpanel-sshadm.service" /etc/systemd/system/stackpanel-sshadm.service

else
	systemctl disable --now stackpanel-sshadm 2>/dev/null || true
fi

systemctl daemon-reload
systemctl enable stackpanel-guard $SSHADM_UNITS >/dev/null
systemctl restart stackpanel-guard $SSHADM_UNITS
sleep 2
systemctl --no-pager --lines=5 status stackpanel-guard $SSHADM_UNITS || true
