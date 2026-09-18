# Jogo Musical — Raspberry Pi 5

Jogo offline inspirado em Guitar Hero para um painel de parede com 10 botoeiras
arcade e 10 anéis WS2812B de 12 pixels. A música dispara um anel; o participante
precisa apertar a botoeira correspondente dentro da janela de acerto. O backend
calcula acertos, erros, combo e pontuação.

O frontend React já está compilado em `frontend/dist`. O Raspberry não precisa
executar Node.js: o serviço permanente é Python/FastAPI.

## Mapa elétrico usado pelo aplicativo

### Anéis WS2812B

- GPIO10/MOSI, pino físico 19 → entrada 1A (pino 1) do SN7407.
- Saída 1Y (pino 2) do SN7407 → resistor de 330–500 ohms → DI laranja do anel 1.
- DO do anel 1 → DI do anel 2, repetindo até o anel 10.
- Amarelo de cada anel → 5 V da fonte externa, em paralelo.
- Verde de cada anel → GND da fonte externa, em paralelo.
- GND da fonte externa, GND do Raspberry e pino 7 do SN7407 unidos.
- Pino 14 do SN7407 → 5 V; resistor pull-up de 1 kohm entre pinos 2 e 14.

Os anéis ocupam os pixels nesta ordem:

| Anel/botoeira | Pixels na cadeia |
| --- | --- |
| 1 | 0–11 |
| 2 | 12–23 |
| 3 | 24–35 |
| 4 | 36–47 |
| 5 | 48–59 |
| 6 | 60–71 |
| 7 | 72–83 |
| 8 | 84–95 |
| 9 | 96–107 |
| 10 | 108–119 |

### Botoeiras

Um terminal de cada botoeira vai ao GPIO indicado e o outro vai ao GND comum.
O programa usa pull-up interno: solta = nível alto; pressionada = GND.

| Botoeira | GPIO BCM | Pino físico |
| --- | ---: | ---: |
| 1 | 17 | 11 |
| 2 | 27 | 13 |
| 3 | 22 | 15 |
| 4 | 5 | 29 |
| 5 | 6 | 31 |
| 6 | 26 | 37 |
| 7 | 16 | 36 |
| 8 | 25 | 22 |
| 9 | 18 | 12 |
| 10 | 12 | 32 |

Correção importante da planilha recebida: os pinos físicos 24 e 26 são GPIO8
(CE0) e GPIO7 (CE1), reservados pelo SPI0. Além disso, GPIO16 já estava atribuído
à botoeira 7. Por isso a botoeira 9 deve usar GPIO18/pino 12, e a botoeira 10 foi
definida no GPIO12/pino 32. Se a fiação for modificada, altere somente
`BUTTON_GPIOS_BCM` em `/etc/default/music-game`.

## Comportamento dos anéis

- Azul: botoeira aguardando o toque.
- Verde: acerto.
- Vermelho: botão errado ou nota perdida.
- Apagado: sem evento ativo.

O brilho padrão está limitado a 25% em `/etc/default/music-game`. Isso reduz o
consumo e o ofuscamento, mas não elimina a necessidade da fonte externa de 5 V,
GND comum, distribuição em paralelo e proteção adequada.

## Instalação e serviço automático

O primeiro provisionamento precisa de internet para `apt` e `pip`. Depois, o
jogo funciona offline. Copie o projeto para o Raspberry e execute:

```bash
cd raspi-music-game
chmod +x scripts/install_raspberry.sh
./scripts/install_raspberry.sh
```

O instalador habilita o SPI, instala as bibliotecas do Pi 5, cria o ambiente
Python e registra `music-game.service`. O serviço inicia no boot e reinicia
automaticamente após falhas. Após falta de energia, basta o Raspberry voltar a
ligar.

Abra `http://localhost:8000`. Em outro computador da rede, use
`http://IP_DO_RASPBERRY:8000`.

```bash
sudo systemctl status music-game
sudo journalctl -u music-game -f
curl http://localhost:8000/api/health
```

