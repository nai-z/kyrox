import asyncio
import json
import os
import re
from pathlib import Path
from typing import AsyncGenerator

import httpx
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# ── Paths ──────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.parent
SETTINGS_FILE = BASE_DIR / "settings.json"
HISTORY_FILE = BASE_DIR / "history.json"

# ── Default settings ───────────────────────────────────────────────────────
DEFAULT_SETTINGS = {
    "model": "llama3",
    "system_prompt": (
        "You are Kyrox, an intelligent AI companion. "
        "You are helpful, concise, and friendly. "
        "When you reason through a problem, wrap your internal thinking in <think>...</think> tags. "
        "Always respond naturally as Kyrox."
    ),
    "ollama_url": "http://localhost:11434",
    "tts_voice": "en-US-GuyNeural",
    "wakeword": "hey kyrox",
}


def load_settings() -> dict:
    if SETTINGS_FILE.exists():
        with open(SETTINGS_FILE) as f:
            data = json.load(f)
        # merge with defaults for any missing keys
        return {**DEFAULT_SETTINGS, **data}
    return DEFAULT_SETTINGS.copy()


def save_settings(data: dict):
    with open(SETTINGS_FILE, "w") as f:
        json.dump(data, f, indent=2)


def load_history() -> list:
    if HISTORY_FILE.exists():
        with open(HISTORY_FILE) as f:
            return json.load(f)
    return []


def save_history(history: list):
    with open(HISTORY_FILE, "w") as f:
        json.dump(history[-100:], f, indent=2)  # keep last 100 messages


# ── App ────────────────────────────────────────────────────────────────────
app = FastAPI(title="Kyrox")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


# ── Models ─────────────────────────────────────────────────────────────────
class SettingsUpdate(BaseModel):
    model: str | None = None
    system_prompt: str | None = None
    ollama_url: str | None = None
    tts_voice: str | None = None
    wakeword: str | None = None


# ── Routes ─────────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def index():
    html_path = BASE_DIR / "templates" / "index.html"
    return HTMLResponse(content=html_path.read_text(encoding="utf-8"))


@app.get("/api/settings")
async def get_settings():
    return load_settings()


@app.post("/api/settings")
async def update_settings(body: SettingsUpdate):
    settings = load_settings()
    for field, value in body.model_dump(exclude_none=True).items():
        settings[field] = value
    save_settings(settings)
    return {"ok": True, "settings": settings}


@app.get("/api/history")
async def get_history():
    return load_history()


@app.delete("/api/history")
async def clear_history():
    save_history([])
    return {"ok": True}


@app.get("/api/models")
async def list_models():
    settings = load_settings()
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(f"{settings['ollama_url']}/api/tags")
            models = [m["name"] for m in r.json().get("models", [])]
            return {"models": models}
    except Exception:
        return {"models": [], "error": "Ollama not reachable"}


@app.get("/api/status")
async def status():
    settings = load_settings()
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            await client.get(f"{settings['ollama_url']}/api/tags")
            return {"ollama": True}
    except Exception:
        return {"ollama": False}


# ── WebSocket chat ─────────────────────────────────────────────────────────
@app.websocket("/ws/chat")
async def chat_ws(ws: WebSocket):
    await ws.accept()
    history = load_history()
    settings = load_settings()

    try:
        while True:
            data = await ws.receive_text()
            payload = json.loads(data)
            action = payload.get("action", "chat")

            # Reload settings each turn so changes apply live
            settings = load_settings()

            if action == "clear":
                history = []
                save_history(history)
                await ws.send_text(json.dumps({"type": "cleared"}))
                continue

            user_msg = payload.get("message", "").strip()
            if not user_msg:
                continue

            # Add user message to history
            history.append({"role": "user", "content": user_msg})

            # Build messages for Ollama
            messages = [{"role": "system", "content": settings["system_prompt"]}]
            messages += history[-20:]  # last 20 turns for context

            # Send "thinking started" signal
            await ws.send_text(json.dumps({"type": "thinking_start"}))

            full_response = ""
            thinking_content = ""
            in_think = False
            think_buffer = ""

            try:
                async with httpx.AsyncClient(timeout=120) as client:
                    async with client.stream(
                        "POST",
                        f"{settings['ollama_url']}/api/chat",
                        json={
                            "model": settings["model"],
                            "messages": messages,
                            "stream": True,
                        },
                    ) as response:
                        async for line in response.aiter_lines():
                            if not line:
                                continue
                            try:
                                chunk = json.loads(line)
                            except json.JSONDecodeError:
                                continue

                            token = chunk.get("message", {}).get("content", "")
                            full_response += token

                            # Parse <think>...</think> in real-time
                            think_buffer += token
                            while True:
                                if not in_think:
                                    start = think_buffer.find("<think>")
                                    if start != -1:
                                        # emit text before <think>
                                        before = think_buffer[:start]
                                        if before:
                                            await ws.send_text(json.dumps({
                                                "type": "token",
                                                "content": before,
                                            }))
                                        think_buffer = think_buffer[start + 7:]
                                        in_think = True
                                    else:
                                        # no think tag yet, emit safe prefix
                                        safe = think_buffer[:-7] if len(think_buffer) > 7 else ""
                                        if safe:
                                            await ws.send_text(json.dumps({
                                                "type": "token",
                                                "content": safe,
                                            }))
                                            think_buffer = think_buffer[len(safe):]
                                        break
                                else:
                                    end = think_buffer.find("</think>")
                                    if end != -1:
                                        thinking_content += think_buffer[:end]
                                        await ws.send_text(json.dumps({
                                            "type": "thinking",
                                            "content": thinking_content,
                                        }))
                                        thinking_content = ""
                                        think_buffer = think_buffer[end + 8:]
                                        in_think = False
                                    else:
                                        # accumulate thinking
                                        thinking_content += think_buffer
                                        await ws.send_text(json.dumps({
                                            "type": "thinking_token",
                                            "content": think_buffer,
                                        }))
                                        think_buffer = ""
                                        break

                            if chunk.get("done"):
                                # flush remaining buffer
                                if think_buffer and not in_think:
                                    await ws.send_text(json.dumps({
                                        "type": "token",
                                        "content": think_buffer,
                                    }))

            except Exception as e:
                await ws.send_text(json.dumps({
                    "type": "error",
                    "content": f"Ollama error: {str(e)}",
                }))
                continue

            # Clean final response (remove think tags)
            clean_response = re.sub(r"<think>.*?</think>", "", full_response, flags=re.DOTALL).strip()

            # Save to history
            history.append({"role": "assistant", "content": clean_response})
            save_history(history)

            await ws.send_text(json.dumps({
                "type": "done",
                "content": clean_response,
            }))

    except WebSocketDisconnect:
        pass
