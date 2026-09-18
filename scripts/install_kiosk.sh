#!/usr/bin/env bash
#
# Configura o Raspberry Pi OS Lite como TOTEM/QUIOSQUE do jogo:
# ao ligar, o Pi faz login automático no terminal, sobe o ambiente gráfico
# mínimo e abre o Chromium em tela cheia apontando para o jogo local.
#
# Pensado para Pi OS Lite (sem desktop). Instala só o essencial: Xorg + Chromium
# + utilitários pequenos. Rode DEPOIS do install_raspberry.sh.
#
# Uso:
#   chmod +x scripts/install_kiosk.sh
#   ./scripts/install_kiosk.sh
#
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_USER="${SUDO_USER:-$USER}"
USER_HOME="$(getent passwd "$SERVICE_USER" | cut -d: -f6)"

# Porta em que o jogo responde (mesma do serviço music-game).
KIOSK_URL="http://localhost:8000"

echo "==> Instalando o mínimo gráfico + Chromium (Pi OS Lite)..."
sudo apt update
# xserver-xorg + xinit: servidor gráfico e o comando startx.
# chromium-browser: navegador do quiosque (no Pi OS o pacote é chromium-browser;
#   em alguns casos é 'chromium' — o autostart detecta qual existe).
# unclutter: esconde o cursor do mouse. x11-xserver-utils: xset (desliga o
#   apagamento de tela). fonts-noto-color-emoji: emojis, se o jogo usar.
# curl é usado pelo .xinitrc para esperar o backend subir antes de abrir o navegador.
sudo apt install -y \
  xserver-xorg xinit x11-xserver-utils unclutter curl \
  chromium-browser fonts-noto-color-emoji || \
sudo apt install -y \
  xserver-xorg xinit x11-xserver-utils unclutter curl \
  chromium fonts-noto-color-emoji

# --- 1) Autologin no console (tty1) para o usuário do serviço --------------
echo "==> Configurando autologin no terminal (tty1) para '$SERVICE_USER'..."
sudo mkdir -p /etc/systemd/system/getty@tty1.service.d
sudo tee /etc/systemd/system/getty@tty1.service.d/autologin.conf >/dev/null <<EOF
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin ${SERVICE_USER} --noclear %I \$TERM
EOF

# --- 2) Ao logar no tty1, iniciar o X automaticamente ----------------------
# Só inicia o gráfico no tty1 (para não atrapalhar acesso via SSH ou outros ttys).
PROFILE="$USER_HOME/.bash_profile"
MARK="# >>> music-game kiosk >>>"
if ! grep -q "$MARK" "$PROFILE" 2>/dev/null; then
  echo "==> Ativando startx automático no login do tty1..."
  cat <<'EOF' | sudo tee -a "$PROFILE" >/dev/null

# >>> music-game kiosk >>>
if [ -z "${DISPLAY:-}" ] && [ "$(tty)" = "/dev/tty1" ]; then
  exec startx -- -nocursor
fi
# <<< music-game kiosk <<<
EOF
fi

# --- 3) .xinitrc: espera o backend e abre o Chromium em kiosk --------------
echo "==> Escrevendo o .xinitrc (abre o jogo em tela cheia)..."
# Descobre qual binário do Chromium existe.
CHROMIUM_BIN="chromium-browser"
command -v chromium-browser >/dev/null 2>&1 || CHROMIUM_BIN="chromium"

sudo tee "$USER_HOME/.xinitrc" >/dev/null <<EOF
#!/bin/sh
# Ambiente gráfico mínimo do quiosque do jogo.

# Desliga apagamento de tela, DPMS e protetor (o totem fica sempre aceso).
xset s off
xset s noblank
xset -dpms

# Esconde o cursor do mouse quando parado.
unclutter -idle 0.5 -root &

# Espera o jogo responder em ${KIOSK_URL} antes de abrir o navegador,
# para não mostrar "tela branca" enquanto o serviço ainda está subindo.
echo "Aguardando o jogo em ${KIOSK_URL} ..."
until curl -sf ${KIOSK_URL}/api/health >/dev/null 2>&1; do
  sleep 1
done

# Limpa estado que faz o Chromium mostrar "restaurar páginas" após queda de energia.
PROFILE_DIR="\$HOME/.config/chromium"
mkdir -p "\$PROFILE_DIR/Default"
sed -i 's/"exit_type":"Crashed"/"exit_type":"Normal"/' "\$PROFILE_DIR/Default/Preferences" 2>/dev/null || true

# Loop: se o navegador fechar/travar, reabre sozinho.
while true; do
  ${CHROMIUM_BIN} \\
    --kiosk "${KIOSK_URL}" \\
    --incognito \\
    --noerrdialogs \\
    --disable-infobars \\
    --disable-session-crashed-bubble \\
    --disable-translate \\
    --no-first-run \\
    --check-for-update-interval=31536000 \\
    --overscroll-history-navigation=0 \\
    --autoplay-policy=no-user-gesture-required
  sleep 2
done
EOF
sudo chown "$SERVICE_USER":"$SERVICE_USER" "$USER_HOME/.xinitrc" "$PROFILE"

sudo systemctl daemon-reload

echo ""
echo "==> Quiosque configurado!"
echo "   Reinicie para testar:  sudo reboot"
echo ""
echo "   Ao ligar, o Pi entra sozinho e abre o jogo em tela cheia no HDMI."
echo ""
echo "   PARA MANUTENÇÃO (sair do quiosque):"
echo "     - Conecte um teclado e pressione  Ctrl+Alt+F2  para abrir outro terminal,"
echo "       faça login e trabalhe normalmente. Ctrl+Alt+F1 volta para o jogo."
echo "     - Ou acesse por SSH de outro computador."
echo "     - Para desativar o modo quiosque:  ./scripts/uninstall_kiosk.sh"
