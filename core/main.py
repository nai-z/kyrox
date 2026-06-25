import json
import os
import re
from pathlib import Path

import httpx
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# ── Paths ──────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.parent
SETTINGS_FILE = BASE_DIR / "settings.json"
HISTORY_FILE  = BASE_DIR / "history.json"

# ── Free models rotation list (best first) ────────────────────────────────
FREE_MODELS = [
    "deepseek/deepseek-r1:free",
    "deepseek/deepseek-v3:free",
    "meta-llama/llama-3.3-70b-instruct:free",
    "meta-llama/llama-4-maverick:free",
    "qwen/qwen3-coder:free",
    "qwen/qwen3-235b-a22b:free",
    "google/gemma-3-12b-it:free",
    "mistralai/mistral-small:free",
    "nvidia/llama-3.1-nemotron-ultra-253b-v1:free",
    "openrouter/auto",   # fallback: OpenRouter picks best available free model
]

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# ── Default settings ───────────────────────────────────────────────────────
DEFAULT_SETTINGS = {
    "backend": "openrouter",        # "openrouter" or "ollama"
    "openrouter_key": "",
    "current_model_index": 0,
    "ollama_url": "http://localhost:11434",
    "ollama_model": "llama3",
    "system_prompt": (
        "You are Kyrox, an intelligent AI companion. "
        "You are helpful, concise, and friendly. "
        "Always respond naturally as Kyrox."
    ),
    "tts_voice": "en-US-GuyNeural",
    "wakeword": "hey kyrox",
    "show_thinking": True,
    "tts": True,
}


def load_settings() -> dict:
    if SETTINGS_FILE.exists():
        with open(SETTINGS_FILE) as f:
            data = json.load(f)
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
        json.dump(history[-100:], f, indent=2)


# ── App ────────────────────────────────────────────────────────────────────
app = FastAPI(title="Kyrox")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

static_dir = BASE_DIR / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


# ── Models ─────────────────────────────────────────────────────────────────
class SettingsUpdate(BaseModel):
    backend: str | None = None
    openrouter_key: str | None = None
    ollama_url: str | None = None
    ollama_model: str | None = None
    system_prompt: str | None = None
    tts_voice: str | None = None
    wakeword: str | None = None
    show_thinking: bool | None = None
    tts: bool | None = None


# ── Routes ─────────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def index():
    html_path = BASE_DIR / "templates" / "index.html"
    return HTMLResponse(content=html_path.read_text(encoding="utf-8"))


@app.get("/api/settings")
async def get_settings():
    s = load_settings()
    s["free_models"] = FREE_MODELS
    s["current_model"] = FREE_MODELS[s.get("current_model_index", 0)]
    return s


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


@app.get("/api/status")
async def status():
    settings = load_settings()
    if settings.get("backend") == "ollama":
        try:
            async with httpx.AsyncClient(timeout=3) as client:
                await client.get(f"{settings['ollama_url']}/api/tags")
            return {"ok": True, "backend": "ollama", "model": settings.get("ollama_model")}
        except Exception:
            return {"ok": False, "backend": "ollama", "error": "Ollama not reachable"}
    else:
        has_key = bool(settings.get("openrouter_key", "").strip())
        idx = settings.get("current_model_index", 0)
        return {
            "ok": has_key,
            "backend": "openrouter",
            "model": FREE_MODELS[idx] if idx < len(FREE_MODELS) else FREE_MODELS[0],
            "has_key": has_key,
        }


