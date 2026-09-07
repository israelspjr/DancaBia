#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_USER="${SUDO_USER:-$USER}"

sudo apt update
sudo apt install -y python3 python3-venv python3-pip ffmpeg libsndfile1 raspi-config
sudo raspi-config nonint do_spi 0
sudo usermod -aG gpio,spi "$SERVICE_USER"
python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install --upgrade pip
"$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt"

if [[ ! -f /etc/default/music-game ]]; then
  sudo cp "$APP_DIR/config/music-game.env.example" /etc/default/music-game
fi

# Pasta de dados persistente para as músicas enviadas (fora do diretório do
# app, para não sumirem em atualizações). Lê MUSIC_DATA_DIR do arquivo de
# ambiente, com /var/lib/music-game como padrão.
DATA_DIR="$(. /etc/default/music-game 2>/dev/null; echo "${MUSIC_DATA_DIR:-/var/lib/music-game}")"
sudo mkdir -p "$DATA_DIR/songs"
sudo chown -R "$SERVICE_USER":"$SERVICE_USER" "$DATA_DIR"

sed -e "s|__APP_DIR__|$APP_DIR|g" -e "s|__USER__|$SERVICE_USER|g" \
  "$APP_DIR/systemd/music-game.service.template" | sudo tee /etc/systemd/system/music-game.service >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable music-game
sudo systemctl restart music-game

echo "Instalação concluída. Abra http://localhost:8000 ou http://$(hostname -I | awk '{print $1}'):8000"
echo "Hardware: sudo journalctl -u music-game -n 50 --no-pager"
