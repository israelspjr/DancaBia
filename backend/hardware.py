"""Raspberry Pi 5 hardware integration for buttons and WS2812B rings.

The ten 12-pixel rings form one 120-pixel chain on SPI0 MOSI (BCM GPIO 10).
Buttons use BCM numbering, pull-up inputs and a shared GND.
"""
from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable


LOGGER = logging.getLogger(__name__)
PressHandler = Callable[[int], Awaitable[None]]

COLORS: dict[str, tuple[int, int, int]] = {
    "off": (0, 0, 0),
    "blue": (0, 80, 255),
    "green": (0, 255, 40),
    "red": (255, 0, 0),
}

# Sequência de cores usada na animação de boot (teste dos anéis).
BOOT_COLORS: list[tuple[str, tuple[int, int, int]]] = [
    ("VERMELHO", (255, 0, 0)),
    ("VERDE", (0, 255, 40)),
    ("AZUL", (0, 80, 255)),
    ("BRANCO", (255, 255, 255)),
]


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError as error:
        raise RuntimeError(f"{name} precisa ser um número inteiro.") from error


def _button_gpios() -> list[int]:
    value = os.getenv("BUTTON_GPIOS_BCM", "17,27,22,5,6,26,16,25,18,12")
    try:
        pins = [int(item.strip()) for item in value.split(",") if item.strip()]
    except ValueError as error:
        raise RuntimeError("BUTTON_GPIOS_BCM contém um GPIO inválido.") from error
    if len(pins) != 10 or len(set(pins)) != 10:
        raise RuntimeError("BUTTON_GPIOS_BCM deve conter 10 GPIOs BCM diferentes.")
    spi0_pins = {7, 8, 9, 10, 11}
    conflicts = sorted(spi0_pins.intersection(pins))
    if conflicts:
        raise RuntimeError(
            f"GPIOs {conflicts} são reservados para o barramento SPI0 dos LEDs."
        )
    return pins


