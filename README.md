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

## Teste sem instalar o serviço

Em um computador comum, o modo `auto` seleciona o simulador:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
HARDWARE_MODE=simulator .venv/bin/uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

As teclas `1 2 3 4 5 6 7 8 9 0` simulam as dez botoeiras.

## Administrativo de músicas

Acesse `http://IP_DO_RASPBERRY:8000/inserir_musica`. Informe título, artista e
MP3. No modo automático, a análise detecta ataques e distribui eventos pelas dez
botoeiras. Ela é deliberadamente voltada à jogabilidade: não precisa reproduzir
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
