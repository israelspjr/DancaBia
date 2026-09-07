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


if __name__ == "__main__":
    unittest.main()
