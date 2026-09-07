import asyncio
import time
import unittest

from backend.game import GameEngine
from backend.hardware import HardwareController


class HardwareGameTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.messages = []
        self.hardware = HardwareController(requested_mode="simulator")

        async def send(message):
            self.messages.append(message)
            await self.hardware.apply_game_message(message)

        self.engine = GameEngine(send)
        await self.hardware.start(self.engine.press)

    async def asyncTearDown(self):
        await self.hardware.close()

    async def test_note_lights_only_the_corresponding_ring(self):
        await self.hardware.apply_game_message({"type": "note", "button": 4})
        self.assertEqual(self.hardware.lights[4], "blue")
        self.assertEqual(self.hardware.lights.count("blue"), 1)

    async def test_correct_physical_press_scores_and_turns_ring_green(self):
        self.engine.active = True
        self.engine.current_event = {"button": 2}
        self.engine.event_opened_at = time.monotonic()

        await self.engine.press(2)

        self.assertEqual(self.engine.score, 10)
        self.assertEqual(self.engine.hits, 1)
        self.assertEqual(self.hardware.lights[2], "green")

    async def test_wrong_press_flashes_red_without_scoring(self):
        self.engine.active = True
        self.engine.current_event = {"button": 6}
        self.engine.event_opened_at = time.monotonic()

        await self.engine.press(1)
        self.assertEqual(self.engine.score, 0)
        self.assertEqual(self.hardware.lights[1], "red")

        await asyncio.sleep(0.2)
        self.assertEqual(self.hardware.lights[1], "off")

    async def test_boot_animation_is_safe_in_simulator(self):
        # Sem hardware real (_neo é None) o boot não deve falhar nem acender LEDs.
        await self.hardware.boot_animation(cycles=2)
        self.assertEqual(self.hardware.lights, ["off"] * self.hardware.ring_count)

    async def test_ring_led_range_matches_island_addresses(self):
        # Mapa da imagem: nota/botão N -> ilha N+1 -> 12 LEDs consecutivos.
        expected = {0: (0, 11), 4: (48, 59), 9: (108, 119)}
        for button, (first, last) in expected.items():
            addresses = list(self.hardware.ring_led_range(button))
            self.assertEqual(addresses[0], first)
            self.assertEqual(addresses[-1], last)
            self.assertEqual(len(addresses), 12)

    async def test_looping_song_repeats_until_stopped(self):
        song = {
            "id": "loop-test",
            "loop": True,
            "loop_span_ms": 200,
            "events": [{"time_ms": 10, "button": 0, "note": "DO", "window_ms": 10}],
        }
        await self.engine.start(song)
        # _run tem 3s de contagem regressiva antes de ativar; espera passar dela
        # e dar tempo de várias passadas do loop (loop_span_ms=200ms).
        await asyncio.sleep(3.8)
        # Ainda rodando (não finalizou sozinho) porque é loop.
        self.assertTrue(self.engine.active)
        notes = [m for m in self.messages if m.get("type") == "note"]
        self.assertGreaterEqual(len(notes), 2)
        await self.engine.stop()
        self.assertFalse(self.engine.active)


if __name__ == "__main__":
    unittest.main()
