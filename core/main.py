"""
Kyrox — AI Companion Backend
FastAPI + WebSocket + OpenRouter/Ollama
Multi-user, persistent memory, PC actions, screenshot vision, .md/.txt context reader
"""

import json, os, re, subprocess, platform, webbrowser, tempfile, base64, io, hashlib
from pathlib import Path
from datetime import datetime
from typing import Optional

import httpx
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# ── Paths ──────────────────────────────────────────────────────────────────
# Script lives at /kyrox/main.py  →  BASE_DIR = /kyrox
BASE_DIR      = Path(__file__).parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR    = BASE_DIR / "static"
DATA_DIR      = BASE_DIR / "data"
STATIC_DIR.mkdir(exist_ok=True)
DATA_DIR.mkdir(exist_ok=True)

SETTINGS_FILE = DATA_DIR / "settings.json"

FREE_MODELS = [
    "deepseek/deepseek-r1:free",
    "deepseek/deepseek-v3:free",
    "meta-llama/llama-3.3-70b-instruct:free",
    "meta-llama/llama-4-maverick:free",
    "qwen/qwen3-235b-a22b:free",
    "qwen/qwen3-coder:free",
    "google/gemma-3-12b-it:free",
    "mistralai/mistral-small:free",
    "nvidia/llama-3.1-nemotron-ultra-253b-v1:free",
    "openrouter/auto",
]

VISION_MODELS = [
    "google/gemini-flash-1.5",
    "google/gemini-2.0-flash-001",
    "openai/gpt-4o-mini",
    "anthropic/claude-3-haiku",
    "meta-llama/llama-3.2-11b-vision-instruct:free",
]

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# ── Coding / creation skills injected dynamically ─────────────────────────
SKILL_FRONTEND = """
[SKILL: Frontend / HTML creation]
When creating HTML pages, ALWAYS produce a complete, visually stunning result:
- Use modern CSS: gradients, glassmorphism, animations, hover effects, box-shadows
- Google Fonts (import from fonts.googleapis.com)
- Responsive layout with flexbox or grid
- Dark or light theme with cohesive color palette
- Smooth transitions on all interactive elements
- Never output a blank white page with plain text
- For games: use canvas or CSS animations, add score, levels, sound effects via Web Audio API
- For landing pages: hero section, cards, CTA buttons, footer
- For dashboards: sidebar nav, stat cards, charts (use Chart.js from cdnjs)
- ALWAYS include meta viewport tag and charset
- Inline all CSS and JS in a single .html file unless told otherwise
Example quality bar: the output should look like a professional designer made it.
"""

SKILL_PYTHON = """
[SKILL: Python scripting]
When writing Python scripts:
- Add proper error handling (try/except) and meaningful error messages
- Use f-strings, type hints where helpful
- Add a if __name__ == '__main__' guard
- For CLI tools: use argparse or sys.argv
- For file operations: always use pathlib.Path
- Add brief docstrings for functions
- Print clear status messages so the user knows what's happening
- Never write bare scripts with no output — always confirm success/failure
"""

SKILL_FILE_OPS = """
[SKILL: File system operations]
When creating or writing files:
- Always confirm the full path you're writing to
- Use the write_file action with absolute or ~/relative paths
- After writing, mention what was created and where
- For projects (multiple files): create them one by one, announce each
- If creating a folder structure: explain it clearly
"""

DEFAULT_SYSTEM_PROMPT = (
    "You are Kyrox, an elite AI companion inspired by JARVIS from Iron Man. "
    "You are sharp, confident, slightly witty, and deeply helpful. "
    "You remember everything about your user and use it naturally in conversation. "
    "Speak in short, punchy sentences unless a detailed answer is needed. "
    "Match the user's language — if they write in French, respond in French. "
    "When asked to open an app or website, emit an action block:\n"
    "```action\n{\"type\":\"open\",\"target\":\"app_or_url\",\"label\":\"name\"}\n```\n"
    "When asked to search the web:\n"
    "```action\n{\"type\":\"search\",\"query\":\"...\"}\n```\n"
    "When asked to run a script:\n"
    "```action\n{\"type\":\"run_script\",\"lang\":\"python\",\"code\":\"...\"}\n```\n"
    "When asked to read a file:\n"
    "```action\n{\"type\":\"read_file\",\"path\":\"...\"}\n```\n"
    "When asked to create/write/save a file:\n"
    "```action\n{\"type\":\"write_file\",\"path\":\"path/to/file.ext\",\"content\":\"file content here\"}\n```\n"
    "When asked to share socials / send links:\n"
    "```action\n{\"type\":\"send_socials\"}\n```\n"
    "Never explain action blocks to the user. Never say emoji names. "
    "Keep code in triple-backtick blocks when displaying to user."
)

