import json
import os
import re
import subprocess
import platform
import webbrowser
import tempfile
import shutil
import base64
import io
from pathlib import Path
from datetime import datetime

import httpx
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

BASE_DIR = Path(__file__).parent.parent
SETTINGS_FILE = BASE_DIR / "settings.json"
HISTORY_FILE  = BASE_DIR / "history.json"
MEMORY_FILE   = BASE_DIR / "memory.json"

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
VISION_MODEL = "google/gemini-flash-1.5"

async def is_screen_request(text: str, api_key: str) -> bool:
    """Ask a fast LLM if this message is asking to look at the screen."""
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            resp = await client.post(
                OPENROUTER_URL,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={
                    "model": "mistralai/mistral-small:free",
                    "messages": [
                        {"role": "system", "content": "You are a classifier. Answer only 'yes' or 'no'. No other text."},
                        {"role": "user", "content": f"Is this message asking an AI assistant to look at, watch, analyze, describe, or capture the user's screen or display? Message: \"{text}\""}
                    ],
                    "max_tokens": 3,
                }
            )
            if resp.status_code == 200:
                answer = resp.json()["choices"][0]["message"]["content"].strip().lower()
                return answer.startswith("yes")
    except Exception:
        pass
    return False

def take_screenshot() -> str | None:
    """Take a screenshot and return base64 PNG string, or None."""
    try:
        import mss
        with mss.mss() as sct:
            monitor = sct.monitors[1]
            sct_img = sct.grab(monitor)
            try:
                from PIL import Image
                img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
            except ImportError:
                # Fallback: use mss built-in PNG (no resize)
                raw = mss.tools.to_png(sct_img.rgb, sct_img.size)
                return base64.b64encode(raw).decode("utf-8")
            max_w = 1280
            if img.width > max_w:
                ratio = max_w / img.width
                img = img.resize((max_w, int(img.height * ratio)), Image.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format="PNG", optimize=True)
            return base64.b64encode(buf.getvalue()).decode("utf-8")
    except Exception:
        try:
            import pyautogui
            from PIL import Image
            img = pyautogui.screenshot()
            buf = io.BytesIO()
            img.save(buf, format="PNG", optimize=True)
            return base64.b64encode(buf.getvalue()).decode("utf-8")
        except Exception:
            return None

async def call_vision_model(api_key: str, image_b64: str, user_message: str, system_prompt: str) -> str:
    """Send screenshot + user message to Gemini Flash vision model."""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                OPENROUTER_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://github.com/nai-z/kyrox",
                    "X-Title": "Kyrox AI",
                },
                json={
                    "model": VISION_MODEL,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {
                            "role": "user",
                            "content": [
                                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}},
                                {"type": "text", "text": user_message or "Describe what you see on this screen in detail."}
                            ]
                        }
                    ],
                    "max_tokens": 1024,
                }
            )
            if resp.status_code == 200:
                return resp.json()["choices"][0]["message"]["content"]
            else:
                return f"Vision model error {resp.status_code}: {resp.text[:200]}"
    except Exception as e:
        return f"Vision error: {str(e)}"

