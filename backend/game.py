from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable

Send = Callable[[dict], Awaitable[None]]


@dataclass
class GameEngine:
    send: Send
    task: asyncio.Task | None = None
    active: bool = False
    score: int = 0
    combo: int = 0
    hits: int = 0
    misses: int = 0
    current_event: dict | None = None
    event_opened_at: float = 0
    already_pressed: bool = False
    history: list[dict] = field(default_factory=list)

    async def start(self, song: dict) -> None:
        await self.stop()
        self.task = asyncio.create_task(self._run(song))

    async def stop(self) -> None:
        self.active = False
        if self.task and not self.task.done():
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        self.task = None
        self.current_event = None
        self.already_pressed = False
        await self.send({"type": "all_off"})

    async def press(self, button: int) -> None:
        if not self.active or not self.current_event or self.already_pressed:
            return
        elapsed = int((time.monotonic() - self.event_opened_at) * 1000)
        expected = int(self.current_event["button"])
        if button != expected:
            self.combo = 0
            await self.send({"type": "feedback", "result": "wrong", "button": button})
            return

        self.already_pressed = True
        delta = abs(elapsed)
        points = 10 if delta <= 100 else 5 if delta <= 250 else 1
        self.score += points
        self.combo += 1
        self.hits += 1
        self.history.append({"button": button, "points": points, "delta_ms": delta})
        await self.send({
            "type": "feedback", "result": "hit", "button": button,
            "points": points, "score": self.score, "combo": self.combo,
        })

    async def _run(self, song: dict) -> None:
        self.score = self.combo = self.hits = self.misses = 0
        self.history.clear()
        await self.send({"type": "countdown", "value": 3})
        await asyncio.sleep(1)
        await self.send({"type": "countdown", "value": 2})
        await asyncio.sleep(1)
        await self.send({"type": "countdown", "value": 1})
        await asyncio.sleep(1)
        self.active = True
        await self.send({"type": "started", "song": song["id"], "audio": song.get("audio")})

        events = song["events"]
        loop = bool(song.get("loop", False))
        # Duração de uma passada completa: usada para reagendar as notas a cada
        # repetição quando a música está em modo loop (demo infinita de teste).
        loop_span_ms = int(song.get("loop_span_ms", 0)) or self._default_loop_span(events)

        started = time.monotonic()
        pass_index = 0
        while self.active:
            base = started + pass_index * (loop_span_ms / 1000)
            for event in events:
                target = base + int(event["time_ms"]) / 1000
                await asyncio.sleep(max(0, target - time.monotonic()))
                self.current_event = event
                self.event_opened_at = time.monotonic()
                self.already_pressed = False
                await self.send({"type": "note", **event})
                await asyncio.sleep(int(event.get("window_ms", 400)) / 1000)
                if not self.already_pressed:
                    self.combo = 0
                    self.misses += 1
                    self.already_pressed = True
                    await self.send({"type": "feedback", "result": "miss", "button": event["button"]})
                    await asyncio.sleep(0.18)
                await self.send({"type": "note_off", "button": event["button"]})
                self.current_event = None
            if not loop:
                break
            pass_index += 1

        self.active = False
        await self.send({
            "type": "finished", "score": self.score, "hits": self.hits,
            "misses": self.misses, "total": len(events),
        })

    @staticmethod
    def _default_loop_span(events: list[dict]) -> int:
        """Tempo de uma passada quando o chart não define loop_span_ms.

        Vai do início até o fim do último evento (tempo + janela) e adiciona
        um pequeno respiro antes de recomeçar, para o loop não ficar colado.
        """
        if not events:
            return 1000
        last = events[-1]
        end_ms = int(last["time_ms"]) + int(last.get("window_ms", 400))
        return end_ms + 1000