DEFAULT_SETTINGS = {
    "backend": "openrouter",
    "openrouter_key": "",
    "current_model_index": 0,
    "ollama_url": "http://localhost:11434",
    "ollama_model": "llama3",
    "system_prompt": DEFAULT_SYSTEM_PROMPT,
    "wakeword": "hey kyrox",
    "tts": True,
    "tts_voice": "",
    "socials": {"twitch":"","twitter":"","instagram":"","youtube":"","discord":"","github":""},
    "apps": {
        "steam": "steam://open/main",
        "spotify": "spotify:",
        "discord": "discord:",
        "chrome": "chrome",
        "firefox": "firefox",
        "vscode": "code",
        "notepad": "notepad",
        "calculator": "calc",
        "explorer": "explorer",
    },
    "context_files": [],
    "context_text": "",
    "auto_scan_home": True,
}

# ── Settings ───────────────────────────────────────────────────────────────
def load_settings() -> dict:
    if SETTINGS_FILE.exists():
        with open(SETTINGS_FILE) as f:
            data = json.load(f)
        merged = {**DEFAULT_SETTINGS, **data}
        for key in ("socials", "apps"):
            merged[key] = {**DEFAULT_SETTINGS[key], **data.get(key, {})}
        return merged
    return DEFAULT_SETTINGS.copy()

def save_settings(data: dict):
    with open(SETTINGS_FILE, "w") as f:
        json.dump(data, f, indent=2)

# ── Per-user data ──────────────────────────────────────────────────────────
def user_dir(uid: str) -> Path:
    p = DATA_DIR / "users" / uid
    p.mkdir(parents=True, exist_ok=True)
    return p

def load_history(uid: str) -> list:
    p = user_dir(uid) / "history.json"
    return json.loads(p.read_text()) if p.exists() else []

def save_history(uid: str, history: list):
    p = user_dir(uid) / "history.json"
    p.write_text(json.dumps(history[-300:], indent=2))

def load_memory(uid: str) -> dict:
    p = user_dir(uid) / "memory.json"
    return json.loads(p.read_text()) if p.exists() else {"facts": [], "preferences": {}}

def save_memory(uid: str, memory: dict):
    memory["last_updated"] = datetime.now().isoformat()
    p = user_dir(uid) / "memory.json"
    p.write_text(json.dumps(memory, indent=2))

def list_users() -> list[dict]:
    base = DATA_DIR / "users"
    if not base.exists():
        return []
    result = []
    for d in base.iterdir():
        if d.is_dir():
            mem = load_memory(d.name)
            name = next((f.split("name is ")[-1] for f in mem.get("facts", []) if "name is" in f.lower()), d.name[:8])
            result.append({"id": d.name, "name": name})
    return result

def memory_summary(memory: dict) -> str:
    facts = memory.get("facts", [])
    prefs = memory.get("preferences", {})
    if not facts and not prefs:
        return ""
    lines = ["[KYROX MEMORY — ce que tu sais sur cet utilisateur:]"]
    for f in facts[-40:]:
        lines.append(f"  • {f}")
    for k, v in prefs.items():
        lines.append(f"  • {k}: {v}")
    return "\n".join(lines)

# ── Auto-scan home directory for user profile files ───────────────────────
def auto_scan_user_profile() -> str:
    """Scan common user profile files to auto-learn about the user."""
    home = Path.home()
    chunks = []

    # Common profile/about files to check
    profile_candidates = [
        home / "about.md", home / "about.txt",
        home / "README.md", home / "profile.md",
        home / "me.md", home / "me.txt",
        home / "Documents" / "about.md",
        home / "Documents" / "profile.md",
    ]
    for p in profile_candidates:
        if p.exists():
            try:
                chunks.append(f"[Profile file: {p.name}]\n{p.read_text(errors='replace')[:3000]}")
            except Exception:
                pass

    # Scan Desktop for .md/.txt files (project notes, etc.)
    desktop = home / "Desktop"
    if desktop.exists():
        for f in list(desktop.glob("*.md"))[:5] + list(desktop.glob("*.txt"))[:5]:
            try:
                chunks.append(f"[Desktop/{f.name}]\n{f.read_text(errors='replace')[:1500]}")
            except Exception:
                pass

    return "\n\n---\n\n".join(chunks)[:8000]

# ── Context file reader ────────────────────────────────────────────────────
def scan_context_files(paths: list[str]) -> str:
    chunks = []
    for raw in paths:
        p = Path(raw).expanduser()
        if p.is_file() and p.suffix.lower() in (".md", ".txt"):
            try:
                chunks.append(f"[File: {p.name}]\n{p.read_text(errors='replace')[:4000]}")
            except Exception:
                pass
        elif p.is_dir():
            for f in sorted(p.rglob("*"))[:20]:
                if f.is_file() and f.suffix.lower() in (".md", ".txt"):
                    try:
                        chunks.append(f"[File: {f.name}]\n{f.read_text(errors='replace')[:2000]}")
                    except Exception:
                        pass
    combined = "\n\n---\n\n".join(chunks)
    return combined[:12000]

