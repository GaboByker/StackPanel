# Logo de StackPanel al entrar por SSH. Lo instala install.sh en
# /etc/profile.d/stackpanel-logo.sh y lo quita uninstall.sh.
#
# Va en profile.d (y no en /etc/update-motd.d) para salir al final, justo antes
# del prompt, después del mensaje de bienvenida del sistema. Solo en sesiones
# SSH con terminal (SSH_TTY): scp, sftp y "ssh host comando" no lo ven. Una vez
# por conexión y respetando ~/.hushlogin.
if [ -n "${SSH_TTY:-}" ] && [ -z "${STACKPANEL_LOGO_SHOWN:-}" ] && [ ! -e "${HOME:-/nonexistent}/.hushlogin" ]; then
export STACKPANEL_LOGO_SHOWN=1
printf '\033[1;34m'
cat <<'LOGO'

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

LOGO
printf '\033[0m'
fi
