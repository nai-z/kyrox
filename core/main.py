import json
import os
import re
import subprocess
import platform
import webbrowser
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

# ── Free models rotation list ─────────────────────────────────────────────
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
    "openrouter/auto",
]

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# ── Default settings ───────────────────────────────────────────────────────
DEFAULT_SETTINGS = {
    "backend": "openrouter",
    "openrouter_key": "",
    "current_model_index": 0,
    "ollama_url": "http://localhost:11434",
    "ollama_model": "llama3",
    "system_prompt": (
        "You are Kyrox, an intelligent AI companion like JARVIS. "
        "You are helpful, concise, and friendly. "
        "Always respond naturally as Kyrox. "
        "When the user asks you to open an app or website, reply with a JSON action block in this exact format on its own line: "
        "```action\n{\"type\":\"open\",\"target\":\"app_or_url\",\"label\":\"human readable name\"}\n``` "
        "When asked to send socials or share links, reply with a JSON action block: "
        "```action\n{\"type\":\"send_socials\"}\n``` "
        "For code, always wrap it in triple backticks with the language name. "
        "Never say 'smiling face emoji' or read out emoji names — just skip them in speech."
    ),
    "tts_voice": "en-US-GuyNeural",
    "wakeword": "hey kyrox",
    "show_thinking": True,
    "tts": True,
    "socials": {
        "twitch": "",
        "twitter": "",
        "instagram": "",
        "youtube": "",
        "discord": "",
        "github": "",
    },
    "apps": {
        "csgo": "steam://rungameid/730",
        "steam": "steam://open/main",
        "spotify": "spotify:",
        "discord": "discord:",
        "chrome": "chrome",
        "firefox": "firefox",
        "vscode": "code",
        "notepad": "notepad",
        "calculator": "calc",
        "explorer": "explorer",
    }
}


def load_settings() -> dict:
    if SETTINGS_FILE.exists():
        with open(SETTINGS_FILE) as f:
            data = json.load(f)
        merged = {**DEFAULT_SETTINGS, **data}
        # Deep merge nested dicts
        for key in ["socials", "apps"]:
            merged[key] = {**DEFAULT_SETTINGS[key], **data.get(key, {})}
        return merged
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


def execute_pc_action(action: dict, settings: dict) -> dict:
    """Execute a PC action — open app, URL, etc."""
    action_type = action.get("type")
    target = action.get("target", "")
    os_name = platform.system()

    if action_type == "open":
        try:
            # Check if it's a URL
            if target.startswith("http://") or target.startswith("https://"):
                webbrowser.open(target)
                return {"ok": True, "message": f"Opened {target} in browser"}

            # Check if it's a protocol URL (steam://, spotify:, discord:, etc.)
            if "://" in target or target.endswith(":"):
                if os_name == "Windows":
                    os.startfile(target)
                else:
                    subprocess.Popen(["xdg-open", target])
                return {"ok": True, "message": f"Launched {target}"}

            # Check app registry in settings
            app_registry = settings.get("apps", {})
            target_lower = target.lower()
            for app_name, app_cmd in app_registry.items():
                if app_name in target_lower or target_lower in app_name:
                    if app_cmd.startswith("http") or "://" in app_cmd:
                        webbrowser.open(app_cmd)
                    elif os_name == "Windows":
                        os.startfile(app_cmd) if os.path.exists(app_cmd) else subprocess.Popen(app_cmd, shell=True)
                    else:
                        subprocess.Popen([app_cmd], shell=True)
                    return {"ok": True, "message": f"Launched {app_name}"}

            # Generic app launch
            if os_name == "Windows":
                subprocess.Popen(target, shell=True)
            elif os_name == "Darwin":
                subprocess.Popen(["open", "-a", target])
            else:
                subprocess.Popen([target])
            return {"ok": True, "message": f"Launched {target}"}

        except Exception as e:
            return {"ok": False, "message": f"Could not open {target}: {str(e)}"}

    elif action_type == "send_socials":
        socials = settings.get("socials", {})
        filled = {k: v for k, v in socials.items() if v.strip()}
        if not filled:
            return {"ok": False, "message": "No socials configured. Add them in Settings!"}
        lines = [f"**{k.capitalize()}**: {v}" for k, v in filled.items()]
        return {"ok": True, "message": "\n".join(lines), "display": True}

    elif action_type == "search":
        query = action.get("query", target)
        engine = action.get("engine", "google")
        if engine == "wikipedia":
            url = f"https://en.wikipedia.org/wiki/Special:Search?search={query.replace(' ', '+')}"
        elif engine == "youtube":
            url = f"https://www.youtube.com/results?search_query={query.replace(' ', '+')}"
        else:
            url = f"https://www.google.com/search?q={query.replace(' ', '+')}"
        webbrowser.open(url)
        return {"ok": True, "message": f"Searched '{query}' on {engine}"}

    return {"ok": False, "message": "Unknown action"}


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
    socials: dict | None = None
    apps: dict | None = None


class PCActionRequest(BaseModel):
    action: dict


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
    update = body.model_dump(exclude_none=True)
    for field, value in update.items():
        if field in ["socials", "apps"] and isinstance(value, dict):
            settings[field] = {**settings.get(field, {}), **value}
        else:
            settings[field] = value
    save_settings(settings)
    return {"ok": True, "settings": settings}


@app.post("/api/action")
async def run_action(body: PCActionRequest):
    settings = load_settings()
    result = execute_pc_action(body.action, settings)
    return result


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

            # PC action executed from frontend
            if action == "pc_action":
                pc_action = payload.get("pc_action", {})
                result = execute_pc_action(pc_action, settings)
                await ws.send_text(json.dumps({"type": "action_result", "result": result}))
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
                        "content": "All free models are rate-limited. Try again in a few minutes.",
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

            # Strip <think> blocks
            clean_response = re.sub(
                r"<think>.*?</think>", "", full_response, flags=re.DOTALL
            ).strip()

            # Parse action blocks from response
            actions_found = []
            action_pattern = re.compile(r"```action\s*(.*?)\s*```", re.DOTALL)
            for match in action_pattern.finditer(clean_response):
                try:
                    action_obj = json.loads(match.group(1))
                    actions_found.append(action_obj)
                except Exception:
                    pass

            # Remove action blocks from display text
            display_response = action_pattern.sub("", clean_response).strip()

            history.append({"role": "assistant", "content": display_response})
            save_history(history)

            # Send actions to frontend for execution
            if actions_found:
                await ws.send_text(json.dumps({
                    "type": "actions",
                    "actions": actions_found,
                }))

            await ws.send_text(json.dumps({
                "type": "done",
                "content": display_response,
            }))

    except WebSocketDisconnect:
        pass