# ── Skill injection based on message content ──────────────────────────────
def get_relevant_skills(message: str) -> str:
    msg_lower = message.lower()
    skills = []

    # Frontend / HTML
    html_keywords = ["html", "page", "site", "website", "web", "css", "interface", "landing",
                     "design", "jeu", "game", "dashboard", "card", "portfolio", "blog",
                     "formulaire", "form", "animation", "bouton", "button"]
    if any(k in msg_lower for k in html_keywords):
        skills.append(SKILL_FRONTEND)

    # Python
    python_keywords = ["python", "script", "code", ".py", "automatise", "automate",
                       "fichier", "file", "liste", "list", "calcul", "calculate"]
    if any(k in msg_lower for k in python_keywords):
        skills.append(SKILL_PYTHON)

    # File operations
    file_keywords = ["crée", "créer", "create", "écris", "write", "sauvegarde", "save",
                     "fichier", "file", "dossier", "folder", "génère", "generate"]
    if any(k in msg_lower for k in file_keywords):
        skills.append(SKILL_FILE_OPS)

    return "\n".join(skills)

# ── PC Actions ────────────────────────────────────────────────────────────
def execute_pc_action(action: dict, settings: dict) -> dict:
    atype  = action.get("type", "")
    target = action.get("target", "").strip()
    os_name = platform.system()

    if atype == "open":
        def _launch(cmd_or_url: str):
            """Open a URL, protocol URI, or executable on any OS."""
            if os_name == "Windows":
                # Use PowerShell Start-Process — handles URLs, protocol URIs, .exe, app names
                subprocess.Popen(
                    ["powershell", "-WindowStyle", "Hidden", "-Command",
                     f"Start-Process '{cmd_or_url}'"],
                    creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
                )
            elif os_name == "Darwin":
                subprocess.Popen(["open", cmd_or_url])
            else:
                subprocess.Popen(["xdg-open", cmd_or_url])

        try:
            # 1. Direct URL → open in browser
            if target.startswith(("http://", "https://")):
                _launch(target)
                return {"ok": True, "message": f"Opened {target}"}

            # 2. Protocol URI (steam://, spotify:, discord:, etc.)
            if "://" in target or (target.endswith(":") and len(target) > 2):
                _launch(target)
                return {"ok": True, "message": f"Launched {target}"}

            # 3. Check registered apps dict (fuzzy match)
            reg = settings.get("apps", {})
            tl = target.lower()
            for name, cmd in reg.items():
                if name in tl or tl in name:
                    _launch(cmd)
                    return {"ok": True, "message": f"Launched {name}"}

            # 4. Known website names → open in browser
            KNOWN_SITES = {
                "youtube": "https://youtube.com",
                "google": "https://google.com",
                "facebook": "https://facebook.com",
                "twitter": "https://twitter.com",
                "instagram": "https://instagram.com",
                "github": "https://github.com",
                "netflix": "https://netflix.com",
                "twitch": "https://twitch.tv",
                "reddit": "https://reddit.com",
                "discord": "https://discord.com",
                "spotify": "https://open.spotify.com",
                "amazon": "https://amazon.com",
                "wikipedia": "https://wikipedia.org",
                "stackoverflow": "https://stackoverflow.com",
                "chatgpt": "https://chat.openai.com",
                "claude": "https://claude.ai",
            }
            tl_clean = tl.strip().lower()
            if tl_clean in KNOWN_SITES:
                _launch(KNOWN_SITES[tl_clean])
                return {"ok": True, "message": f"Opened {KNOWN_SITES[tl_clean]}"}

            # 5. Looks like a domain
            if "." in target:
                url = target if target.startswith("http") else f"https://{target}"
                _launch(url)
                return {"ok": True, "message": f"Opened {url}"}

            # 6. Try as app name / executable
            _launch(target)
            return {"ok": True, "message": f"Launched {target}"}

        except Exception as e:
            # Last resort: try webbrowser
            try:
                webbrowser.open(f"https://{target}.com")
                return {"ok": True, "message": f"Opened https://{target}.com (fallback)"}
            except Exception:
                return {"ok": False, "message": str(e)}

    elif atype == "run_script":
        lang = action.get("lang", "python").lower()
        code = action.get("code", "")
        if not code.strip():
            return {"ok": False, "message": "No code provided"}
        try:
            ext = {
                "python": ".py", "py": ".py", "bash": ".sh", "shell": ".sh",
                "powershell": ".ps1", "batch": ".bat", "js": ".js", "javascript": ".js"
            }.get(lang, ".py")
            with tempfile.NamedTemporaryFile(mode="w", suffix=ext, delete=False, encoding="utf-8") as f:
                f.write(code)
                tmp = f.name
            if lang in ("python", "py"):
                proc = subprocess.run(["python", tmp], capture_output=True, text=True, timeout=30)
            elif lang in ("bash", "shell"):
                proc = subprocess.run(["bash", tmp], capture_output=True, text=True, timeout=30)
            elif lang == "powershell":
                proc = subprocess.run(["powershell", "-File", tmp], capture_output=True, text=True, timeout=30)
            else:
                proc = subprocess.run(["python", tmp], capture_output=True, text=True, timeout=30)
            try:
                os.unlink(tmp)
            except Exception:
                pass
            out = (proc.stdout or "") + (proc.stderr or "")
            return {
                "ok": proc.returncode == 0,
                "message": out.strip() or "Script executed — no output.",
                "returncode": proc.returncode,
            }
        except subprocess.TimeoutExpired:
            return {"ok": False, "message": "Script timed out (30s)"}
        except Exception as e:
            return {"ok": False, "message": str(e)}

    elif atype == "write_file":
        path_str = action.get("path", "").strip()
        content  = action.get("content", "")
        if not path_str:
            return {"ok": False, "message": "No path provided"}
        try:
            p = Path(path_str).expanduser()
            # Resolve relative paths to home directory
            if not p.is_absolute():
                p = Path.home() / p
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            return {"ok": True, "message": f"File written: {p} ({len(content)} chars)", "path": str(p)}
        except Exception as e:
            return {"ok": False, "message": str(e)}

    elif atype == "read_file":
        p = Path(target).expanduser()
        if not p.is_absolute():
            p = Path.home() / p
        try:
            if not p.exists():
                return {"ok": False, "message": f"Not found: {target}"}
            if p.stat().st_size > 5 * 1024 * 1024:
                return {"ok": False, "message": "File too large (>5MB)"}
            content = p.read_text(encoding="utf-8", errors="replace")
            return {"ok": True, "message": f"Read {len(content)} chars", "content": content[:8000]}
        except Exception as e:
            return {"ok": False, "message": str(e)}

    elif atype == "send_socials":
        soc = {k: v for k, v in settings.get("socials", {}).items() if v and v.strip()}
        if not soc:
            return {"ok": False, "message": "No socials configured"}
        return {"ok": True, "message": "\n".join(f"{k}: {v}" for k, v in soc.items()), "display": True}

    elif atype == "search":
        q = action.get("query", target)
        url = f"https://www.google.com/search?q={q.replace(' ', '+')}"
        webbrowser.open(url)
        return {"ok": True, "message": f"Searched: {q}"}

    elif atype == "list_files":
        path_str = action.get("path", "~").strip()
        p = Path(path_str).expanduser()
        try:
            if not p.exists():
                return {"ok": False, "message": f"Path not found: {path_str}"}
            if p.is_file():
                return {"ok": True, "message": f"{p} is a file", "files": [str(p)]}
            files = [str(f.relative_to(p)) for f in sorted(p.iterdir())[:100]]
            return {"ok": True, "message": f"{len(files)} items in {p}", "files": files}
        except Exception as e:
            return {"ok": False, "message": str(e)}

    return {"ok": False, "message": "Unknown action"}

