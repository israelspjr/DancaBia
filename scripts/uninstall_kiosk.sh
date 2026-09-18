#!/usr/bin/env bash
#
# Desativa o modo QUIOSQUE (totem) do jogo, revertendo o que o install_kiosk.sh
# configurou: remove o autologin no tty1 e o startx automático. NÃO desinstala
# pacotes nem toca no serviço music-game (o jogo continua rodando em :8000).
#
# Uso:
#   chmod +x scripts/uninstall_kiosk.sh
#   ./scripts/uninstall_kiosk.sh
#
set -euo pipefail

SERVICE_USER="${SUDO_USER:-$USER}"
USER_HOME="$(getent passwd "$SERVICE_USER" | cut -d: -f6)"

echo "==> Removendo autologin do tty1..."
sudo rm -f /etc/systemd/system/getty@tty1.service.d/autologin.conf
sudo rmdir /etc/systemd/system/getty@tty1.service.d 2>/dev/null || true

echo "==> Removendo o startx automático do .bash_profile..."
PROFILE="$USER_HOME/.bash_profile"
if [ -f "$PROFILE" ]; then
  # Remove o bloco delimitado pelos marcadores do kiosk.
  sed -i '/# >>> music-game kiosk >>>/,/# <<< music-game kiosk <<</d' "$PROFILE"
fi

echo "==> (Opcional) O .xinitrc foi mantido em $USER_HOME/.xinitrc"
echo "    Remova manualmente se quiser: rm $USER_HOME/.xinitrc"

sudo systemctl daemon-reload

echo ""
echo "==> Modo quiosque desativado. Reinicie para voltar ao terminal normal:"
echo "    sudo reboot"
echo ""
echo "    O jogo continua acessível em http://localhost:8000 (serviço music-game)."