# ── WebSocket chat ─────────────────────────────────────────────────────────
@app.websocket("/ws/chat")
async def chat_ws(ws: WebSocket):
    await ws.accept()
    history  = load_history()
    settings = load_settings()

    try:
        while True:
            data    = await ws.receive_text()
            payload = json.loads(data)
            action  = payload.get("action", "chat")
            settings = load_settings()

            if action == "clear":
                history = []
                save_history(history)
                await ws.send_text(json.dumps({"type": "cleared"}))
                continue

            user_msg = payload.get("message", "").strip()
            if not user_msg:
                continue

            history.append({"role": "user", "content": user_msg})

            messages = [{"role": "system", "content": settings["system_prompt"]}]
            messages += history[-20:]

            await ws.send_text(json.dumps({"type": "thinking_start"}))

            full_response = ""
            success = False

            # ── OpenRouter backend ─────────────────────────────────────────
            if settings.get("backend", "openrouter") == "openrouter":
                api_key = settings.get("openrouter_key", "").strip()
                if not api_key:
                    await ws.send_text(json.dumps({
                        "type": "error",
                        "content": "no_api_key",
                    }))
                    history.pop()
                    continue

                idx = settings.get("current_model_index", 0)
                tried = 0

                while tried < len(FREE_MODELS):
                    model = FREE_MODELS[idx % len(FREE_MODELS)]
                    await ws.send_text(json.dumps({
                        "type": "model_info",
                        "model": model,
                    }))

                    try:
                        async with httpx.AsyncClient(timeout=60) as client:
                            async with client.stream(
                                "POST",
                                OPENROUTER_URL,
                                headers={
                                    "Authorization": f"Bearer {api_key}",
                                    "Content-Type": "application/json",
                                    "HTTP-Referer": "https://github.com/nai-z/kyrox",
                                    "X-Title": "Kyrox AI",
                                },
                                json={
                                    "model": model,
                                    "messages": messages,
                                    "stream": True,
                                },
                            ) as response:
                                if response.status_code == 429:
                                    # Rate limited — try next model
                                    await ws.send_text(json.dumps({
                                        "type": "model_switch",
                                        "reason": "rate_limit",
                                        "from": model,
                                    }))
                                    idx = (idx + 1) % len(FREE_MODELS)
                                    tried += 1
                                    continue

                                if response.status_code != 200:
                                    idx = (idx + 1) % len(FREE_MODELS)
                                    tried += 1
                                    continue

                                async for line in response.aiter_lines():
                                    if not line or not line.startswith("data:"):
                                        continue
                                    raw = line[5:].strip()
                                    if raw == "[DONE]":
                                        break
                                    try:
                                        chunk = json.loads(raw)
                                    except json.JSONDecodeError:
                                        continue
                                    token = (
                                        chunk.get("choices", [{}])[0]
                                        .get("delta", {})
                                        .get("content", "")
                                    ) or ""
                                    full_response += token
                                    if token:
                                        await ws.send_text(json.dumps({
                                            "type": "token",
                                            "content": token,
                                        }))

                                # Save current model index so next msg starts here
                                settings["current_model_index"] = idx % len(FREE_MODELS)
                                save_settings(settings)
                                success = True
                                break

                    except Exception:
                        idx = (idx + 1) % len(FREE_MODELS)
                        tried += 1

                if not success:
                    await ws.send_text(json.dumps({
                        "type": "error",
                        "content": "Tous les modèles gratuits sont en limite. Réessaie dans quelques minutes.",
                    }))
                    history.pop()
                    continue

            # ── Ollama backend ─────────────────────────────────────────────
            else:
                try:
                    async with httpx.AsyncClient(timeout=120) as client:
                        async with client.stream(
                            "POST",
                            f"{settings['ollama_url']}/api/chat",
                            json={
                                "model": settings["ollama_model"],
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
                                if token:
                                    await ws.send_text(json.dumps({
                                        "type": "token",
                                        "content": token,
                                    }))
                    success = True
                except Exception as e:
                    await ws.send_text(json.dumps({
                        "type": "error",
                        "content": f"Ollama error: {str(e)}",
                    }))
                    history.pop()
                    continue

            clean_response = re.sub(
                r"<think>.*?</think>", "", full_response, flags=re.DOTALL
            ).strip()

            history.append({"role": "assistant", "content": clean_response})
            save_history(history)

            await ws.send_text(json.dumps({
                "type": "done",
                "content": clean_response,
            }))

    except WebSocketDisconnect:
        pass