# ── Screenshot ─────────────────────────────────────────────────────────────
def take_screenshot() -> Optional[str]:
    try:
        import mss
        with mss.mss() as sct:
            mon = sct.monitors[1]
            img = sct.grab(mon)
            try:
                from PIL import Image
                pil = Image.frombytes("RGB", img.size, img.bgra, "raw", "BGRX")
                if pil.width > 1280:
                    r = 1280 / pil.width
                    pil = pil.resize((1280, int(pil.height * r)))
                buf = io.BytesIO()
                pil.save(buf, "PNG", optimize=True)
                return base64.b64encode(buf.getvalue()).decode()
            except ImportError:
                raw = mss.tools.to_png(img.rgb, img.size)
                return base64.b64encode(raw).decode()
    except Exception:
        pass
    try:
        import pyautogui
        from PIL import Image
        img = pyautogui.screenshot()
        buf = io.BytesIO()
        img.save(buf, "PNG", optimize=True)
        return base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return None

async def is_screen_request(text: str) -> bool:
    kw = ("screen", "écran", "mon écran", "regarde", "capture", "screenshot", "display", "bureau", "fenêtre")
    return any(k in text.lower() for k in kw)

async def call_vision(api_key: str, img_b64: str, msg: str, sys_prompt: str) -> str:
    last_err = "No vision model available"
    for vision_model in VISION_MODELS:
        try:
            async with httpx.AsyncClient(timeout=45) as client:
                r = await client.post(
                    OPENROUTER_URL,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                        "HTTP-Referer": "https://kyrox.nemea.uk",
                        "X-Title": "Kyrox AI",
                    },
                    json={
                        "model": vision_model,
                        "messages": [
                            {"role": "system", "content": sys_prompt},
                            {"role": "user", "content": [
                                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}},
                                {"type": "text", "text": msg or "Describe my screen in detail."}
                            ]}
                        ],
                        "max_tokens": 1024,
                    }
                )
            if r.status_code == 200:
                data = r.json()
                content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                if content:
                    return content
                last_err = f"{vision_model}: empty response"
                continue
            elif r.status_code in (404, 400, 422):
                last_err = f"{vision_model}: HTTP {r.status_code}"
                continue
            elif r.status_code == 429:
                last_err = f"{vision_model}: rate limited"
                continue
            else:
                last_err = f"{vision_model}: HTTP {r.status_code}"
                continue
        except Exception as e:
            last_err = f"{vision_model}: {e}"
            continue
    return f"⚠ Vision unavailable — {last_err}"