O endpoint de saúde deve mostrar `"mode":"raspberry"`, 120 LEDs e a lista de
GPIOs. Se mostrar `simulator` no Raspberry, confira o log do serviço.

Após alterar a fiação em `/etc/default/music-game`:

```bash
sudo nano /etc/default/music-game
sudo systemctl restart music-game
```

## Erro ao instalar o lgpio (`cannot find -llgpio`)

No Raspberry Pi OS **trixie** (Python 3.13) não existe wheel pronto do `lgpio`,
e instalá-lo pelo pip tenta compilar e falha com `cannot find -llgpio`. Por isso
o `lgpio` **não** está no `requirements.txt`: o instalador usa o pacote do
sistema (`python3-lgpio`) via apt e cria o ambiente com `--system-site-packages`.

Se você já tomou esse erro, refaça o ambiente:

```bash
cd /home/user/raspi-music-game
sudo apt update
sudo apt install -y python3-lgpio liblgpio-dev
rm -rf .venv
python3 -m venv --system-site-packages .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
```

## Teste sem instalar o serviço

Em um computador comum, o modo `auto` seleciona o simulador:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
HARDWARE_MODE=simulator .venv/bin/uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

As teclas `1 2 3 4 5 6 7 8 9 0` simulam as dez botoeiras.

## Modo totem/quiosque (abrir o jogo sozinho no HDMI ao ligar)

Para o Raspberry funcionar como um totem — liga na tomada e o jogo aparece em
tela cheia no monitor/TV via HDMI, sem precisar de outro computador para acessar
`:8000` — use o instalador de quiosque. Ele funciona no **Raspberry Pi OS Lite**
(só terminal): instala o mínimo gráfico (Xorg + Chromium), configura login
automático e abre o navegador em tela cheia no jogo local.

```bash
cd raspi-music-game
chmod +x scripts/install_kiosk.sh
./scripts/install_kiosk.sh
sudo reboot
```

Depois do reboot, ao ligar o Pi:

1. faz login automático no terminal;
2. sobe o ambiente gráfico mínimo;
3. **espera** o jogo responder em `http://localhost:8000` (evita "tela branca");
4. abre o Chromium em tela cheia já no jogo.

Se o navegador travar/fechar, ele reabre sozinho. O apagamento de tela e o
protetor ficam desligados (o totem fica sempre aceso), o cursor some quando
parado, e o aviso de "restaurar páginas" após queda de energia é suprimido.

**Ligar/desligar da tomada:** funciona — o serviço e o quiosque sobem sozinhos.
Ainda assim, desligar direto na tomada por muito tempo pode desgastar o cartão
SD; se possível, prefira desligar pelo sistema.

### Sair do quiosque para manutenção

- Conecte um teclado e pressione **Ctrl+Alt+F2** para abrir outro terminal (faça
  login e trabalhe); **Ctrl+Alt+F1** volta para o jogo.
- Ou acesse por **SSH** de outro computador da rede.
- Para desativar o modo quiosque de vez (volta ao terminal normal no boot):

```bash
./scripts/uninstall_kiosk.sh
sudo reboot
```

O jogo continua rodando em `http://localhost:8000` mesmo com o quiosque
desativado (o serviço `music-game` é independente).

## Onde as músicas ficam salvas (não somem em atualizações)

As músicas de demonstração (`songs/`) vêm junto do código. As músicas que você
**envia pelo sistema** são gravadas em uma pasta separada, fora do diretório do
aplicativo, definida por `MUSIC_DATA_DIR` (padrão `/var/lib/music-game`). Assim,
atualizar o código (novo zip por cima, `git pull`, rodar o instalador de novo)
**não apaga** as músicas cadastradas.

> Se antes suas músicas sumiam depois de atualizar, era porque ficavam dentro de
> `songs/` e a atualização sobrescrevia a pasta. Agora elas ficam em
> `MUSIC_DATA_DIR`. Não apague essa pasta ao atualizar.

