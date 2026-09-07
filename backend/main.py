from __future__ import annotations

import json
import re
import shutil
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Body, FastAPI, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .game import GameEngine
from .analyzer import NOTES, analyze_audio
from .hardware import HardwareController

ROOT = Path(__file__).resolve().parents[1]
SONGS = ROOT / "songs"
WEB = ROOT / "frontend" / "dist"

clients: set[WebSocket] = set()
hardware = HardwareController()


def load_songs() -> list[dict]:
    found = []
    for chart in sorted(SONGS.glob("*/chart.json")):
        data = json.loads(chart.read_text(encoding="utf-8"))
        data["event_count"] = len(data.get("events", []))
        found.append(data)
    return found


async def broadcast(message: dict) -> None:
    await hardware.apply_game_message(message)
    dead = []
    for client in clients:
        try:
            await client.send_json(message)
        except Exception:
            dead.append(client)
    clients.difference_update(dead)


engine = GameEngine(broadcast)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await hardware.start(engine.press)
    await hardware.boot_animation()
    try:
        yield
    finally:
        await engine.stop()
        await hardware.close()


app = FastAPI(title="Jogo Musical Raspberry", lifespan=lifespan)


@app.get("/api/health")
def health():
    return {"ok": True, **hardware.status()}


@app.get("/api/songs")
def songs():
    return [{k: v for k, v in song.items() if k != "events"} for song in load_songs()]


@app.get("/api/songs/{song_id}")
def song_details(song_id: str):
    chart_path = SONGS / safe_slug(song_id) / "chart.json"
    if not chart_path.exists():
        raise HTTPException(404, "Música não encontrada.")
    return json.loads(chart_path.read_text(encoding="utf-8"))


@app.put("/api/songs/{song_id}/chart")
def update_chart(song_id: str, events: list[dict] = Body(...)):
    chart_path = SONGS / safe_slug(song_id) / "chart.json"
    if not chart_path.exists():
        raise HTTPException(404, "Música não encontrada.")
    validated = validate_events(events)
    chart = json.loads(chart_path.read_text(encoding="utf-8"))
    chart["events"] = sorted(validated, key=lambda item: int(item["time_ms"]))
    chart_path.write_text(json.dumps(chart, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, "events": chart["events"]}


def safe_slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug[:60] or "musica"


def validate_events(events: list[dict]) -> list[dict]:
    if not isinstance(events, list):
        raise ValueError
    for event in events:
        if not isinstance(event, dict) or not 0 <= int(event["button"]) <= 9 or int(event["time_ms"]) < 0:
            raise ValueError
        event["time_ms"] = int(event["time_ms"])
        event["button"] = int(event["button"])
        event["note"] = NOTES[event["button"]]
        event["window_ms"] = int(event.get("window_ms", 430))
    return events


@app.post("/api/songs")
async def create_song(
    title: str = Form(...),
    artist: str = Form(""),
    chart_json: str = Form(""),
    generation_mode: str = Form("automatic"),
    difficulty: str = Form("medium"),
    max_notes: int = Form(350),
    audio: UploadFile = File(...),
):
    if not audio.filename or Path(audio.filename).suffix.lower() != ".mp3":
        raise HTTPException(400, "Envie um arquivo MP3.")
    base = safe_slug(title)
    song_id = base
    sequence = 2
    while (SONGS / song_id).exists():
        song_id = f"{base}-{sequence}"
        sequence += 1
    folder = SONGS / song_id
    folder.mkdir(parents=True)
    audio_name = "audio.mp3"
    with (folder / audio_name).open("wb") as destination:
        shutil.copyfileobj(audio.file, destination)
    duration = 0.0
    if generation_mode == "automatic":
        try:
            events, duration = await asyncio.to_thread(
                analyze_audio, folder / audio_name, difficulty, max(10, min(max_notes, 2000))
            )
        except Exception as error:
            shutil.rmtree(folder)
            raise HTTPException(422, f"Não foi possível analisar o áudio: {error}")
    else:
        try:
            events = validate_events(json.loads(chart_json))
        except (ValueError, TypeError, KeyError, json.JSONDecodeError):
            shutil.rmtree(folder)
            raise HTTPException(400, "Mapa inválido. Use uma lista JSON com time_ms e button de 0 a 9.")
    chart = {
        "id": song_id,
        "title": title.strip(),
        "artist": artist.strip(),
        "audio": f"/songs/{song_id}/{audio_name}",
        "duration": round(duration, 2),
        "difficulty": difficulty,
        "events": sorted(events, key=lambda item: int(item["time_ms"])),
    }
    (folder / "chart.json").write_text(json.dumps(chart, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, "song": {k: v for k, v in chart.items() if k != "events"}, "events": chart["events"]}


@app.websocket("/ws")
async def websocket(ws: WebSocket):
    await ws.accept()
    clients.add(ws)
    await ws.send_json({"type": "ready"})
    try:
        while True:
            message = await ws.receive_json()
            if message.get("type") == "start":
                song = next((s for s in load_songs() if s["id"] == message.get("song")), None)
                if song:
                    await engine.start(song)
            elif message.get("type") == "press":
                await engine.press(int(message["button"]))
            elif message.get("type") == "stop":
                await engine.stop()
                await broadcast({"type": "stopped"})
    except WebSocketDisconnect:
        clients.discard(ws)


app.mount("/songs", StaticFiles(directory=SONGS), name="songs")
app.mount("/assets", StaticFiles(directory=WEB / "assets"), name="assets")


@app.get("/{path:path}")
def spa(path: str):
    target = WEB / path
    return FileResponse(target if target.is_file() else WEB / "index.html")