# ── Auto-memory extraction ─────────────────────────────────────────────────
MEMORY_PATTERNS = [
    (r"(?:my name is|i'm called|call me|je m'appelle|mon nom est)\s+(\w+)", "User's name is {}"),
    (r"i(?:'m| am)\s+(\d+)\s*(?:years?\s*old|ans?)", "User is {} years old"),
    (r"i\s+(?:love|like|enjoy|adore|j'aime)\s+([^,.!?\n]{3,40})", "User likes: {}"),
    (r"i\s+(?:hate|dislike|déteste)\s+([^,.!?\n]{3,40})", "User dislikes: {}"),
    (r"i\s+(?:live|am)\s+in\s+([^,.!?\n]{3,40})", "User lives in {}"),
    (r"i(?:'m| am)\s+(?:a\s+)?(?:developer|programmer|designer|student|engineer|gamer|streamer|artist)", "User is a {}"),
    (r"my\s+(?:favorite|fav)\s+\w+\s+is\s+([^,.!?\n]{2,30})", "User's favorite: {}"),
    (r"j(?:e suis|'suis)\s+([^,.!?\n]{3,40})", "L'utilisateur est: {}"),
    (r"(?:j'habite|je vis)\s+à?\s+([^,.!?\n]{3,40})", "L'utilisateur habite: {}"),
]

def extract_facts(text: str) -> list[str]:
    facts = []
    for pat, tmpl in MEMORY_PATTERNS:
        m = re.search(pat, text.lower())
        if m:
            val = m.group(1).strip().title() if m.lastindex else m.group(0).strip()
            facts.append(tmpl.format(val))
    return facts

# ── FastAPI app ────────────────────────────────────────────────────────────
app = FastAPI(title="Kyrox AI")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# ── REST endpoints ─────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def index():
    return HTMLResponse((TEMPLATES_DIR / "index.html").read_text(encoding="utf-8"))

@app.get("/api/settings")
async def get_settings():
    s = load_settings()
    s["free_models"]   = FREE_MODELS
    s["current_model"] = FREE_MODELS[s.get("current_model_index", 0) % len(FREE_MODELS)]
    return s

class SettingsIn(BaseModel):
    backend:            Optional[str]  = None
    openrouter_key:     Optional[str]  = None
    ollama_url:         Optional[str]  = None
    ollama_model:       Optional[str]  = None
    system_prompt:      Optional[str]  = None
    wakeword:           Optional[str]  = None
    tts:                Optional[bool] = None
    tts_voice:          Optional[str]  = None
    socials:            Optional[dict] = None
    apps:               Optional[dict] = None
    context_files:      Optional[list] = None
    auto_scan_home:     Optional[bool] = None

@app.post("/api/settings")
async def post_settings(body: SettingsIn):
    s = load_settings()
    update = body.model_dump(exclude_none=True)
    for k, v in update.items():
        if k in ("socials", "apps") and isinstance(v, dict):
            s[k] = {**s.get(k, {}), **v}
        else:
            s[k] = v
    if "context_files" in update:
        s["context_text"] = scan_context_files(s.get("context_files", []))
    save_settings(s)
    return {"ok": True, "settings": s}

@app.post("/api/action")
async def run_action(req: Request):
    body = await req.json()
    s = load_settings()
    return execute_pc_action(body.get("action", {}), s)

@app.get("/api/users")
async def get_users():
    return list_users()

@app.get("/api/history/{uid}")
async def get_history(uid: str):
    return load_history(uid)

@app.delete("/api/history/{uid}")
async def del_history(uid: str):
    save_history(uid, [])
    return {"ok": True}

@app.get("/api/memory/{uid}")
async def get_memory(uid: str):
    return load_memory(uid)