DEFAULT_SETTINGS = {
    "backend": "openrouter",
    "openrouter_key": "",
    "current_model_index": 0,
    "ollama_url": "http://localhost:11434",
    "ollama_model": "llama3",
    "system_prompt": (
        "You are Kyrox, an elite AI companion inspired by JARVIS. "
        "You are sharp, confident, slightly witty, and deeply helpful. "
        "You remember everything about your user and use it naturally in conversation. "
        "When asked to open an app or website, reply with an action block: "
        "```action\n{\"type\":\"open\",\"target\":\"app_or_url\",\"label\":\"human readable name\"}\n``` "
        "When asked to run/create a script, write the script code and reply with: "
        "```action\n{\"type\":\"run_script\",\"lang\":\"python\",\"code\":\"...your script...\"}\n``` "
        "When asked to read a file, reply with: "
        "```action\n{\"type\":\"read_file\",\"path\":\"...absolute path...\"}\n``` "
        "When asked to search the web, reply with: "
        "```action\n{\"type\":\"search\",\"query\":\"...\"}\n``` "
        "When asked to send socials or share links, reply with: "
        "```action\n{\"type\":\"send_socials\"}\n``` "
        "For code displayed to the user (not executed), wrap in triple backticks with language. "
        "Never say emoji names or 'smiling face emoji'. Skip them in speech."
    ),
    "tts_voice": "en-US-GuyNeural",
    "wakeword": "hey kyrox",
    "show_thinking": True,
    "tts": True,
    "socials": {
        "twitch": "", "twitter": "", "instagram": "",
        "youtube": "", "discord": "", "github": "",
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
        json.dump(history[-200:], f, indent=2)

def load_memory() -> dict:
    if MEMORY_FILE.exists():
        with open(MEMORY_FILE) as f:
            return json.load(f)
    return {"facts": [], "preferences": {}, "last_updated": ""}

def save_memory(memory: dict):
    memory["last_updated"] = datetime.now().isoformat()
    with open(MEMORY_FILE, "w") as f:
        json.dump(memory, f, indent=2)

def memory_summary(memory: dict) -> str:
    facts = memory.get("facts", [])
    prefs = memory.get("preferences", {})
    if not facts and not prefs:
        return ""
    lines = ["[MEMORY — what you know about the user:]"]
    for f in facts[-30:]:
        lines.append(f"  - {f}")
    for k, v in prefs.items():
        lines.append(f"  - {k}: {v}")
    return "\n".join(lines)

def execute_pc_action(action: dict, settings: dict) -> dict:
    action_type = action.get("type")
    target = action.get("target", "")
    os_name = platform.system()

    if action_type == "open":
        try:
            if target.startswith("http://") or target.startswith("https://"):
                webbrowser.open(target)
                return {"ok": True, "message": f"Opened {target} in browser"}
            if "://" in target or target.endswith(":"):
                if os_name == "Windows":
                    os.startfile(target)
                else:
                    subprocess.Popen(["xdg-open", target])
                return {"ok": True, "message": f"Launched {target}"}
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
            if os_name == "Windows":
                subprocess.Popen(target, shell=True)
            elif os_name == "Darwin":
                subprocess.Popen(["open", "-a", target])
            else:
                subprocess.Popen([target])
            return {"ok": True, "message": f"Launched {target}"}
        except Exception as e:
            return {"ok": False, "message": f"Could not open {target}: {str(e)}"}

    elif action_type == "run_script":
        lang = action.get("lang", "python").lower()
        code = action.get("code", "")
        if not code.strip():
            return {"ok": False, "message": "No script code provided."}
        try:
            ext_map = {"python": ".py", "py": ".py", "bash": ".sh", "shell": ".sh", "powershell": ".ps1", "batch": ".bat", "js": ".js", "javascript": ".js"}
            ext = ext_map.get(lang, ".py")
            with tempfile.NamedTemporaryFile(mode="w", suffix=ext, delete=False, encoding="utf-8") as f:
                f.write(code)
                tmp_path = f.name
            if lang in ("python", "py"):
                proc = subprocess.run(["python", tmp_path], capture_output=True, text=True, timeout=30)
            elif lang in ("bash", "shell"):
                proc = subprocess.run(["bash", tmp_path], capture_output=True, text=True, timeout=30)
            elif lang == "powershell":
                proc = subprocess.run(["powershell", "-File", tmp_path], capture_output=True, text=True, timeout=30)
            elif lang in ("batch", "bat"):
                proc = subprocess.run(["cmd", "/c", tmp_path], capture_output=True, text=True, timeout=30)
            else:
                proc = subprocess.run(["python", tmp_path], capture_output=True, text=True, timeout=30)
            os.unlink(tmp_path)
            output = (proc.stdout or "") + (proc.stderr or "")
            return {"ok": proc.returncode == 0, "message": output.strip() or "Script executed (no output).", "script_path": tmp_path}
        except subprocess.TimeoutExpired:
            return {"ok": False, "message": "Script timed out after 30s."}
        except Exception as e:
            return {"ok": False, "message": f"Error running script: {str(e)}"}

    elif action_type == "read_file":
        path = Path(target)
        try:
            if not path.exists():
                return {"ok": False, "message": f"File not found: {target}"}
            if path.stat().st_size > 5 * 1024 * 1024:
                return {"ok": False, "message": "File too large (>5MB)."}
            content = path.read_text(encoding="utf-8", errors="replace")
            return {"ok": True, "message": f"Read {len(content)} chars from {path.name}", "content": content[:8000]}
        except Exception as e:
            return {"ok": False, "message": f"Could not read file: {str(e)}"}

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
        url_map = {
            "wikipedia": f"https://en.wikipedia.org/wiki/Special:Search?search={query.replace(' ', '+')}",
            "youtube": f"https://www.youtube.com/results?search_query={query.replace(' ', '+')}",
            "google": f"https://www.google.com/search?q={query.replace(' ', '+')}",
        }
        webbrowser.open(url_map.get(engine, url_map["google"]))
        return {"ok": True, "message": f"Searched '{query}' on {engine}"}

    return {"ok": False, "message": "Unknown action"}


app = FastAPI(title="Kyrox")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

static_dir = BASE_DIR / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


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

class MemoryUpdate(BaseModel):
    facts: list | None = None
    preferences: dict | None = None


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

@app.get("/api/memory")
async def get_memory():
    return load_memory()

@app.post("/api/memory")
async def update_memory(body: MemoryUpdate):
    memory = load_memory()
    if body.facts is not None:
        memory["facts"] = body.facts
    if body.preferences is not None:
        memory["preferences"] = {**memory.get("preferences", {}), **body.preferences}
    save_memory(memory)
    return {"ok": True, "memory": memory}

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
            memory   = load_memory()

            if action == "clear":
                history = []
                save_history(history)
                await ws.send_text(json.dumps({"type": "cleared"}))
                continue

            if action == "pc_action":
                pc_action = payload.get("pc_action", {})
                result = execute_pc_action(pc_action, settings)
                await ws.send_text(json.dumps({"type": "action_result", "result": result}))
                continue

            # Memory learning from user messages
            if action == "learn":
                fact = payload.get("fact", "").strip()
                if fact:
                    memory["facts"].append(fact)
                    save_memory(memory)
                    await ws.send_text(json.dumps({"type": "learned", "fact": fact}))
                continue

            user_msg = payload.get("message", "").strip()
            if not user_msg:
                continue

            # Auto-extract facts from user messages (simple heuristics)
            auto_facts = []
            patterns = [
                (r"(?:my name is|i'm called|call me)\s+(\w+)", "User's name is {}"),
                (r"i(?:'m| am)\s+(\d+)\s*(?:years?\s*old)", "User is {} years old"),
                (r"i(?:'m| am)\s+(?:a\s+)?(?:developer|programmer|designer|student|engineer|gamer)", "User is a {}"),
                (r"i\s+(?:love|like|enjoy|play)\s+([^,.!?]+)", "User likes {}"),
                (r"i\s+(?:hate|dislike|don'?t like)\s+([^,.!?]+)", "User dislikes {}"),
                (r"i\s+(?:live|am)\s+in\s+([^,.!?]+)", "User lives in {}"),
                (r"my\s+(?:favorite|fav)\s+\w+\s+is\s+([^,.!?]+)", "User's favorite: {}"),
            ]
            for pat, tmpl in patterns:
                m = re.search(pat, user_msg.lower())
                if m:
                    fact_str = tmpl.format(m.group(1).strip().title() if m.lastindex else m.group(0))
                    if fact_str not in memory.get("facts", []):
                        auto_facts.append(fact_str)

            if auto_facts:
                memory.setdefault("facts", []).extend(auto_facts)
                save_memory(memory)

            history.append({"role": "user", "content": user_msg})

            # Build system prompt with memory
            mem_ctx = memory_summary(memory)
            sys_prompt = settings["system_prompt"]
            if mem_ctx:
                sys_prompt = mem_ctx + "\n\n" + sys_prompt

            # ── Screen vision shortcut ─────────────────────────────────────
            _api_key_for_vision = settings.get("openrouter_key", "").strip()
            if _api_key_for_vision and settings.get("backend", "openrouter") == "openrouter" and await is_screen_request(user_msg, _api_key_for_vision):
                await ws.send_text(json.dumps({"type": "thinking_start"}))
                await ws.send_text(json.dumps({"type": "token", "content": "📸 Taking screenshot…"}))
                img_b64 = take_screenshot()
                if img_b64 is None:
                    err = "I couldn't capture your screen. Make sure mss and pillow are installed: pip install mss pillow"
                    await ws.send_text(json.dumps({"type": "done", "content": err}))
                    history.append({"role": "assistant", "content": err})
                    save_history(history)
                    continue
                await ws.send_text(json.dumps({"type": "model_info", "model": VISION_MODEL}))
                vision_response = await call_vision_model(_api_key_for_vision, img_b64, user_msg, sys_prompt)
                history.append({"role": "assistant", "content": vision_response})
                save_history(history)
                await ws.send_text(json.dumps({"type": "done", "content": vision_response}))
                continue
            # ─────────────────────────────────────────────────────────────

            messages = [{"role": "system", "content": sys_prompt}]
            messages += history[-20:]

            await ws.send_text(json.dumps({"type": "thinking_start"}))

            full_response = ""
            success = False

            if settings.get("backend", "openrouter") == "openrouter":
                api_key = settings.get("openrouter_key", "").strip()
                if not api_key:
                    await ws.send_text(json.dumps({"type": "error", "content": "no_api_key"}))
                    history.pop()
                    continue

                idx = settings.get("current_model_index", 0)
                tried = 0

                while tried < len(FREE_MODELS):
                    model = FREE_MODELS[idx % len(FREE_MODELS)]
                    await ws.send_text(json.dumps({"type": "model_info", "model": model}))

                    try:
                        async with httpx.AsyncClient(timeout=60) as client:
                            async with client.stream(
                                "POST", OPENROUTER_URL,
                                headers={
                                    "Authorization": f"Bearer {api_key}",
                                    "Content-Type": "application/json",
                                    "HTTP-Referer": "https://github.com/nai-z/kyrox",
                                    "X-Title": "Kyrox AI",
                                },
                                json={"model": model, "messages": messages, "stream": True},
                            ) as response:
                                if response.status_code == 429:
                                    await ws.send_text(json.dumps({"type": "model_switch", "reason": "rate_limit", "from": model}))
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
                                    token = (chunk.get("choices", [{}])[0].get("delta", {}).get("content", "")) or ""
                                    full_response += token
                                    if token:
                                        await ws.send_text(json.dumps({"type": "token", "content": token}))

                                settings["current_model_index"] = idx % len(FREE_MODELS)
                                save_settings(settings)
                                success = True
                                break
                    except Exception:
                        idx = (idx + 1) % len(FREE_MODELS)
                        tried += 1

                if not success:
                    await ws.send_text(json.dumps({"type": "error", "content": "All models rate-limited. Try again in a few minutes."}))
                    history.pop()
                    continue

            else:
                try:
                    async with httpx.AsyncClient(timeout=120) as client:
                        async with client.stream(
                            "POST", f"{settings['ollama_url']}/api/chat",
                            json={"model": settings["ollama_model"], "messages": messages, "stream": True},
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
                                    await ws.send_text(json.dumps({"type": "token", "content": token}))
                    success = True
                except Exception as e:
                    await ws.send_text(json.dumps({"type": "error", "content": f"Ollama error: {str(e)}"}))
                    history.pop()
                    continue

            clean_response = re.sub(r"<think>.*?</think>", "", full_response, flags=re.DOTALL).strip()

            # Parse and execute action blocks
            actions_found = []
            action_pattern = re.compile(r"```action\s*(.*?)\s*```", re.DOTALL)
            for match in action_pattern.finditer(clean_response):
                try:
                    action_obj = json.loads(match.group(1))
                    actions_found.append(action_obj)
                except Exception:
                    pass

            display_response = action_pattern.sub("", clean_response).strip()

            # Handle read_file inline — inject result back into response
            for act in actions_found:
                if act.get("type") == "read_file":
                    result = execute_pc_action(act, settings)
                    if result.get("ok") and result.get("content"):
                        file_ctx = f"\n\n[File contents of {act.get('path')}]:\n```\n{result['content']}\n```"
                        # Add to history so next turn sees file content
                        history.append({"role": "assistant", "content": display_response})
                        history.append({"role": "user", "content": f"[System: file read successful]{file_ctx}"})
                        save_history(history)
                        await ws.send_text(json.dumps({"type": "actions", "actions": [act]}))
                        await ws.send_text(json.dumps({"type": "done", "content": display_response}))
                    else:
                        await ws.send_text(json.dumps({"type": "done", "content": display_response + f"\n\n⚠ {result['message']}"}))
                    actions_found = [a for a in actions_found if a.get("type") != "read_file"]
                    break

            history.append({"role": "assistant", "content": display_response})
            save_history(history)

            if actions_found:
                await ws.send_text(json.dumps({"type": "actions", "actions": actions_found}))

            await ws.send_text(json.dumps({"type": "done", "content": display_response}))

    except WebSocketDisconnect:
        pass
