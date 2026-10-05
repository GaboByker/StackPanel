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
ln -sf /usr/local/lib/stackpanel-guard/stackpanel_guard.py /usr/local/sbin/stackpanel-guard

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
systemctl daemon-reload
systemctl enable stackpanel-guard >/dev/null
systemctl restart stackpanel-guard
sleep 2
systemctl --no-pager --lines=5 status stackpanel-guard || true