@app.post("/api/memory/{uid}")
async def post_memory(uid: str, req: Request):
    body = await req.json()
    m = load_memory(uid)
    if "facts"       in body: m["facts"]       = body["facts"]
    if "preferences" in body: m["preferences"] = {**m.get("preferences", {}), **body["preferences"]}
    save_memory(uid, m)
    return {"ok": True, "memory": m}

@app.get("/api/status")
async def get_status():
    s = load_settings()
    if s.get("backend") == "ollama":
        try:
            async with httpx.AsyncClient(timeout=3) as c:
                await c.get(f"{s['ollama_url']}/api/tags")
            return {"ok": True, "backend": "ollama", "model": s.get("ollama_model")}
        except:
            return {"ok": False, "backend": "ollama", "error": "Ollama offline"}
    has_key = bool(s.get("openrouter_key", "").strip())
    idx = s.get("current_model_index", 0)
    return {"ok": has_key, "backend": "openrouter",
            "model": FREE_MODELS[idx % len(FREE_MODELS)], "has_key": has_key}

@app.post("/api/scan-context")
async def scan_context(req: Request):
    body = await req.json()
    paths = body.get("paths", [])
    text = scan_context_files(paths)
    s = load_settings()
    s["context_files"] = paths
    s["context_text"]  = text
    save_settings(s)
    return {"ok": True, "chars": len(text), "preview": text[:200]}