@dataclass
class HardwareController:
    requested_mode: str = field(default_factory=lambda: os.getenv("HARDWARE_MODE", "auto").lower())
    ring_count: int = field(default_factory=lambda: _env_int("RING_COUNT", 10))
    leds_per_ring: int = field(default_factory=lambda: _env_int("LEDS_PER_RING", 12))
    spi_device: str = field(default_factory=lambda: os.getenv("SPI_DEVICE", "/dev/spidev0.0"))
    spi_speed_khz: int = field(default_factory=lambda: _env_int("SPI_SPEED_KHZ", 800))
    brightness: float = field(default_factory=lambda: float(os.getenv("LED_BRIGHTNESS", "0.25")))
    button_gpios: list[int] = field(default_factory=_button_gpios)
    debounce_seconds: float = field(default_factory=lambda: float(os.getenv("BUTTON_DEBOUNCE", "0.04")))
    mode: str = "simulator"
    lights: list[str] = field(default_factory=lambda: ["off"] * 10)
    _neo: object | None = field(default=None, init=False, repr=False)
    _buttons: list[object] = field(default_factory=list, init=False, repr=False)
    _loop: asyncio.AbstractEventLoop | None = field(default=None, init=False, repr=False)
    _on_press: PressHandler | None = field(default=None, init=False, repr=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)
    _flash_tasks: set[asyncio.Task] = field(default_factory=set, init=False, repr=False)

    @property
    def total_leds(self) -> int:
        return self.ring_count * self.leds_per_ring

    def ring_led_range(self, button: int) -> range:
        """Faixa de endereços (0-119) da ilha correspondente à nota/botão.

        A cadeia física é um único fio de 120 LEDs dividido em 10 ilhas de 12.
        O índice ``button`` (0-9) é a nota musical / botoeira; cada nota comanda
        exatamente uma ilha, na mesma ordem da fiação:

            botão 0 (DO)  -> ilha 1  -> LEDs 0..11
            botão 1 (DO#) -> ilha 2  -> LEDs 12..23
            botão 2 (RE)  -> ilha 3  -> LEDs 24..35
            botão 3 (RE#) -> ilha 4  -> LEDs 36..47
            botão 4 (MI)  -> ilha 5  -> LEDs 48..59
            botão 5 (FA)  -> ilha 6  -> LEDs 60..71
            botão 6 (FA#) -> ilha 7  -> LEDs 72..83
            botão 7 (SOL) -> ilha 8  -> LEDs 84..95
            botão 8 (LA)  -> ilha 9  -> LEDs 96..107
            botão 9 (SI)  -> ilha 10 -> LEDs 108..119
        """
        first_pixel = button * self.leds_per_ring
        return range(first_pixel, first_pixel + self.leds_per_ring)

    def status(self) -> dict:
        return {
            "mode": self.mode,
            "ring_count": self.ring_count,
            "leds_per_ring": self.leds_per_ring,
            "total_leds": self.total_leds,
            "button_gpios_bcm": self.button_gpios,
            "spi_device": self.spi_device,
        }

    async def start(self, on_press: PressHandler) -> None:
        if self.requested_mode not in {"auto", "raspberry", "simulator"}:
            raise RuntimeError("HARDWARE_MODE deve ser auto, raspberry ou simulator.")
        if self.ring_count != 10:
            raise RuntimeError("Esta versão do jogo exige RING_COUNT=10.")
        if self.leds_per_ring <= 0:
            raise RuntimeError("LEDS_PER_RING precisa ser maior que zero.")
        if not 0 < self.brightness <= 1:
            raise RuntimeError("LED_BRIGHTNESS deve estar entre 0 e 1.")

        self._loop = asyncio.get_running_loop()
        self._on_press = on_press
        if self.requested_mode == "simulator" or (
            self.requested_mode == "auto" and not self._is_raspberry_pi()
        ):
            self.mode = "simulator"
            LOGGER.info("Hardware em modo simulador.")
            return

        try:
            from gpiozero import Button
            from pi5neo import Pi5Neo

            self._neo = Pi5Neo(
                self.spi_device,
                num_leds=self.total_leds,
                spi_speed_khz=self.spi_speed_khz,
                quiet_mode=True,
            )
            self._buttons = [
                Button(
                    gpio,
                    pull_up=True,
                    bounce_time=self.debounce_seconds,
                )
                for gpio in self.button_gpios
            ]
            for index, button in enumerate(self._buttons):
                button.when_pressed = lambda index=index: self._dispatch_press(index)
            self.mode = "raspberry"
            await self.all_off()
            LOGGER.info(
                "Hardware ativo: %s LEDs em %s anéis; botoeiras BCM %s.",
                self.total_leds,
                self.ring_count,
                self.button_gpios,
            )
        except Exception:
            await self.close()
            raise

    def _dispatch_press(self, button: int) -> None:
        if not self._loop or not self._on_press:
            return
        self._loop.call_soon_threadsafe(self._schedule_press, button)

    def _schedule_press(self, button: int) -> None:
        if self._on_press:
            asyncio.create_task(self._on_press(button))

    async def set_light(self, button: int, color: str) -> None:
        if not 0 <= button < self.ring_count:
            return
        if color not in COLORS:
            raise ValueError(f"Cor de jogo desconhecida: {color}")
        self.lights[button] = color
        if not self._neo:
            return

        rgb = tuple(round(channel * self.brightness) for channel in COLORS[color])
        async with self._lock:
            for pixel in self.ring_led_range(button):
                self._neo.set_led_color(pixel, *rgb)
            self._neo.update_strip(sleep_duration=0.001)

    async def all_off(self) -> None:
        self.lights = ["off"] * self.ring_count
        if not self._neo:
            return
        async with self._lock:
            self._neo.clear_strip()
            self._neo.update_strip(sleep_duration=0.001)

    async def _fill_all(self, rgb: tuple[int, int, int]) -> None:
        """Acende todos os LEDs da cadeia com a mesma cor."""
        if not self._neo:
            return
        async with self._lock:
            for pixel in range(self.total_leds):
                self._neo.set_led_color(pixel, *rgb)
            self._neo.update_strip(sleep_duration=0.001)

    async def _fill_ring(self, ring: int, rgb: tuple[int, int, int]) -> None:
        """Apaga tudo e acende apenas o anel (ilha) indicado, 0-based."""
        if not self._neo:
            return
        async with self._lock:
            for pixel in range(self.total_leds):
                self._neo.set_led_color(pixel, 0, 0, 0)
            for pixel in self.ring_led_range(ring):
                self._neo.set_led_color(pixel, *rgb)
            self._neo.update_strip(sleep_duration=0.001)

    async def boot_animation(self, cycles: int = 2) -> None:
        """Teste visual dos anéis executado ao subir o serviço.

        Roda um número fixo de ciclos (padrão 2) e encerra: em cada ciclo
        acende todos os LEDs em cada cor da paleta e depois faz a varredura
        anel por anel. No modo simulador não faz nada além de registrar log.
        """
        if not self._neo:
            LOGGER.info("Boot dos LEDs ignorado (modo %s).", self.mode)
            return

        LOGGER.info("Boot dos LEDs: %s ciclo(s) de teste dos anéis.", cycles)
        try:
            for cycle in range(1, cycles + 1):
                LOGGER.info("Boot dos LEDs: ciclo %s/%s.", cycle, cycles)

                # Fase 1: todos os LEDs juntos, uma cor de cada vez.
                for name, base_rgb in BOOT_COLORS:
                    rgb = tuple(round(channel * self.brightness) for channel in base_rgb)
                    await self._fill_all(rgb)
                    await asyncio.sleep(0.6)

                await self.all_off()
                await asyncio.sleep(0.3)

                # Fase 2: varredura anel por anel (ilha por ilha).
                for ring in range(self.ring_count):
                    base_rgb = BOOT_COLORS[ring % len(BOOT_COLORS)][1]
                    rgb = tuple(round(channel * self.brightness) for channel in base_rgb)
                    await self._fill_ring(ring, rgb)
                    await asyncio.sleep(0.18)

                await self.all_off()
                await asyncio.sleep(0.3)
        finally:
            # Garante que os anéis fiquem apagados ao final do boot.
            await self.all_off()
            LOGGER.info("Boot dos LEDs concluído.")

    async def apply_game_message(self, message: dict) -> None:
        message_type = message.get("type")
        if message_type == "note":
            await self.set_light(int(message["button"]), "blue")
        elif message_type == "note_off":
            await self.set_light(int(message["button"]), "off")
        elif message_type == "feedback":
            result = message.get("result")
            if result == "hit":
                await self.set_light(int(message["button"]), "green")
            elif result in {"wrong", "miss"}:
                button = int(message["button"])
                await self.set_light(button, "red")
                if result == "wrong":
                    self._start_flash_clear(button)
        elif message_type in {"all_off", "finished", "stopped"}:
            await self.all_off()

    def _start_flash_clear(self, button: int) -> None:
        task = asyncio.create_task(self._clear_after(button, 0.18))
        self._flash_tasks.add(task)
        task.add_done_callback(self._flash_tasks.discard)

    async def _clear_after(self, button: int, delay: float) -> None:
        await asyncio.sleep(delay)
        if self.lights[button] == "red":
            await self.set_light(button, "off")

    async def close(self) -> None:
        for task in self._flash_tasks:
            task.cancel()
        self._flash_tasks.clear()
        for button in self._buttons:
            button.close()
        self._buttons.clear()
        if self._neo:
            try:
                await self.all_off()
            finally:
                self._neo.close()
                self._neo = None
        self.mode = "simulator"

    @staticmethod
    def _is_raspberry_pi() -> bool:
        model_path = Path("/proc/device-tree/model")
        try:
            return "Raspberry Pi" in model_path.read_text(errors="ignore")
        except OSError:
            return False
