from __future__ import annotations
from __future__ import annotations

import json
import os
import re
import shutil
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import Body, FastAPI, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .game import GameEngine
from .analyzer import NOTES, analyze_audio
from .hardware import HardwareController

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "frontend" / "dist"

# Músicas de demonstração versionadas junto do código (somente leitura).
SEED_SONGS = ROOT / "songs"

# Músicas enviadas pelo usuário: gravadas FORA do diretório do app para que
# atualizações de código (git pull, unzip por cima, reinstalação) nunca as
# apaguem. Configurável por MUSIC_DATA_DIR; o padrão fica no home do serviço.
DATA_DIR = Path(os.getenv("MUSIC_DATA_DIR", str(Path.home() / "music-game-data"))).expanduser()
SONGS = DATA_DIR / "songs"
SONGS.mkdir(parents=True, exist_ok=True)

clients: set[WebSocket] = set()
hardware = HardwareController()


def _song_dir(song_id: str) -> Path | None:
    """Diretório de uma música, procurando primeiro nos uploads e depois nas seeds."""
    for base in (SONGS, SEED_SONGS):
        candidate = base / song_id
        if (candidate / "chart.json").exists():
            return candidate
    return None


def load_songs() -> list[dict]:
    found: dict[str, dict] = {}
    # Seeds primeiro; uploads do usuário sobrescrevem se houver id igual.
    for base in (SEED_SONGS, SONGS):
        if not base.exists():
            continue
        for chart in sorted(base.glob("*/chart.json")):
            data = json.loads(chart.read_text(encoding="utf-8"))
            data["event_count"] = len(data.get("events", []))
            found[data["id"]] = data
    return list(found.values())


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


@app.post("/api/system-test")
async def system_test():
    """Teste de sistema: acende as 10 ilhas para conferir os LEDs.

    Não roda durante uma partida (evita conflito de comandos nos anéis).
    """
    if engine.active:
        raise HTTPException(409, "Pare a rodada atual antes de rodar o teste de sistema.")
    await broadcast({"type": "system_test_started"})
    await hardware.boot_animation(cycles=1)
    await broadcast({"type": "system_test_finished"})
    return {"ok": True, "mode": hardware.mode}


@app.get("/api/songs")
def songs():
    return [{k: v for k, v in song.items() if k != "events"} for song in load_songs()]


@app.get("/api/songs/{song_id}")
def song_details(song_id: str):
    folder = _song_dir(safe_slug(song_id))
    if not folder:
        raise HTTPException(404, "Música não encontrada.")
    return json.loads((folder / "chart.json").read_text(encoding="utf-8"))


@app.put("/api/songs/{song_id}/chart")
def update_chart(song_id: str, events: list[dict] = Body(...)):
    slug = safe_slug(song_id)
    folder = _song_dir(slug)
    if not folder:
        raise HTTPException(404, "Música não encontrada.")
    validated = validate_events(events)
    chart = json.loads((folder / "chart.json").read_text(encoding="utf-8"))
    chart["events"] = sorted(validated, key=lambda item: int(item["time_ms"]))
    # Se a música veio de uma seed (repo), grava a versão editada nos dados do
    # usuário para não perder o ajuste em atualizações e não sujar o repositório.
    if folder.parent == SEED_SONGS:
        folder = SONGS / slug
        folder.mkdir(parents=True, exist_ok=True)
    (folder / "chart.json").write_text(json.dumps(chart, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, "events": chart["events"]}


def safe_slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug[:60] or "musica"


def download_youtube_audio(url: str, destination: Path) -> None:
    """Baixa o áudio de um vídeo do YouTube como MP3 usando yt-dlp.

    Requer internet no momento do cadastro e o pacote yt-dlp instalado (ver
    requirements.txt) além do ffmpeg (já instalado pelo script do Raspberry).
    Uso educacional interno (Senac SP), sem fins comerciais.
    """
    try:
        import yt_dlp
    except ImportError as error:  # pragma: no cover - depende do ambiente
        raise RuntimeError(
            "yt-dlp não está instalado. Rode: .venv/bin/pip install yt-dlp"
        ) from error

    # yt-dlp adiciona a extensão do postprocessor (.mp3), então passamos o alvo
    # sem sufixo e conferimos o arquivo final.
    target_stem = destination.with_suffix("")
    options = {
        "format": "bestaudio/best",
        "outtmpl": str(target_stem) + ".%(ext)s",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "postprocessors": [
            {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}
        ],
    }
    with yt_dlp.YoutubeDL(options) as downloader:
        downloader.download([url])

    produced = target_stem.with_suffix(".mp3")
    if not produced.exists():
        raise RuntimeError("Download concluído mas o arquivo MP3 não foi gerado.")
    if produced != destination:
        produced.replace(destination)


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
    youtube_url: str = Form(""),
    audio: Optional[UploadFile] = File(None),
):
    from_youtube = generation_mode == "youtube"
    if from_youtube:
        if not youtube_url.strip():
            raise HTTPException(400, "Informe o link do YouTube.")
    elif not audio or not audio.filename or Path(audio.filename).suffix.lower() != ".mp3":
        raise HTTPException(400, "Envie um arquivo MP3.")

    # id único considerando tanto os uploads quanto as seeds.
    base = safe_slug(title)
    song_id = base
    sequence = 2
    while _song_dir(song_id) is not None:
        song_id = f"{base}-{sequence}"
        sequence += 1
    folder = SONGS / song_id
    folder.mkdir(parents=True)
    audio_name = "audio.mp3"

    if from_youtube:
        try:
            await asyncio.to_thread(download_youtube_audio, youtube_url.strip(), folder / audio_name)
        except Exception as error:
            shutil.rmtree(folder, ignore_errors=True)
            raise HTTPException(422, f"Não foi possível baixar o áudio do YouTube: {error}")
    else:
        with (folder / audio_name).open("wb") as destination:
            shutil.copyfileobj(audio.file, destination)

    duration = 0.0
    # YouTube e "automatic" geram o mapa pela análise do áudio; só o modo
    # "manual" usa o JSON colado.
    if generation_mode in {"automatic", "youtube"}:
        try:
            events, duration = await asyncio.to_thread(
                analyze_audio, folder / audio_name, difficulty, max(10, min(max_notes, 2000))
            )
        except Exception as error:
            shutil.rmtree(folder, ignore_errors=True)
            raise HTTPException(422, f"Não foi possível analisar o áudio: {error}")
    else:
        try:
            events = validate_events(json.loads(chart_json))
        except (ValueError, TypeError, KeyError, json.JSONDecodeError):
            shutil.rmtree(folder, ignore_errors=True)
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


app.mount("/assets", StaticFiles(directory=WEB / "assets"), name="assets")


@app.get("/songs/{song_id}/{filename}")
def song_asset(song_id: str, filename: str):
    """Serve o áudio da música, buscando nos uploads do usuário e nas seeds."""
    folder = _song_dir(safe_slug(song_id))
    if not folder:
        raise HTTPException(404, "Música não encontrada.")
    # Evita path traversal: só o nome do arquivo, dentro da pasta da música.
    target = (folder / Path(filename).name).resolve()
    if folder.resolve() not in target.parents or not target.is_file():
        raise HTTPException(404, "Arquivo não encontrado.")
    return FileResponse(target)


@app.get("/{path:path}")
def spa(path: str):
    target = WEB / path
    return FileResponse(target if target.is_file() else WEB / "index.html")