@app.get("/api/voices")
async def get_voices():
    """Return list of available system TTS voices."""
    os_name = platform.system()
    voices = []
    try:
        if os_name == "Windows":
            result = subprocess.run(
                ["powershell", "-Command",
                 "Add-Type -AssemblyName System.Speech; "
                 "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                 "$s.GetInstalledVoices() | ForEach-Object { $_.VoiceInfo.Name }"],
                capture_output=True, text=True, timeout=10
            )
            for line in result.stdout.strip().splitlines():
                name = line.strip()
                if name:
                    voices.append({"id": name, "name": name, "lang": "en"})
        elif os_name == "Darwin":
            result = subprocess.run(["say", "-v", "?"], capture_output=True, text=True)
            for line in result.stdout.splitlines():
                parts = line.split()
                if parts:
                    voices.append({"id": parts[0], "name": parts[0], "lang": parts[1] if len(parts) > 1 else ""})
        elif os_name == "Linux":
            try:
                result = subprocess.run(["espeak", "--voices"], capture_output=True, text=True, timeout=5)
                for line in result.stdout.splitlines()[1:]:
                    parts = line.split()
                    if len(parts) >= 4:
                        voices.append({"id": parts[3], "name": parts[3], "lang": parts[1]})
            except Exception:
                pass
    except Exception:
        pass
    return {"voices": voices}

@app.get("/api/news")
async def get_news():
    """Fetch top headlines via RSS (no API key needed)."""
    feeds = [
        ("Google News FR", "https://news.google.com/rss?hl=fr&gl=FR&ceid=FR:fr"),
        ("BBC World", "https://feeds.bbci.co.uk/news/world/rss.xml"),
        ("Le Monde", "https://www.lemonde.fr/rss/une.xml"),
    ]
    articles = []
    async with httpx.AsyncClient(timeout=10) as client:
        for source, url in feeds:
            try:
                r = await client.get(url, headers={"User-Agent": "Kyrox/1.0"})
                if r.status_code != 200:
                    continue
                items = re.findall(r"<item>(.*?)</item>", r.text, re.DOTALL)
                for item in items[:5]:
                    title = re.search(r"<title><!\[CDATA\[(.*?)\]\]></title>|<title>(.*?)</title>", item)
                    link  = re.search(r"<link>(.*?)</link>|<guid[^>]*>(https?://[^<]+)</guid>", item)
                    pub   = re.search(r"<pubDate>(.*?)</pubDate>", item)
                    if title:
                        t = (title.group(1) or title.group(2) or "").strip()
                        l = (link.group(1) or (link.group(2) if link else "") or "").strip() if link else ""
                        p = pub.group(1).strip() if pub else ""
                        if t:
                            articles.append({"title": t, "link": l, "pub": p, "source": source})
            except Exception:
                continue
    return {"articles": articles[:20]}

# ── WebSocket chat ─────────────────────────────────────────────────────────
@app.websocket("/ws/chat/{uid}")
async def chat_ws(ws: WebSocket, uid: str):
    await ws.accept()

    history  = load_history(uid)
    settings = load_settings()

    # Auto-scan user profile files on connect
    profile_text = auto_scan_user_profile()
    if profile_text:
        await ws.send_text(json.dumps({"type": "profile_scanned", "chars": len(profile_text)}))

    idx = settings.get("current_model_index", 0)
    await ws.send_text(json.dumps({"type": "model_info", "model": FREE_MODELS[idx % len(FREE_MODELS)]}))

    try:
        while True:
            raw      = await ws.receive_text()
            payload  = json.loads(raw)
            action   = payload.get("action", "chat")
            settings = load_settings()
            memory   = load_memory(uid)

            # ── Control actions ──────────────────────────────────────────
            if action == "clear":
                history = []
                save_history(uid, history)
                await ws.send_text(json.dumps({"type": "cleared"}))
                continue

            if action == "learn":
                fact = payload.get("fact", "").strip()
                if fact and fact not in memory.get("facts", []):
                    memory.setdefault("facts", []).append(fact)
                    save_memory(uid, memory)
                await ws.send_text(json.dumps({"type": "learned"}))
                continue

            # ── Chat ─────────────────────────────────────────────────────
            user_msg = payload.get("message", "").strip()
            if not user_msg:
                continue

            new_facts = extract_facts(user_msg)
            changed = False
            for f in new_facts:
                if f not in memory.get("facts", []):
                    memory.setdefault("facts", []).append(f)
                    changed = True
            if changed:
                save_memory(uid, memory)
                await ws.send_text(json.dumps({"type": "learned"}))

            history.append({"role": "user", "content": user_msg})

            mem_ctx  = memory_summary(memory)
            ctx_text = settings.get("context_text", "")
            sys_prompt = settings["system_prompt"]

            # Inject profile scan
            if profile_text:
                sys_prompt = f"[USER PROFILE — fichiers détectés sur son PC]:\n{profile_text}\n\n" + sys_prompt

            if ctx_text:
                sys_prompt = f"[CONTEXT FILES — projets/PC de l'utilisateur]:\n{ctx_text}\n\n" + sys_prompt
            if mem_ctx:
                sys_prompt = mem_ctx + "\n\n" + sys_prompt

            # Inject relevant skills based on message
            skills = get_relevant_skills(user_msg)
            if skills:
                sys_prompt = sys_prompt + "\n\n" + skills

            # ── Vision shortcut ──────────────────────────────────────────
            api_key = settings.get("openrouter_key", "").strip()
            if (api_key and settings.get("backend", "openrouter") == "openrouter"
                    and await is_screen_request(user_msg)):
                await ws.send_text(json.dumps({"type": "token", "content": "📸 Capture en cours…\n\n"}))
                img = take_screenshot()
                if img is None:
                    err = "⚠ Impossible de capturer l'écran. Installe: pip install mss pillow"
                    await ws.send_text(json.dumps({"type": "done", "content": err}))
                    history.append({"role": "assistant", "content": err})
                    save_history(uid, history)
                    continue
                await ws.send_text(json.dumps({"type": "model_info", "model": "vision"}))
                resp = await call_vision(api_key, img, user_msg, sys_prompt)
                history.append({"role": "assistant", "content": resp})
                save_history(uid, history)
                await ws.send_text(json.dumps({"type": "done", "content": resp}))
                continue

            # ── LLM call ─────────────────────────────────────────────────
            messages = [{"role": "system", "content": sys_prompt}] + history[-24:]
            full_response = ""
            success = False

            if settings.get("backend", "openrouter") == "openrouter":
                if not api_key:
                    await ws.send_text(json.dumps({"type": "error", "content": "no_api_key"}))
                    history.pop()
                    continue

                idx   = settings.get("current_model_index", 0)
                tried = 0
                while tried < len(FREE_MODELS):
                    model = FREE_MODELS[idx % len(FREE_MODELS)]
                    await ws.send_text(json.dumps({"type": "model_info", "model": model}))
                    try:
                        async with httpx.AsyncClient(timeout=90) as client:
                            async with client.stream(
                                "POST", OPENROUTER_URL,
                                headers={"Authorization": f"Bearer {api_key}",
                                         "Content-Type": "application/json",
                                         "HTTP-Referer": "https://kyrox.nemea.uk",
                                         "X-Title": "Kyrox AI"},
                                json={"model": model, "messages": messages, "stream": True},
                            ) as resp:
                                if resp.status_code == 429:
                                    await ws.send_text(json.dumps({"type": "model_switch", "from": model}))
                                    idx = (idx + 1) % len(FREE_MODELS); tried += 1; continue
                                if resp.status_code != 200:
                                    idx = (idx + 1) % len(FREE_MODELS); tried += 1; continue
                                async for line in resp.aiter_lines():
                                    if not line or not line.startswith("data:"): continue
                                    raw2 = line[5:].strip()
                                    if raw2 == "[DONE]": break
                                    try:
                                        chunk = json.loads(raw2)
                                    except:
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
                        idx = (idx + 1) % len(FREE_MODELS); tried += 1

                if not success:
                    await ws.send_text(json.dumps({"type": "error", "content": "Tous les modèles sont rate-limited. Réessaie dans un moment."}))
                    history.pop()
                    continue

            else:  # Ollama
                try:
                    async with httpx.AsyncClient(timeout=120) as client:
                        async with client.stream(
                            "POST", f"{settings['ollama_url']}/api/chat",
                            json={"model": settings["ollama_model"], "messages": messages, "stream": True},
                        ) as resp:
                            async for line in resp.aiter_lines():
                                if not line: continue
                                try:
                                    chunk = json.loads(line)
                                except:
                                    continue
                                token = chunk.get("message", {}).get("content", "")
                                full_response += token
                                if token:
                                    await ws.send_text(json.dumps({"type": "token", "content": token}))
                    success = True
                except Exception as e:
                    await ws.send_text(json.dumps({"type": "error", "content": f"Ollama error: {e}"}))
                    history.pop()
                    continue

            # Strip <think> blocks
            clean = re.sub(r"<think>.*?</think>", "", full_response, flags=re.DOTALL).strip()

            # Parse action blocks
            action_pattern = re.compile(r"```action\s*(.*?)\s*```", re.DOTALL)
            actions_found  = []
            for m2 in action_pattern.finditer(clean):
                try:
                    actions_found.append(json.loads(m2.group(1)))
                except:
                    pass
            display = action_pattern.sub("", clean).strip()

            # Handle read_file inline
            for act in list(actions_found):
                if act.get("type") == "read_file":
                    res = execute_pc_action(act, settings)
                    await ws.send_text(json.dumps({"type": "actions", "actions": [act], "results": {act.get("type"): res}}))
                    if res.get("ok") and res.get("content"):
                        history.append({"role": "assistant", "content": display})
                        history.append({"role": "user", "content": f"[File: {act.get('path')}]\n{res['content']}"})
                    save_history(uid, history)
                    await ws.send_text(json.dumps({"type": "done", "content": display}))
                    actions_found = [a for a in actions_found if a.get("type") != "read_file"]
                    break
            else:
                history.append({"role": "assistant", "content": display})
                save_history(uid, history)

                if actions_found:
                    results = {}
                    for act in actions_found:
                        if act.get("type") != "send_socials":
                            res = execute_pc_action(act, settings)
                            results[act.get("type", "")] = res
                    await ws.send_text(json.dumps({"type": "actions", "actions": actions_found, "results": results}))

                await ws.send_text(json.dumps({"type": "done", "content": display}))

    except WebSocketDisconnect:
        pass

# ── Startup info endpoint ─────────────────────────────────────────────────
@app.get("/api/startup-info")
async def startup_info():
    """Return instructions to auto-launch Kyrox at startup."""
    os_name = platform.system()
    script_path = str(Path(__file__).resolve())
    python_path = "python"  # assume python is on PATH

    if os_name == "Windows":
        # Create a .bat file in Startup folder
        startup_folder = Path.home() / "AppData/Roaming/Microsoft/Windows/Start Menu/Programs/Startup"
        bat_path = startup_folder / "kyrox.bat"
        bat_content = f'@echo off\nstart "" /B {python_path} -m uvicorn main:app --host 127.0.0.1 --port 8000 --app-dir "{Path(script_path).parent}"'
        instructions = (
            f"To auto-start Kyrox on Windows login:\n"
            f"1. Create file: {bat_path}\n"
            f"   Content:\n{bat_content}\n\n"
            f"Or run this command (as admin) to install it automatically:"
        )
        auto_cmd = f'echo {bat_content} > "{bat_path}"'
    elif os_name == "Darwin":
        plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>uk.nemea.kyrox</string>
  <key>ProgramArguments</key><array>
    <string>{python_path}</string><string>-m</string><string>uvicorn</string>
    <string>main:app</string><string>--host</string><string>127.0.0.1</string>
    <string>--port</string><string>8000</string>
    <string>--app-dir</string><string>{Path(script_path).parent}</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
</dict></plist>"""
        plist_path = Path.home() / "Library/LaunchAgents/uk.nemea.kyrox.plist"
        instructions = f"Save this plist to:\n{plist_path}\nThen run: launchctl load {plist_path}"
        auto_cmd = f"echo '{plist}' > {plist_path} && launchctl load {plist_path}"
    else:
        service = f"""[Unit]
Description=Kyrox AI
After=network.target

[Service]
ExecStart={python_path} -m uvicorn main:app --host 127.0.0.1 --port 8000 --app-dir {Path(script_path).parent}
Restart=always

[Install]
WantedBy=default.target"""
        instructions = "Create a systemd user service or add to .bashrc / .profile"
        auto_cmd = f"echo '{service}' > ~/.config/systemd/user/kyrox.service && systemctl --user enable kyrox && systemctl --user start kyrox"

    return {"os": os_name, "instructions": instructions, "auto_cmd": auto_cmd, "script": script_path}