Backup simples das músicas enviadas:

```bash
tar czf musicas-backup.tgz -C /var/lib/music-game songs
```

## Teste de sistema (verificar os LEDs)

Além do teste automático que roda no boot, há um botão **"TESTE DE SISTEMA"** na
tela principal do jogo. Ele acende as 10 ilhas em sequência para você conferir
se todos os anéis estão funcionando, sem precisar iniciar uma música. Também
disponível pela API: `POST /api/system-test` (recusa se houver rodada em
andamento).

## Administrativo de músicas

Acesse `http://IP_DO_RASPBERRY:8000/inserir_musica`. Informe título, artista e
escolha a origem do áudio:

- **Upload MP3 — mapa automático:** envie um arquivo MP3; o Python analisa.
- **Link do YouTube — mapa automático:** cole a URL do vídeo. O sistema baixa o
  áudio com `yt-dlp`, converte para MP3 (via ffmpeg) e gera o mapa. **Requer
  internet no momento do cadastro.** Uso educacional interno (Senac SP), sem
  fins comerciais. Se um download parar de funcionar após o YouTube mudar algo,
  atualize a ferramenta: `.venv/bin/pip install -U yt-dlp`.
- **Upload MP3 — colar mapa JSON:** envie o MP3 e cole manualmente o mapa.

Não é necessário converter para MIDI: a análise detecta os ataques do áudio e
escolhe a nota predominante para cada evento. No modo automático, a análise
distribui eventos pelas dez botoeiras. Ela é deliberadamente voltada à jogabilidade: não precisa reproduzir
todas as notas nem separar perfeitamente cada timbre. Depois é possível ajustar
tempos e botoeiras na tabela.

O mapa usa `button` de 0 a 9, correspondendo fisicamente às botoeiras 1 a 10.
Durante a rodada, os eventos do mesmo mapa comandam simultaneamente a tela e os
anéis físicos; as botoeiras físicas entram no mesmo cálculo de pontuação usado
pelo teclado e pelo toque na tela.

## Músicas de demonstração

- **Escala de demonstração** (`songs/demo`): percorre as dez notas uma vez e
  encerra. Serve para uma verificação rápida.
- **Teste contínuo (loop lento)** (`songs/demo-loop`): percorre as dez ilhas em
  sequência e **repete indefinidamente** até você parar a rodada. Ideal para
  testar as botoeiras e os anéis sem precisar reiniciar. O ritmo é de cerca de
  3 segundos entre notas, com janela de acerto folgada (1,5 s).

Qualquer chart pode virar loop adicionando `"loop": true` no `chart.json`.
Opcionalmente, `"loop_span_ms"` define a duração de uma passada completa antes de
recomeçar; sem ele, o sistema usa o fim do último evento mais um respiro de 1 s.

## Mapeamento nota → ilha → LEDs

Cada uma das dez notas/botoeiras comanda exatamente uma ilha de 12 LEDs, na
mesma ordem da cadeia física (ver `HardwareController.ring_led_range`):

| Nota (botão) | Ilha | Endereços dos LEDs |
| --- | :---: | --- |
| DÓ (0) | 1 | 0–11 |
| DÓ♯ (1) | 2 | 12–23 |
| RÉ (2) | 3 | 24–35 |
| RÉ♯ (3) | 4 | 36–47 |
| MI (4) | 5 | 48–59 |
| FÁ (5) | 6 | 60–71 |
| FÁ♯ (6) | 7 | 72–83 |
| SOL (7) | 8 | 84–95 |
| LÁ (8) | 9 | 96–107 |
| SI (9) | 10 | 108–119 |

v1.1
unzip painel_guitar_hero_rpi5_hardware_servico.zip
cd painel_guitar_hero_rpi5_hardware_servico
chmod +x scripts/install_raspberry.sh
./scripts/install_raspberry.sh

Verificação:
sudo systemctl status music-game
curl http://localhost:8000/api/health
sudo journalctl -u music-game -f
