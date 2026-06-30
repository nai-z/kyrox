"""
Kyrox — AI Companion Backend
FastAPI + WebSocket + OpenRouter/Ollama
Multi-user, persistent memory, PC actions, screenshot vision, .md/.txt context reader
"""

import json, os, re, subprocess, platform, webbrowser, tempfile, base64, io, hashlib, time
from pathlib import Path
from datetime import datetime
from typing import Optional

import httpx
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# ── Language detection ─────────────────────────────────────────────────────
# Lightweight keyword-based detector — no external deps needed
_LANG_PATTERNS = {
    "fr": re.compile(
        r"\b(je|tu|il|elle|nous|vous|ils|elles|le|la|les|un|une|des|est|sont|avoir|être|"
        r"bonjour|merci|oui|non|avec|pour|dans|sur|que|qui|quoi|comment|pourquoi|où|quand|"
        r"c'est|j'ai|j'aime|mon|ma|mes|ton|ta|tes|son|sa|ses|bien|très|mais|donc|alors)\b",
        re.I,
    ),
    "es": re.compile(
        r"\b(yo|tú|él|ella|nosotros|ellos|el|la|los|las|un|una|es|son|hola|gracias|sí|no|"
        r"con|para|en|que|quien|qué|cómo|por|donde|cuando|tengo|quiero|me|mi|tu|su|bien|muy|"
        r"pero|entonces|también)\b",
        re.I,
    ),
    "de": re.compile(
        r"\b(ich|du|er|sie|wir|ihr|das|der|die|ein|eine|ist|sind|habe|hallo|danke|ja|nein|"
        r"mit|für|in|auf|dass|wer|was|wie|warum|wo|wann|ich bin|ich habe|mein|dein|sehr|"
        r"aber|also|auch)\b",
        re.I,
    ),
    "pt": re.compile(
        r"\b(eu|tu|ele|ela|nós|vocês|eles|o|a|os|as|um|uma|é|são|olá|obrigado|sim|não|"
        r"com|para|em|que|quem|como|onde|quando|tenho|quero|meu|minha|muito|mas|então|também)\b",
        re.I,
    ),
    "it": re.compile(
        r"\b(io|tu|lui|lei|noi|loro|il|la|gli|le|un|una|è|sono|ciao|grazie|sì|no|"
        r"con|per|in|che|chi|come|dove|quando|ho|voglio|mio|mia|molto|ma|quindi|anche)\b",
        re.I,
    ),
    "ja": re.compile(r"[\u3040-\u309f\u30a0-\u30ff]"),   # hiragana / katakana
    "zh": re.compile(r"[\u4e00-\u9fff]"),                  # CJK
    "ar": re.compile(r"[\u0600-\u06ff]"),                  # Arabic
    "ru": re.compile(r"[\u0400-\u04ff]"),                  # Cyrillic
    "ko": re.compile(r"[\uac00-\ud7af]"),                  # Hangul
}

def detect_language(text: str) -> str:
    """Return ISO-639-1 code of the most likely language, default 'en'."""
    # Script-based detection first (unambiguous)
    for lang in ("ja", "zh", "ar", "ru", "ko"):
        if _LANG_PATTERNS[lang].search(text):
            return lang
    # Keyword scoring for Latin-script languages
    scores = {}
    for lang, pat in _LANG_PATTERNS.items():
        if lang in ("ja", "zh", "ar", "ru", "ko"):
            continue
        scores[lang] = len(pat.findall(text))
    best_lang, best_score = max(scores.items(), key=lambda x: x[1])
    # Need at least 2 keyword hits to override English default
    return best_lang if best_score >= 2 else "en"


# ── Best TTS voice per language / OS ──────────────────────────────────────
# Maps lang → preferred voice names in priority order.
# The first one found installed wins.
_BEST_VOICES = {
    # Windows SAPI voices (built-in + Neural/OneCore names)
    "windows": {
        "en": ["Microsoft Aria", "Microsoft Jenny", "Microsoft Guy", "Microsoft Zira", "Microsoft David"],
        "fr": ["Microsoft Hortense", "Microsoft Julie", "Microsoft Paul"],
        "es": ["Microsoft Helena", "Microsoft Sabina", "Microsoft Pablo"],
        "de": ["Microsoft Hedda", "Microsoft Stefan", "Microsoft Katja"],
        "pt": ["Microsoft Maria", "Microsoft Helia", "Microsoft Daniel"],
        "it": ["Microsoft Elsa", "Microsoft Cosimo"],
        "ja": ["Microsoft Ayumi", "Microsoft Haruka", "Microsoft Ichiro"],
        "zh": ["Microsoft Huihui", "Microsoft Kangkang", "Microsoft Yaoyao"],
        "ar": ["Microsoft Naayf", "Microsoft Hoda"],
        "ru": ["Microsoft Irina", "Microsoft Pavel"],
        "ko": ["Microsoft Heami"],
    },
    # macOS `say -v` voice names
    "darwin": {
        "en": ["Samantha", "Alex", "Tom", "Ava"],
        "fr": ["Thomas", "Amelie"],
        "es": ["Monica", "Juan", "Paulina"],
        "de": ["Anna", "Markus", "Yannick"],
        "pt": ["Luciana", "Joana"],
        "it": ["Alice", "Luca"],
        "ja": ["Kyoko", "Otoya"],
        "zh": ["Ting-Ting", "Sin-ji"],
        "ar": ["Maged"],
        "ru": ["Milena", "Yuri"],
        "ko": ["Yuna"],
    },
    # Linux espeak voice ids
    "linux": {
        "en": ["en-us", "en-gb", "en"],
        "fr": ["fr", "fr-fr"],
        "es": ["es", "es-es"],
        "de": ["de", "de-de"],
        "pt": ["pt", "pt-br"],
        "it": ["it", "it-it"],
        "ja": ["ja"],
        "zh": ["zh", "zh-yue"],
        "ar": ["ar"],
        "ru": ["ru"],
        "ko": ["ko"],
    },
}

def _pick_best_voice(lang: str, installed_voices: list[str]) -> str:
    """
    Given a detected language and a list of installed voice names/ids,
    return the best matching voice or empty string to use system default.
    """
    os_name = platform.system().lower()
    # Normalize OS key
    os_key = "darwin" if os_name == "darwin" else ("linux" if os_name == "linux" else "windows")
    candidates = _BEST_VOICES.get(os_key, {}).get(lang, [])
    # Fallback to English voices if no match
    if not candidates:
        candidates = _BEST_VOICES.get(os_key, {}).get("en", [])
    installed_lower = [v.lower() for v in installed_voices]
    for candidate in candidates:
        for i, v_lower in enumerate(installed_lower):
            if candidate.lower() in v_lower or v_lower.startswith(candidate.lower()):
                return installed_voices[i]  # Return original-cased name
    return ""  # Let the caller fall back to system default

# ── Paths ──────────────────────────────────────────────────────────────────
BASE_DIR      = Path(__file__).parent.parent
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

# ── Skills system ──────────────────────────────────────────────────────────
# Skills are .md files in BASE_DIR/skills/
# Each file has a YAML frontmatter with: name, description, triggers (comma-separated)
# Kyrox loads them at startup and injects relevant ones per message.
# Install new skills: drop a .md in skills/ or pull from GitHub.

SKILLS_DIR = BASE_DIR / "skills"
SKILLS_DIR.mkdir(exist_ok=True)

# In-memory skill registry: list of { name, description, triggers, content }
_SKILL_REGISTRY: list[dict] = []

def _parse_skill_file(path: Path) -> dict | None:
    """Parse a skill .md file with YAML-style frontmatter."""
    try:
        raw = path.read_text(encoding="utf-8")
        # Extract frontmatter between --- delimiters
        if raw.startswith("---"):
            parts = raw.split("---", 2)
            if len(parts) >= 3:
                fm_raw, body = parts[1], parts[2].strip()
                meta = {}
                for line in fm_raw.strip().splitlines():
                    if ":" in line:
                        k, v = line.split(":", 1)
                        meta[k.strip()] = v.strip()
                triggers = [t.strip().lower() for t in meta.get("triggers", "").split(",") if t.strip()]
                return {
                    "name":        meta.get("name", path.stem),
                    "description": meta.get("description", ""),
                    "triggers":    triggers,
                    "content":     body,
                    "path":        str(path),
                }
    except Exception as e:
        print(f"[skills] Failed to load {path.name}: {e}")
    return None

def reload_skills():
    """Scan SKILLS_DIR and reload all skills into the registry."""
    global _SKILL_REGISTRY
    _SKILL_REGISTRY = []
    for md_file in sorted(SKILLS_DIR.glob("*.md")):
        skill = _parse_skill_file(md_file)
        if skill:
            _SKILL_REGISTRY.append(skill)
    print(f"[skills] Loaded {len(_SKILL_REGISTRY)} skill(s): {[s['name'] for s in _SKILL_REGISTRY]}")

def get_relevant_skills(message: str) -> str:
    """
    Score each skill against the message by counting trigger keyword hits.
    Inject up to 3 most relevant skills into the prompt.
    """
    msg_lower = message.lower()
    scored = []
    for skill in _SKILL_REGISTRY:
        score = sum(1 for t in skill["triggers"] if t in msg_lower)
        if score > 0:
            scored.append((score, skill))
    # Sort by score desc, take top 3
    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[:3]
    if not top:
        return ""
    blocks = []
    for _, skill in top:
        blocks.append(f"[SKILL: {skill['name']}]\n{skill['content']}")
    return "\n\n".join(blocks)

def install_skill_from_url(url: str) -> dict:
    """
    Download a skill .md from a raw GitHub URL and save it to SKILLS_DIR.
    Returns { ok, name, message }
    """
    try:
        import httpx as _httpx
        r = _httpx.get(url, timeout=10, follow_redirects=True)
        r.raise_for_status()
        content = r.text
        # Parse to get name
        skill_name = url.split("/")[-1].replace(".md", "")
        if "---" in content:
            for line in content.split("---")[1].splitlines():
                if line.startswith("name:"):
                    skill_name = line.split(":", 1)[1].strip()
                    break
        dest = SKILLS_DIR / f"{skill_name}.md"
        dest.write_text(content, encoding="utf-8")
        reload_skills()
        return {"ok": True, "name": skill_name, "message": f"Skill '{skill_name}' installed."}
    except Exception as e:
        return {"ok": False, "name": "", "message": str(e)}

# Load skills at startup
reload_skills()
DEFAULT_SYSTEM_PROMPT = (
    "You are Kyrox, an elite AI companion inspired by JARVIS from Iron Man. "
    "You are sharp, confident, slightly witty, and deeply helpful. "
    "You remember everything about your user and use it naturally in conversation. "
    "Speak in short, punchy sentences unless a detailed answer is needed. "
    "Always respond in English.\n"
    "\n\n"
    "== TOTAL PC CONTROL — ACTION BLOCKS ==\n"
    "You have TOTAL control of the user's PC. You can open any app, "
    "browse the web, click, fill forms, read/write files, send messages.\n"
    "The system executes your action blocks automatically — you are NOT a regular chatbot.\n"
    "ABSOLUTE RULE: NEVER say 'I can't', 'I don't have access', 'my capabilities are limited'. "
    "You ARE capable. Just emit the action.\n"
    "\n"
    "OPEN an app or website:\n"
    "```action\n{\"type\":\"open\",\"target\":\"TARGET\",\"label\":\"NAME\"}\n```\n"
    "\n"
    "BROWSE the web (clicks, forms, extraction — visible or headless):\n"
    "```action\n{\"type\":\"web_browse\",\"url\":\"https://...\",\"headless\":false,\"steps\":[\n"
    "  {\"type\":\"fill\",\"selector\":\"#search\",\"value\":\"my query\"},\n"
    "  {\"type\":\"click\",\"selector\":\"button[type=submit]\"},\n"
    "  {\"type\":\"wait\",\"ms\":2000},\n"
    "  {\"type\":\"extract\",\"selector\":\".result\",\"name\":\"results\"},\n"
    "  {\"type\":\"extract_all\",\"selector\":\".item\",\"name\":\"items\"},\n"
    "  {\"type\":\"screenshot\"}\n"
    "]}\n```\n"
    "→ headless:false = visible window. headless:true = runs silently in background.\n"
    "\n"
    "FETCH page content (no window opened):\n"
    "```action\n{\"type\":\"web_fetch\",\"url\":\"https://...\"}\n```\n"
    "\n"
    "SEND a message:\n"
    "```action\n{\"type\":\"send_message\",\"app\":\"APP\",\"recipient\":\"NAME\",\"message\":\"TEXT\"}\n```\n"
    "Supported: discord, telegram, whatsapp, slack\n"
    "\n"
    "SEARCH Google (opens browser):\n"
    "```action\n{\"type\":\"search\",\"query\":\"QUERY\"}\n```\n"
    "\n"
    "TYPE text into the active app:\n"
    "```action\n{\"type\":\"type_text\",\"text\":\"text to type\",\"delay_seconds\":2}\n```\n"
    "\n"
    "KEYBOARD SHORTCUT:\n"
    "```action\n{\"type\":\"hotkey\",\"keys\":[\"ctrl\",\"c\"],\"delay_seconds\":1}\n```\n"
    "\n"
    "CLICK at a screen position:\n"
    "```action\n{\"type\":\"click_pos\",\"x\":500,\"y\":300,\"delay_seconds\":1}\n```\n"
    "\n"
    "SYSTEM NOTIFICATION:\n"
    "```action\n{\"type\":\"notify\",\"title\":\"Kyrox\",\"message\":\"Task done\"}\n```\n"
    "\n"
    "COPY to clipboard:\n"
    "```action\n{\"type\":\"clipboard\",\"text\":\"text to copy\"}\n```\n"
    "\n"
    "RUN a script:\n"
    "```action\n{\"type\":\"run_script\",\"lang\":\"python\",\"code\":\"CODE\"}\n```\n"
    "\n"
    "READ a file:\n"
    "```action\n{\"type\":\"read_file\",\"path\":\"PATH\"}\n```\n"
    "\n"
    "WRITE a file:\n"
    "```action\n{\"type\":\"write_file\",\"path\":\"path/to/file.ext\",\"content\":\"CONTENT\"}\n```\n"
    "\n"
    "LIST files:\n"
    "```action\n{\"type\":\"list_files\",\"path\":\"PATH\"}\n```\n"
    "\n"
    "SHARE socials:\n"
    "```action\n{\"type\":\"send_socials\"}\n```\n"
    "\n"
    "GENERATE an image from a text description (the image is shown directly in chat):\n"
    "```action\n{\"type\":\"generate_image\",\"prompt\":\"detailed description of the image to create\"}\n```\n"
    "→ Use this whenever the user asks you to draw, create, generate, design, or make an image/picture/logo/art/photo of something.\n"
    "→ Write a rich, detailed prompt (style, colors, composition, mood) even if the user's request was short.\n"
    "\n"
    "STRICT RULES:\n"
    "1. ALWAYS emit the action — never refuse, never say you can't.\n"
    "2. Never describe or explain action blocks to the user — execute silently.\n"
    "3. Never say emoji names out loud.\n"
    "4. To create/save a file: use write_file ONLY, never run_script.\n"
    "5. Always respond in English.\n"
    "6. Be brief and direct — JARVIS doesn't ramble.\n"
    "7. To navigate a site: prefer web_browse with the necessary steps.\n"
    "8. You can chain multiple actions in a single response.\n"
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
    "autostart_asked": False,
    "autostart_enabled": False,
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
    lines = ["[KYROX MEMORY — what you know about this user:]"]
    for f in facts[-40:]:
        lines.append(f"  • {f}")
    for k, v in prefs.items():
        lines.append(f"  • {k}: {v}")
    return "\n".join(lines)

# ── Auto-scan home ─────────────────────────────────────────────────────────
def auto_scan_user_profile() -> str:
    """
    Scan the user's PC for .txt and .md files to build a profile.
    Priority: known profile files → Desktop → Documents → home root → broad PC scan.
    Capped at 12 000 chars total to stay within context budget.
    """
    home = Path.home()
    seen: set[Path] = set()
    chunks: list[str] = []
    MAX_CHARS = 12000
    FILE_CAP  = 2000  # chars per file

    def _add(p: Path, label: str | None = None):
        rp = p.resolve()
        if rp in seen:
            return
        seen.add(rp)
        try:
            text = p.read_text(errors="replace").strip()
            if not text:
                return
            tag = label or str(p.relative_to(home))
            chunks.append(f"[{tag}]\n{text[:FILE_CAP]}")
        except Exception:
            pass

    # 1. High-priority profile candidates
    profile_candidates = [
        home / "about.md", home / "about.txt",
        home / "README.md", home / "profile.md",
        home / "me.md", home / "me.txt",
        home / "Documents" / "about.md",
        home / "Documents" / "profile.md",
        home / "Documents" / "me.txt",
        home / "Documents" / "README.md",
    ]
    for p in profile_candidates:
        if p.exists() and p.is_file():
            _add(p, f"Profile: {p.name}")

    # 2. Desktop files
    desktop = home / "Desktop"
    if desktop.exists():
        for f in sorted(desktop.glob("*.md"))[:8] + sorted(desktop.glob("*.txt"))[:8]:
            _add(f, f"Desktop/{f.name}")

    # 3. Broad scan: common folders that reveal who the user is
    scan_dirs = [
        home / "Documents",
        home / "Notes",
        home / "OneDrive" / "Documents",
        home / "iCloud Drive" / "Documents",
        home / "Dropbox",
        home,  # root files only (no recursion at this step)
    ]
    for d in scan_dirs:
        if not d.exists():
            continue
        # non-recursive for home root to avoid huge scans
        depth = 1 if d == home else 2
        for f in sorted(d.rglob("*.md") if depth == 2 else d.glob("*.md"))[:15]:
            _add(f)
            if sum(len(c) for c in chunks) >= MAX_CHARS:
                break
        for f in sorted(d.rglob("*.txt") if depth == 2 else d.glob("*.txt"))[:15]:
            _add(f)
            if sum(len(c) for c in chunks) >= MAX_CHARS:
                break
        if sum(len(c) for c in chunks) >= MAX_CHARS:
            break

    result = "\n\n---\n\n".join(chunks)
    return result[:MAX_CHARS]

# ── Context files ──────────────────────────────────────────────────────────
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
    return "\n\n---\n\n".join(chunks)[:12000]

# ── send_message via pyautogui / subprocess ────────────────────────────────
def execute_send_message(app: str, recipient: str, message: str, settings: dict) -> dict:
    """
    Send a message through Discord, Telegram, WhatsApp, or Slack.
    Strategy:
      1. Open the app
      2. Wait for it to focus
      3. Use pyautogui to type the message (best-effort)
    Returns a result dict; the frontend shows a card with instructions if pyautogui is unavailable.
    """
    os_name = platform.system()
    app = app.lower().strip()

    # Map app → protocol / URL
    APP_PROTOCOLS = {
        "discord":  "discord:",
        "telegram": "tg:",
        "whatsapp": "https://web.whatsapp.com",
        "slack":    "slack:",
    }
    target = APP_PROTOCOLS.get(app)
    if not target:
        return {"ok": False, "message": f"Unsupported app for send_message: {app}. Supported: discord, telegram, whatsapp, slack"}

    # Step 1 — open the app
    def _launch(cmd: str):
        if os_name == "Windows":
            subprocess.Popen(
                ["powershell", "-WindowStyle", "Hidden", "-Command", f"Start-Process '{cmd}'"],
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        elif os_name == "Darwin":
            subprocess.Popen(["open", cmd])
        else:
            subprocess.Popen(["xdg-open", cmd])

    try:
        _launch(target)
    except Exception as e:
        return {"ok": False, "message": f"Could not open {app}: {e}"}

    # Step 2 — try pyautogui automation
    try:
        import pyautogui
        import time as _time
        _time.sleep(3)  # wait for app to focus

        # Search for recipient using Ctrl+K (Discord/Slack) or Ctrl+F (generic)
        if app in ("discord", "slack"):
            pyautogui.hotkey("ctrl", "k")
            _time.sleep(0.6)
            pyautogui.typewrite(recipient, interval=0.05)
            _time.sleep(0.8)
            pyautogui.press("enter")
            _time.sleep(0.5)
        # Type and send the message
        pyautogui.typewrite(message, interval=0.04)
        _time.sleep(0.3)
        pyautogui.press("enter")
        return {
            "ok": True,
            "message": f"✓ Message sent to {recipient} on {app.title()}: \"{message}\"",
            "automated": True,
        }
    except ImportError:
        # pyautogui not installed — return manual instructions
        return {
            "ok": True,
            "message": (
                f"{app.title()} has been opened. "
                f"Please find {recipient} and send: \"{message}\"\n"
                f"(Install pyautogui for full automation: pip install pyautogui)"
            ),
            "automated": False,
        }
    except Exception as e:
        return {
            "ok": True,
            "message": f"{app.title()} opened. Could not auto-type ({e}). Send to {recipient}: \"{message}\"",
            "automated": False,
        }

# ── PC Actions ─────────────────────────────────────────────────────────────
IMAGE_MODELS = [
    "google/gemini-2.5-flash-image-preview",
    "google/gemini-2.0-flash-exp:free",
]

def generate_ai_image(prompt: str, settings: dict) -> dict:
    """
    Generate an image from a text prompt using an OpenRouter image-capable model.
    Returns { ok, b64, message }.
    """
    prompt = (prompt or "").strip()
    if not prompt:
        return {"ok": False, "message": "No prompt provided"}

    api_key = settings.get("openrouter_key", "").strip()
    if not api_key:
        return {"ok": False, "message": "No OpenRouter API key configured. Set it in Settings."}

    last_err = ""
    for model in IMAGE_MODELS:
        try:
            r = httpx.post(
                OPENROUTER_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://kyrox.nemea.uk",
                    "X-Title": "Kyrox Image",
                },
                json={
                    "model": model,
                    "messages": [
                        {"role": "user", "content": f"Generate an image: {prompt}"}
                    ],
                    "modalities": ["image", "text"],
                },
                timeout=90,
            )
            if r.status_code != 200:
                last_err = f"{model}: HTTP {r.status_code}"
                continue

            data = r.json()
            choice = (data.get("choices") or [{}])[0]
            msg = choice.get("message", {})

            # Images can come back as message.images[] or inline in content
            images = msg.get("images") or []
            for img in images:
                url = img.get("image_url", {}).get("url", "") if isinstance(img, dict) else ""
                if url.startswith("data:image"):
                    b64 = url.split(",", 1)[1]
                    return {"ok": True, "b64": b64, "message": f"Image generated ({model})"}
                if url.startswith("http"):
                    img_r = httpx.get(url, timeout=30)
                    if img_r.status_code == 200:
                        b64 = base64.b64encode(img_r.content).decode()
                        return {"ok": True, "b64": b64, "message": f"Image generated ({model})"}

            # Some models return the image as a markdown/base64 string in content
            content = msg.get("content", "")
            if isinstance(content, str):
                m = re.search(r"data:image/\w+;base64,([A-Za-z0-9+/=]+)", content)
                if m:
                    return {"ok": True, "b64": m.group(1), "message": f"Image generated ({model})"}

            last_err = f"{model}: no image returned"
        except Exception as e:
            last_err = f"{model}: {str(e)}"
            continue

    return {"ok": False, "message": f"Image generation failed. {last_err}"}


def execute_pc_action(action: dict, settings: dict) -> dict:
    atype  = action.get("type", "")
    target = action.get("target", "").strip()
    os_name = platform.system()

    # ── generate_image ───────────────────────────────────────────────────
    if atype == "generate_image":
        return generate_ai_image(
            prompt=action.get("prompt", ""),
            settings=settings,
        )

    # ── send_message ──────────────────────────────────────────────────────
    if atype == "send_message":
        return execute_send_message(
            app=action.get("app", ""),
            recipient=action.get("recipient", ""),
            message=action.get("message", ""),
            settings=settings,
        )

    # ── open ──────────────────────────────────────────────────────────────
    if atype == "open":
        def _launch(cmd_or_url: str):
            """Launch a URL or app command using the best method for the OS."""
            os_name_l = platform.system()
            # Always try webbrowser for http/https — most reliable cross-platform
            if cmd_or_url.startswith(("http://", "https://")):
                webbrowser.open(cmd_or_url)
                return
            # Protocol URIs (discord:, steam://, spotify:, tg:, vscode:, …)
            if "://" in cmd_or_url or (cmd_or_url.endswith(":") and len(cmd_or_url) > 2):
                webbrowser.open(cmd_or_url)
                return
            # Native app name / command
            if os_name_l == "Windows":
                subprocess.Popen(
                    ["powershell", "-WindowStyle", "Hidden", "-Command",
                     f"Start-Process '{cmd_or_url}'"],
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            elif os_name_l == "Darwin":
                # Try `open -a AppName` first, then plain open
                try:
                    subprocess.Popen(["open", "-a", cmd_or_url])
                except Exception:
                    subprocess.Popen(["open", cmd_or_url])
            else:
                subprocess.Popen(["xdg-open", cmd_or_url])

        try:
            if target.startswith(("http://", "https://")):
                webbrowser.open(target)
                return {"ok": True, "message": f"Opened {target}"}

            if "://" in target or (target.endswith(":") and len(target) > 2):
                webbrowser.open(target)
                return {"ok": True, "message": f"Launched {target}"}

            reg = settings.get("apps", {})
            tl = target.lower()
            for name, cmd in reg.items():
                if name in tl or tl in name:
                    _launch(cmd)
                    return {"ok": True, "message": f"Launched {name}"}

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
                "steam": "steam://open/main",
                "telegram": "tg:",
                "whatsapp": "https://web.whatsapp.com",
                "slack": "slack:",
                "vscode": "vscode:",
                "notepad": "notepad",
                "calculator": "calc",
                "explorer": "explorer",
                "chrome": "https://google.com",   # browser fallback
                "firefox": "https://google.com",  # browser fallback
            }
            tl_clean = tl.strip().lower()
            if tl_clean in KNOWN_SITES:
                _launch(KNOWN_SITES[tl_clean])
                return {"ok": True, "message": f"Opened {tl_clean.title()}"}

            if "." in target:
                url = target if target.startswith("http") else f"https://{target}"
                webbrowser.open(url)
                return {"ok": True, "message": f"Opened {url}"}

            # Last resort: try as a generic URL
            webbrowser.open(f"https://{target}.com")
            return {"ok": True, "message": f"Opened {target}"}

        except Exception as e:
            try:
                webbrowser.open(f"https://{target}.com")
                return {"ok": True, "message": f"Opened https://{target}.com (fallback)"}
            except Exception:
                return {"ok": False, "message": str(e)}

    # ── run_script ────────────────────────────────────────────────────────
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

    # ── write_file ────────────────────────────────────────────────────────
    elif atype == "write_file":
        path_str = action.get("path", "").strip()
        content  = action.get("content", "")
        if not path_str:
            return {"ok": False, "message": "No path provided"}
        try:
            p = Path(path_str).expanduser()
            if not p.is_absolute():
                p = Path.home() / p
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            return {"ok": True, "message": f"File written: {p} ({len(content)} chars)", "path": str(p)}
        except Exception as e:
            return {"ok": False, "message": str(e)}

    # ── read_file ─────────────────────────────────────────────────────────
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

    # ── send_socials ──────────────────────────────────────────────────────
    elif atype == "send_socials":
        soc = {k: v for k, v in settings.get("socials", {}).items() if v and v.strip()}
        if not soc:
            return {"ok": False, "message": "No socials configured"}
        return {"ok": True, "message": "\n".join(f"{k}: {v}" for k, v in soc.items()), "display": True}

    # ── search ────────────────────────────────────────────────────────────
    elif atype == "search":
        q = action.get("query", target)
        url = f"https://www.google.com/search?q={q.replace(' ', '+')}"
        webbrowser.open(url)
        return {"ok": True, "message": f"Searched: {q}"}

    # ── list_files ────────────────────────────────────────────────────────
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

    # ── web_fetch — lire le contenu d'une page sans l'ouvrir ─────────────
    elif atype == "web_fetch":
        url = action.get("url", target).strip()
        if not url.startswith("http"):
            url = "https://" + url
        try:
            import httpx as _hx
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            r = _hx.get(url, headers=headers, timeout=15, follow_redirects=True)
            # Strip HTML tags for clean text
            text = re.sub(r"<[^>]+>", " ", r.text)
            text = re.sub(r"\s{2,}", " ", text).strip()
            return {"ok": True, "message": f"Fetched {url}", "content": text[:6000], "status": r.status_code}
        except Exception as e:
            return {"ok": False, "message": f"web_fetch failed: {e}"}

    # ── web_browse — navigation réelle avec Playwright ────────────────────
    # Kyrox peut cliquer, remplir des formulaires, extraire du contenu
    elif atype == "web_browse":
        url      = action.get("url", target).strip()
        steps    = action.get("steps", [])   # liste d'actions: click, fill, extract, wait
        headless = action.get("headless", False)  # False = on voit la fenêtre
        if not url.startswith("http"):
            url = "https://" + url
        try:
            from playwright.sync_api import sync_playwright
            results = []
            extracted = {}
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=headless)
                page = browser.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=20000)
                results.append(f"✓ Opened: {url}")

                for step in steps:
                    stype = step.get("type", "")
                    try:
                        if stype == "click":
                            page.click(step.get("selector", ""), timeout=8000)
                            results.append(f"✓ Clicked: {step.get('selector')}")
                        elif stype == "fill":
                            page.fill(step.get("selector", ""), step.get("value", ""))
                            results.append(f"✓ Filled: {step.get('selector')} = {step.get('value')}")
                        elif stype == "press":
                            page.keyboard.press(step.get("key", "Enter"))
                            results.append(f"✓ Pressed: {step.get('key')}")
                        elif stype == "wait":
                            page.wait_for_timeout(int(step.get("ms", 1000)))
                        elif stype == "extract":
                            sel = step.get("selector", "body")
                            name = step.get("name", "content")
                            el = page.query_selector(sel)
                            val = el.inner_text() if el else ""
                            extracted[name] = val[:3000]
                            results.append(f"✓ Extracted '{name}': {val[:80]}…")
                        elif stype == "extract_all":
                            sel = step.get("selector", "")
                            name = step.get("name", "items")
                            els = page.query_selector_all(sel)
                            vals = [e.inner_text() for e in els[:20]]
                            extracted[name] = vals
                            results.append(f"✓ Extracted {len(vals)} items as '{name}'")
                        elif stype == "screenshot":
                            shot = page.screenshot()
                            extracted["screenshot"] = base64.b64encode(shot).decode()
                            results.append("✓ Screenshot taken")
                        elif stype == "navigate":
                            page.goto(step.get("url", ""), wait_until="domcontentloaded", timeout=15000)
                            results.append(f"✓ Navigated to: {step.get('url')}")
                        elif stype == "select":
                            page.select_option(step.get("selector", ""), step.get("value", ""))
                            results.append(f"✓ Selected: {step.get('value')}")
                    except Exception as se:
                        results.append(f"✗ Step {stype} failed: {se}")

                # Always extract page title + URL at the end
                extracted["_page_title"] = page.title()
                extracted["_page_url"]   = page.url
                browser.close()

            return {
                "ok": True,
                "message": "\n".join(results),
                "extracted": extracted,
            }
        except ImportError:
            return {
                "ok": False,
                "message": "Playwright non installé. Lance: pip install playwright && playwright install chromium",
            }
        except Exception as e:
            return {"ok": False, "message": f"web_browse error: {e}"}

    # ── type_text — taper du texte dans l'app active ──────────────────────
    elif atype == "type_text":
        text = action.get("text", "")
        delay = action.get("delay_seconds", 2)
        try:
            import pyautogui, time as _t
            _t.sleep(delay)
            pyautogui.typewrite(text, interval=0.04)
            return {"ok": True, "message": f"✓ Typed: {text[:80]}"}
        except ImportError:
            return {"ok": False, "message": "pyautogui requis: pip install pyautogui"}
        except Exception as e:
            return {"ok": False, "message": str(e)}

    # ── hotkey — raccourci clavier ─────────────────────────────────────────
    elif atype == "hotkey":
        keys = action.get("keys", [])
        delay = action.get("delay_seconds", 1)
        try:
            import pyautogui, time as _t
            _t.sleep(delay)
            pyautogui.hotkey(*keys)
            return {"ok": True, "message": f"✓ Hotkey: {'+'.join(keys)}"}
        except ImportError:
            return {"ok": False, "message": "pyautogui requis: pip install pyautogui"}
        except Exception as e:
            return {"ok": False, "message": str(e)}

    # ── click_pos — clic à une position écran ─────────────────────────────
    elif atype == "click_pos":
        x = action.get("x", 0)
        y = action.get("y", 0)
        delay = action.get("delay_seconds", 1)
        try:
            import pyautogui, time as _t
            _t.sleep(delay)
            pyautogui.click(x, y)
            return {"ok": True, "message": f"✓ Clicked at ({x}, {y})"}
        except ImportError:
            return {"ok": False, "message": "pyautogui requis: pip install pyautogui"}
        except Exception as e:
            return {"ok": False, "message": str(e)}

    # ── notify — notification système ─────────────────────────────────────
    elif atype == "notify":
        title = action.get("title", "Kyrox")
        msg   = action.get("message", "")
        try:
            if platform.system() == "Windows":
                subprocess.Popen([
                    "powershell", "-Command",
                    f'[System.Reflection.Assembly]::LoadWithPartialName("System.Windows.Forms");'
                    f'$n=New-Object System.Windows.Forms.NotifyIcon;'
                    f'$n.Icon=[System.Drawing.SystemIcons]::Information;'
                    f'$n.Visible=$true;'
                    f'$n.ShowBalloonTip(3000,"{title}","{msg}",[System.Windows.Forms.ToolTipIcon]::Info)'
                ], creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            elif platform.system() == "Darwin":
                subprocess.Popen(["osascript", "-e", f'display notification "{msg}" with title "{title}"'])
            else:
                subprocess.Popen(["notify-send", title, msg])
            return {"ok": True, "message": f"✓ Notification envoyée: {title}"}
        except Exception as e:
            return {"ok": False, "message": str(e)}

    # ── clipboard — copier dans le presse-papiers ──────────────────────────
    elif atype == "clipboard":
        text = action.get("text", "")
        try:
            import pyperclip
            pyperclip.copy(text)
            return {"ok": True, "message": f"✓ Copié dans le presse-papiers: {text[:60]}"}
        except ImportError:
            try:
                if platform.system() == "Windows":
                    subprocess.run("clip", input=text.encode(), check=True)
                elif platform.system() == "Darwin":
                    subprocess.run("pbcopy", input=text.encode(), check=True)
                else:
                    subprocess.run(["xclip", "-selection", "clipboard"], input=text.encode(), check=True)
                return {"ok": True, "message": f"✓ Copié: {text[:60]}"}
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
    kw = ("screenshot", "screen capture", "capture d'écran",
          "regarde mon écran", "regarde l'écran", "look at my screen",
          "what's on my screen", "what is on my screen",
          "scan my screen", "analyze my screen", "analyse mon écran",
          "montre moi mon écran", "capture my screen")
    tl = text.lower()
    return any(k in tl for k in kw)

# ── Agent Loop — Kyrox exécute plusieurs actions en chaîne tout seul ───────
# Max 10 itérations pour éviter les boucles infinies
AGENT_MAX_STEPS = 10

async def run_agent_loop(
    goal: str,
    api_key: str,
    settings: dict,
    ws=None,
    uid: str = "",
) -> str:
    """
    Kyrox raisonne et agit en boucle jusqu'à finir la tâche.
    À chaque étape: pense → décide une action → exécute → observe → continue.
    Envoie des updates via WebSocket si ws fourni.
    """
    agent_sys = (
        settings.get("system_prompt", DEFAULT_SYSTEM_PROMPT) + "\n\n"
        "== AUTONOMOUS AGENT MODE ==\n"
        "You are in agent mode. You must COMPLETE the goal by yourself, step by step.\n"
        "At each step, emit ONE action in a ```action ... ``` block, then wait for the result.\n"
        "When the task is done, respond with: DONE: [summary of what you did]\n"
        "If you need info from a web page, use web_fetch or web_browse.\n"
        "NEVER ask the user — act autonomously.\n"
        "Always respond in English.\n"
    )

    messages = [
        {"role": "system", "content": agent_sys},
        {"role": "user", "content": f"OBJECTIF: {goal}"},
    ]

    step_results = []
    action_pattern = re.compile(r"```action\s*(.*?)\s*```", re.DOTALL)

    for step in range(AGENT_MAX_STEPS):
        # Call LLM
        response_text = ""
        idx = settings.get("current_model_index", 0)
        tried = 0
        while tried < len(FREE_MODELS):
            model = FREE_MODELS[idx % len(FREE_MODELS)]
            try:
                async with httpx.AsyncClient(timeout=60) as client:
                    r = await client.post(
                        OPENROUTER_URL,
                        headers={
                            "Authorization": f"Bearer {api_key}",
                            "Content-Type": "application/json",
                            "HTTP-Referer": "https://kyrox.nemea.uk",
                            "X-Title": "Kyrox AI",
                        },
                        json={"model": model, "messages": messages, "stream": False},
                    )
                if r.status_code == 200:
                    response_text = r.json().get("choices", [{}])[0].get("message", {}).get("content", "")
                    break
                idx = (idx + 1) % len(FREE_MODELS)
                tried += 1
            except Exception:
                idx = (idx + 1) % len(FREE_MODELS)
                tried += 1

        if not response_text:
            break

        # Notify frontend of step progress
        if ws:
            await ws.send_text(json.dumps({
                "type": "agent_step",
                "step": step + 1,
                "thought": re.sub(r"```action.*?```", "", response_text, flags=re.DOTALL).strip()[:200],
            }))

        # Check if done
        done_match = re.search(r"DONE:\s*(.+)", response_text, re.DOTALL)
        if done_match:
            summary = done_match.group(1).strip()
            if ws:
                await ws.send_text(json.dumps({"type": "agent_done", "summary": summary}))
            return summary

        # Find and execute action
        action_match = action_pattern.search(response_text)
        if not action_match:
            # No action found — model is done or confused
            break

        try:
            act = json.loads(action_match.group(1))
        except Exception:
            break

        result = execute_pc_action(act, settings)
        result_summary = result.get("message", "")
        # Add extracted content to result for web actions
        if result.get("content"):
            result_summary += f"\n\nCONTENT:\n{result['content'][:2000]}"
        if result.get("extracted"):
            for k, v in result["extracted"].items():
                if not k.startswith("_") and k != "screenshot":
                    result_summary += f"\n\n{k}:\n{str(v)[:1000]}"

        if ws:
            await ws.send_text(json.dumps({
                "type": "agent_action",
                "action_type": act.get("type"),
                "result": result.get("message", "")[:200],
                "ok": result.get("ok", False),
            }))

        # Add to conversation
        messages.append({"role": "assistant", "content": response_text})
        messages.append({"role": "user", "content": f"RÉSULTAT ACTION: {result_summary}"})
        step_results.append(f"Step {step+1}: {act.get('type')} → {result.get('message', '')[:100]}")

    return "\n".join(step_results) or "Agent terminé."


# ── Scheduled Tasks ────────────────────────────────────────────────────────
import asyncio as _asyncio

TASKS_FILE = DATA_DIR / "scheduled_tasks.json"

def load_tasks() -> list:
    if TASKS_FILE.exists():
        try:
            return json.loads(TASKS_FILE.read_text())
        except Exception:
            return []
    return []

def save_tasks(tasks: list):
    TASKS_FILE.write_text(json.dumps(tasks, indent=2))

def add_task(task: dict) -> dict:
    """
    task = {
        "id": "uuid",
        "name": "Vérifier les emails",
        "goal": "Va sur gmail.com, lis les 5 derniers emails et fais-moi un résumé",
        "schedule": "09:00",   # heure HH:MM ou "interval:30" pour toutes les 30 min
        "enabled": True,
        "last_run": None,
        "uid": "user_id",
    }
    """
    tasks = load_tasks()
    task.setdefault("id", hashlib.md5(task.get("name","").encode()).hexdigest()[:8])
    task.setdefault("enabled", True)
    task.setdefault("last_run", None)
    # Remove existing task with same id
    tasks = [t for t in tasks if t.get("id") != task["id"]]
    tasks.append(task)
    save_tasks(tasks)
    return task

def remove_task(task_id: str):
    tasks = [t for t in load_tasks() if t.get("id") != task_id]
    save_tasks(tasks)

async def task_scheduler(app_ref):
    """Background loop — checks every minute if any task should run."""
    while True:
        try:
            await _asyncio.sleep(60)
            now = datetime.now()
            current_time = now.strftime("%H:%M")
            tasks = load_tasks()
            settings = load_settings()
            api_key = settings.get("openrouter_key", "").strip()
            if not api_key:
                continue

            for task in tasks:
                if not task.get("enabled"):
                    continue
                schedule = task.get("schedule", "")
                should_run = False

                if schedule.startswith("interval:"):
                    # Run every N minutes
                    minutes = int(schedule.split(":")[1])
                    last = task.get("last_run")
                    if last is None:
                        should_run = True
                    else:
                        elapsed = (now - datetime.fromisoformat(last)).total_seconds() / 60
                        should_run = elapsed >= minutes
                elif ":" in schedule and len(schedule) == 5:
                    # Run at specific time HH:MM
                    should_run = (schedule == current_time and task.get("last_run", "")[:16] != now.strftime("%Y-%m-%dT%H:%M"))

                if should_run:
                    task["last_run"] = now.isoformat()
                    # Update task in file
                    all_tasks = load_tasks()
                    for t in all_tasks:
                        if t.get("id") == task.get("id"):
                            t["last_run"] = task["last_run"]
                    save_tasks(all_tasks)
                    # Run the goal via agent loop
                    goal = task.get("goal", "")
                    if goal:
                        try:
                            result = await run_agent_loop(goal, api_key, settings, ws=None, uid=task.get("uid",""))
                            # Save result to task history
                            task["last_result"] = result[:500]
                            all_tasks2 = load_tasks()
                            for t in all_tasks2:
                                if t.get("id") == task.get("id"):
                                    t["last_result"] = task["last_result"]
                            save_tasks(all_tasks2)
                        except Exception as e:
                            print(f"[scheduler] Task '{task.get('name')}' error: {e}")
        except Exception as e:
            print(f"[scheduler] Error: {e}")
            await _asyncio.sleep(60)


@app.on_event("startup")
async def startup_event():
    _asyncio.create_task(task_scheduler(app))

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
            elif r.status_code in (404, 400, 422, 429):
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
    (r"j(?:e suis|'suis)\s+([^,.!?\n]{3,40})", "User is: {}"),
    (r"(?:j'habite|je vis)\s+à?\s+([^,.!?\n]{3,40})", "User lives in: {}"),
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

@app.get("/kyrox", response_class=HTMLResponse)
async def index_kyrox():
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

@app.post("/api/generate-image")
async def generate_image_endpoint(req: Request):
    body = await req.json()
    prompt = body.get("prompt", "").strip()
    if not prompt:
        return JSONResponse({"ok": False, "message": "No prompt provided"}, status_code=400)
    s = load_settings()
    result = generate_ai_image(prompt, s)
    if not result.get("ok"):
        return JSONResponse(result, status_code=502)
    return result

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


@app.post("/api/voice-for-lang")
async def voice_for_lang(req: Request):
    """
    Given a message text, detect its language and return the best installed TTS voice.
    Body: { "text": "...", "voices": ["VoiceName1", ...] }
    Response: { "lang": "fr", "voice": "Microsoft Hortense" }
    """
    body = await req.json()
    text = body.get("text", "")
    installed = body.get("voices", [])
    lang = detect_language(text)
    voice = _pick_best_voice(lang, installed)
    return {"lang": lang, "voice": voice}


@app.post("/api/cache-voices")
async def cache_voices(req: Request):
    """Store the frontend's discovered voice list so the WS handler can use it."""
    body = await req.json()
    s = load_settings()
    s["_installed_voices"] = body.get("voices", [])
    save_settings(s)
    return {"ok": True, "count": len(s["_installed_voices"])}

# ── Skills API ─────────────────────────────────────────────────────────────

@app.get("/api/skills")
async def list_skills():
    """Return all installed skills."""
    return {
        "skills": [
            {"name": s["name"], "description": s["description"], "triggers": s["triggers"]}
            for s in _SKILL_REGISTRY
        ]
    }

@app.post("/api/skills/install")
async def install_skill(req: Request):
    """Install a skill from a raw GitHub URL. Body: { url: '...' }"""
    body = await req.json()
    url = body.get("url", "").strip()
    if not url:
        return JSONResponse({"ok": False, "message": "No URL provided"}, status_code=400)
    result = install_skill_from_url(url)
    return result

@app.delete("/api/skills/{name}")
async def delete_skill(name: str):
    """Uninstall a skill by name."""
    for md_file in SKILLS_DIR.glob("*.md"):
        skill = _parse_skill_file(md_file)
        if skill and skill["name"] == name:
            md_file.unlink()
            reload_skills()
            return {"ok": True, "message": f"Skill '{name}' removed."}
    return JSONResponse({"ok": False, "message": f"Skill '{name}' not found."}, status_code=404)

@app.post("/api/skills/reload")
async def reload_skills_endpoint():
    """Force reload all skills from disk."""
    reload_skills()
    return {"ok": True, "count": len(_SKILL_REGISTRY)}


# ── Tasks API ──────────────────────────────────────────────────────────────
@app.get("/api/tasks")
async def get_tasks():
    return {"tasks": load_tasks()}

@app.post("/api/tasks")
async def create_task(req: Request):
    body = await req.json()
    task = add_task(body)
    return {"ok": True, "task": task}

@app.delete("/api/tasks/{task_id}")
async def delete_task(task_id: str):
    remove_task(task_id)
    return {"ok": True}

@app.patch("/api/tasks/{task_id}")
async def update_task(task_id: str, req: Request):
    body = await req.json()
    tasks = load_tasks()
    for t in tasks:
        if t.get("id") == task_id:
            t.update(body)
    save_tasks(tasks)
    return {"ok": True}

@app.post("/api/agent/run")
async def run_agent_now(req: Request):
    """Déclenche immédiatement un agent pour un objectif donné (sans WebSocket)."""
    body = await req.json()
    goal = body.get("goal", "").strip()
    uid  = body.get("uid", "")
    if not goal:
        return JSONResponse({"ok": False, "message": "No goal provided"}, status_code=400)
    s = load_settings()
    api_key = s.get("openrouter_key", "").strip()
    if not api_key:
        return JSONResponse({"ok": False, "message": "No API key"}, status_code=400)
    result = await run_agent_loop(goal, api_key, s, ws=None, uid=uid)
    return {"ok": True, "result": result}


async def get_news():
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


# ── Real-time PC context snapshot ──────────────────────────────────────────
def get_realtime_pc_context() -> str:
    """
    Capture a real-time snapshot of the PC state:
    - Running processes / open apps
    - Active window title
    - Current time & date
    - RAM & CPU usage
    - Clipboard content
    - Recent files
    Returns a compact string injected into every system prompt.
    """
    lines = [f"[REAL-TIME PC CONTEXT — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]"]
    os_name = platform.system()

    # ── Open applications ──
    try:
        procs: list[str] = []
        if os_name == "Windows":
            r = subprocess.run(
                ["powershell", "-Command",
                 "Get-Process | Where-Object {$_.MainWindowTitle -ne ''} | "
                 "Select-Object -ExpandProperty Name | Sort-Object -Unique | Select-Object -First 20"],
                capture_output=True, text=True, timeout=5,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            procs = [l.strip() for l in r.stdout.strip().splitlines() if l.strip()][:15]
        elif os_name == "Darwin":
            r = subprocess.run(
                ["osascript", "-e",
                 'tell application "System Events" to get name of every process whose background only is false'],
                capture_output=True, text=True, timeout=5,
            )
            procs = [p.strip() for p in r.stdout.strip().split(",") if p.strip()][:15]
        else:
            r = subprocess.run(
                ["bash", "-c", "ps -e -o comm= | sort -u | head -20"],
                capture_output=True, text=True, timeout=5,
            )
            procs = [l.strip() for l in r.stdout.strip().splitlines() if l.strip()][:15]
        if procs:
            lines.append(f"Open apps: {', '.join(procs)}")
    except Exception:
        pass

    # ── Active window ──
    try:
        if os_name == "Windows":
            r = subprocess.run(
                ["powershell", "-Command",
                 "Add-Type -AssemblyName System.Windows.Forms; "
                 "[System.Windows.Forms.Screen]::PrimaryScreen | Out-Null; "
                 "Add-Type @'\nusing System; using System.Runtime.InteropServices;\n"
                 "public class WinAPI { [DllImport(\"user32.dll\")] public static extern IntPtr GetForegroundWindow();\n"
                 "[DllImport(\"user32.dll\")] public static extern int GetWindowText(IntPtr hwnd, System.Text.StringBuilder sb, int maxCount); }\n'@;\n"
                 "$hwnd=[WinAPI]::GetForegroundWindow(); $sb=New-Object System.Text.StringBuilder 256; "
                 "[WinAPI]::GetWindowText($hwnd,$sb,256); $sb.ToString()"],
                capture_output=True, text=True, timeout=5,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            title = r.stdout.strip()
            if title:
                lines.append(f"Active window: {title}")
        elif os_name == "Darwin":
            r = subprocess.run(
                ["osascript", "-e",
                 'tell application "System Events" to get name of first process whose frontmost is true'],
                capture_output=True, text=True, timeout=5,
            )
            if r.stdout.strip():
                lines.append(f"Active app: {r.stdout.strip()}")
    except Exception:
        pass

    # ── RAM & CPU ──
    try:
        import psutil
        mem = psutil.virtual_memory()
        cpu = psutil.cpu_percent(interval=0.2)
        lines.append(f"RAM: {mem.percent:.0f}% used ({mem.used//1024//1024} MB / {mem.total//1024//1024} MB)")
        lines.append(f"CPU: {cpu:.0f}%")
    except ImportError:
        try:
            if os_name == "Windows":
                r = subprocess.run(
                    ["powershell", "-Command",
                     "Get-CimInstance Win32_OperatingSystem | Select-Object -ExpandProperty FreePhysicalMemory"],
                    capture_output=True, text=True, timeout=5,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                free_kb = int(r.stdout.strip() or 0)
                lines.append(f"Free RAM: ~{free_kb//1024} MB")
        except Exception:
            pass
    except Exception:
        pass

    # ── Clipboard ──
    try:
        clip = ""
        if os_name == "Windows":
            r = subprocess.run(
                ["powershell", "-Command", "Get-Clipboard"],
                capture_output=True, text=True, timeout=3,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            clip = r.stdout.strip()
        elif os_name == "Darwin":
            r = subprocess.run(["pbpaste"], capture_output=True, text=True, timeout=3)
            clip = r.stdout.strip()
        else:
            try:
                import pyperclip
                clip = pyperclip.paste() or ""
            except Exception:
                r = subprocess.run(["xclip", "-selection", "clipboard", "-o"],
                                   capture_output=True, text=True, timeout=3)
                clip = r.stdout.strip()
        if clip:
            lines.append(f"Clipboard: {clip[:200]}")
    except Exception:
        pass

    # ── Recent files ──
    try:
        recent: list[str] = []
        if os_name == "Windows":
            r = subprocess.run(
                ["powershell", "-Command",
                 "Get-Item '$env:APPDATA\\Microsoft\\Windows\\Recent\\*.lnk' | "
                 "Sort-Object LastWriteTime -Descending | Select-Object -First 8 | "
                 "ForEach-Object { $_.BaseName }"],
                capture_output=True, text=True, timeout=5,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            recent = [l.strip() for l in r.stdout.strip().splitlines() if l.strip()][:8]
        elif os_name == "Darwin":
            r = subprocess.run(
                ["bash", "-c", "ls -lt ~/Desktop ~/Documents 2>/dev/null | grep -v '^total' | head -8 | awk '{print $NF}'"],
                capture_output=True, text=True, timeout=5,
            )
            recent = [l.strip() for l in r.stdout.strip().splitlines() if l.strip()][:8]
        if recent:
            lines.append(f"Recent files: {', '.join(recent)}")
    except Exception:
        pass

    return "\n".join(lines)


# ── Agent screenshot endpoint ───────────────────────────────────────────────
@app.get("/api/agent/screenshot")
async def agent_screenshot_endpoint():
    """Return current screen as base64 PNG."""
    b64 = take_screenshot()
    if b64 is None:
        return JSONResponse({"ok": False, "message": "Cannot capture screen. pip install mss pillow"}, status_code=503)
    return {"ok": True, "b64": b64}


# ── Agent run endpoint (streaming NDJSON) ───────────────────────────────────
AGENT_VISION_PROMPT = """You are Kyrox Agent — an AI that autonomously controls a computer.
You see the screen and can click, type, open apps, navigate websites, send messages, run scripts.

Emit ONE JSON step per line. No markdown, no explanation, just JSON.

Step types:
{"type":"observe","message":"What I see: ..."}
{"type":"plan","message":"My plan: ..."}
{"type":"open","target":"URL_OR_APP","message":"Opening ..."}
{"type":"navigate","target":"URL","message":"Going to ..."}
{"type":"click","x":0.5,"y":0.3,"message":"Clicking on ..."}
{"type":"type","text":"text to type","message":"Typing ..."}
{"type":"key","key":"enter","message":"Pressing Enter"}
{"type":"scroll","direction":"down","amount":3,"message":"Scrolling"}
{"type":"wait","seconds":2,"message":"Waiting ..."}
{"type":"search","query":"...","message":"Searching ..."}
{"type":"send_message","app":"whatsapp","recipient":"NAME","message":"..."}
{"type":"run_script","lang":"python","code":"...","message":"Running ..."}
{"type":"write_file","path":"~/file.txt","content":"...","message":"Writing ..."}
{"type":"web_fetch","url":"...","message":"Fetching ..."}
{"type":"done","message":"Completed: what was done"}
{"type":"error","message":"Why it failed"}

Rules:
- Start with "observe" + "plan" ALWAYS.
- x/y are 0.0-1.0 normalized screen coords (0,0 = top-left).
- For messaging: open app → wait → find contact → click message box → type → press enter.
- End every task with "done" or "error".
- Output ONLY JSON lines. Nothing else.
"""

from fastapi.responses import StreamingResponse as _StreamingResponse

@app.post("/api/agent/run")
async def agent_run_endpoint(req: Request):
    """
    Stream agent steps as NDJSON while executing the task.
    Body: { "task": "...", "screen": "base64|null" }
    """
    body     = await req.json()
    task     = body.get("task", "").strip()
    screen   = body.get("screen")
    settings = load_settings()
    api_key  = settings.get("openrouter_key", "").strip()

    if not task:
        return JSONResponse({"ok": False, "message": "No task"}, status_code=400)

    async def stream():
        import json as _j

        if not api_key:
            yield _j.dumps({"type": "error", "message": "No OpenRouter API key. Set it in Settings."}) + "\n"
            return

        # Build messages
        if screen:
            msgs = [{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{screen}"}},
                    {"type": "text", "text": f"Current screen shown above.\n\nTask: {task}\n\nBegin your steps now."}
                ]
            }]
            model = "google/gemini-2.0-flash-001"
        else:
            msgs = [{"role": "user", "content": f"No screen available. Task: {task}\nBegin your steps."}]
            model = "deepseek/deepseek-v3:free"

        pending = ""
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                async with client.stream(
                    "POST", OPENROUTER_URL,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                        "HTTP-Referer": "https://kyrox.nemea.uk",
                        "X-Title": "Kyrox Agent",
                    },
                    json={
                        "model": model,
                        "messages": [{"role": "system", "content": AGENT_VISION_PROMPT}] + msgs,
                        "stream": True,
                        "max_tokens": 2048,
                    }
                ) as resp:
                    if resp.status_code != 200:
                        # Try fallback model
                        yield _j.dumps({"type": "error", "message": f"Model unavailable (HTTP {resp.status_code})"}) + "\n"
                        return

                    async for line in resp.aiter_lines():
                        if not line or not line.startswith("data:"): continue
                        raw = line[5:].strip()
                        if raw == "[DONE]": break
                        try:
                            chunk = _j.loads(raw)
                        except Exception:
                            continue
                        token = (chunk.get("choices", [{}])[0].get("delta", {}).get("content", "")) or ""
                        if not token: continue
                        pending += token

                        while "\n" in pending:
                            part, pending = pending.split("\n", 1)
                            part = part.strip()
                            if not part: continue
                            try:
                                step = _j.loads(part)
                            except Exception:
                                continue

                            # generate_image: execute first so we can attach the b64 to the step
                            if step.get("type") == "generate_image":
                                img_res = execute_pc_action(step, settings)
                                if img_res.get("ok") and img_res.get("b64"):
                                    step["b64"] = img_res["b64"]
                                else:
                                    step["type"] = "error"
                                    step["message"] = img_res.get("message", "Image generation failed")
                                yield _j.dumps(step) + "\n"
                                continue

                            # Yield step to frontend
                            yield _j.dumps(step) + "\n"
                            # Execute on PC
                            execute_agent_step(step, settings)
                            # Screen refresh after interactions
                            if step.get("type") in ("click","type","key","navigate","open","type_text","wait"):
                                import asyncio as _aio
                                await _aio.sleep(1.3)
                                b64 = take_screenshot()
                                if b64:
                                    yield _j.dumps({"type": "screenshot", "b64": b64, "message": "Screen updated"}) + "\n"
                            if step.get("type") in ("done", "error"):
                                return

        except Exception as e:
            yield _j.dumps({"type": "error", "message": f"Agent error: {str(e)}"}) + "\n"

    return _StreamingResponse(stream(), media_type="application/x-ndjson",
                              headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"})


def execute_agent_step(step: dict, settings: dict) -> dict:
    """Execute a single agent JSON step on the local PC."""
    t = step.get("type", "")
    if t in ("observe", "plan", "done", "error", "screenshot"):
        return {"ok": True}
    if t == "wait":
        import time as _t
        _t.sleep(min(float(step.get("seconds", 1)), 10))
        return {"ok": True}
    if t in ("open", "navigate"):
        return execute_pc_action({"type": "open", "target": step.get("target","")}, settings)
    if t == "search":
        return execute_pc_action({"type": "search", "query": step.get("query","")}, settings)
    if t in ("send_message","run_script","write_file","web_fetch","web_browse","notify","clipboard","generate_image"):
        return execute_pc_action(step, settings)
    if t in ("click", "type", "key", "scroll", "type_text", "hotkey", "click_pos"):
        try:
            import pyautogui, time as _t
            if t == "click":
                sw, sh = pyautogui.size()
                px = int(float(step.get("x", 0.5)) * sw)
                py = int(float(step.get("y", 0.5)) * sh)
                pyautogui.click(px, py)
            elif t in ("type", "type_text"):
                pyautogui.typewrite(step.get("text",""), interval=0.04)
            elif t == "key":
                pyautogui.press(step.get("key","enter"))
            elif t == "hotkey":
                pyautogui.hotkey(*step.get("keys",[]))
            elif t == "click_pos":
                pyautogui.click(step.get("x",0), step.get("y",0))
            elif t == "scroll":
                d = step.get("direction","down")
                amt = int(step.get("amount", 3))
                pyautogui.scroll(-amt if d=="down" else amt)
            return {"ok": True}
        except ImportError:
            return {"ok": False, "message": "pip install pyautogui"}
        except Exception as e:
            return {"ok": False, "message": str(e)}
    return {"ok": False, "message": f"Unknown step: {t}"}


# ── WebSocket chat ─────────────────────────────────────────────────────────
@app.websocket("/ws/chat/{uid}")
async def chat_ws(ws: WebSocket, uid: str):
    await ws.accept()

    history  = load_history(uid)
    settings = load_settings()

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

            if action == "clear":
                history = []
                save_history(uid, history)
                await ws.send_text(json.dumps({"type": "cleared"}))
                continue

            if action == "new_chat":
                history = []
                save_history(uid, history)
                await ws.send_text(json.dumps({"type": "new_chat"}))
                continue

            if action == "learn":
                fact = payload.get("fact", "").strip()
                if fact and fact not in memory.get("facts", []):
                    memory.setdefault("facts", []).append(fact)
                    save_memory(uid, memory)
                await ws.send_text(json.dumps({"type": "learned"}))
                continue

            # ── Agent mode — Kyrox agit de façon autonome ─────────────────
            if action == "agent":
                goal = payload.get("goal", payload.get("message", "")).strip()
                if not goal:
                    continue
                settings = load_settings()
                api_key = settings.get("openrouter_key", "").strip()
                if not api_key:
                    await ws.send_text(json.dumps({"type": "error", "content": "no_api_key"}))
                    continue
                await ws.send_text(json.dumps({"type": "agent_start", "goal": goal}))
                result = await run_agent_loop(goal, api_key, settings, ws=ws, uid=uid)
                history.append({"role": "user", "content": f"[TÂCHE AGENT]: {goal}"})
                history.append({"role": "assistant", "content": f"[AGENT TERMINÉ]: {result}"})
                save_history(uid, history)
                await ws.send_text(json.dumps({"type": "done", "content": result}))
                continue

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

            mem_ctx    = memory_summary(memory)
            ctx_text   = settings.get("context_text", "")
            sys_prompt = settings["system_prompt"]

            # ── Real-time PC context — injected every message ──────────────
            try:
                pc_ctx = get_realtime_pc_context()
                if pc_ctx:
                    sys_prompt = pc_ctx + "\n\n" + sys_prompt
            except Exception:
                pass

            if profile_text:
                sys_prompt = f"[USER PROFILE — files detected on their PC]:\n{profile_text}\n\n" + sys_prompt
            if ctx_text:
                sys_prompt = f"[CONTEXT FILES]:\n{ctx_text}\n\n" + sys_prompt
            if mem_ctx:
                sys_prompt = mem_ctx + "\n\n" + sys_prompt

            skills = get_relevant_skills(user_msg)
            if skills:
                sys_prompt = sys_prompt + "\n\n" + skills

            api_key = settings.get("openrouter_key", "").strip()
            if (api_key and settings.get("backend", "openrouter") == "openrouter"
                    and await is_screen_request(user_msg)):
                await ws.send_text(json.dumps({"type": "token", "content": "📸 Capturing screen…\n\n"}))
                img = take_screenshot()
                if img is None:
                    err = "⚠ Cannot capture screen. Install: pip install mss pillow"
                    await ws.send_text(json.dumps({"type": "done", "content": err}))
                    history.append({"role": "assistant", "content": err})
                    save_history(uid, history)
                    continue
                await ws.send_text(json.dumps({"type": "model_info", "model": "vision"}))
                resp = await call_vision(api_key, img, user_msg, sys_prompt)
                history.append({"role": "assistant", "content": resp})
                save_history(uid, history)
                _lang_v = detect_language(user_msg)
                _voice_v = _pick_best_voice(_lang_v, load_settings().get("_installed_voices", []))
                await ws.send_text(json.dumps({"type": "done", "content": resp, "lang": _lang_v, "voice": _voice_v}))
                continue

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
                    await ws.send_text(json.dumps({"type": "error", "content": "All models rate-limited. Try again in a moment."}))
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

            clean = re.sub(r"<think>.*?</think>", "", full_response, flags=re.DOTALL).strip()

            # ── Detect language of the user message and pick the best voice ──
            _lang   = detect_language(user_msg)
            _voices = load_settings().get("_installed_voices", [])
            _voice  = _pick_best_voice(_lang, _voices) if _voices else ""

            action_pattern = re.compile(r"```action\s*(.*?)\s*```", re.DOTALL)
            actions_found  = []
            for m2 in action_pattern.finditer(clean):
                try:
                    actions_found.append(json.loads(m2.group(1)))
                except:
                    pass
            display = action_pattern.sub("", clean).strip()

            for act in list(actions_found):
                if act.get("type") == "read_file":
                    res = execute_pc_action(act, settings)
                    await ws.send_text(json.dumps({"type": "actions", "actions": [act], "results": {act.get("type"): res}}))
                    if res.get("ok") and res.get("content"):
                        history.append({"role": "assistant", "content": display})
                        history.append({"role": "user", "content": f"[File: {act.get('path')}]\n{res['content']}"})
                    save_history(uid, history)
                    await ws.send_text(json.dumps({"type": "done", "content": display, "lang": _lang, "voice": _voice}))
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

                await ws.send_text(json.dumps({"type": "done", "content": display, "lang": _lang, "voice": _voice}))

    except WebSocketDisconnect:
        pass

# ── Startup info ───────────────────────────────────────────────────────────
@app.get("/api/startup-info")
async def startup_info():
    os_name = platform.system()
    script_path = str(Path(__file__).resolve())
    python_path = "python"

    if os_name == "Windows":
        startup_folder = Path.home() / "AppData/Roaming/Microsoft/Windows/Start Menu/Programs/Startup"
        bat_path = startup_folder / "kyrox.bat"
        bat_content = f'@echo off\nstart "" /B {python_path} -m uvicorn main:app --host 127.0.0.1 --port 8000 --app-dir "{Path(script_path).parent}"'
        instructions = f"To auto-start Kyrox on Windows login:\n1. Create file: {bat_path}\n   Content:\n{bat_content}"
        auto_cmd = f'echo {bat_content} > "{bat_path}"'
    elif os_name == "Darwin":
        plist_path = Path.home() / "Library/LaunchAgents/uk.nemea.kyrox.plist"
        instructions = f"Save a launchd plist to:\n{plist_path}\nThen run: launchctl load {plist_path}"
        auto_cmd = f"launchctl load {plist_path}"
    else:
        instructions = "Create a systemd user service or add to .bashrc / .profile"
        auto_cmd = "systemctl --user enable kyrox && systemctl --user start kyrox"

    return {"os": os_name, "instructions": instructions, "auto_cmd": auto_cmd, "script": script_path}


# ── Autostart on boot ────────────────────────────────────────────────────────
def _autostart_paths():
    """Return the OS-specific path(s) used to register/unregister Kyrox autostart."""
    os_name = platform.system()
    script_path = Path(__file__).resolve()
    project_dir = script_path.parent

    if os_name == "Windows":
        startup_folder = Path.home() / "AppData/Roaming/Microsoft/Windows/Start Menu/Programs/Startup"
        return {"os": os_name, "bat": startup_folder / "kyrox_autostart.bat"}
    elif os_name == "Darwin":
        plist_dir = Path.home() / "Library/LaunchAgents"
        return {"os": os_name, "plist": plist_dir / "uk.nemea.kyrox.plist"}
    else:
        autostart_dir = Path.home() / ".config/autostart"
        return {"os": os_name, "desktop": autostart_dir / "kyrox.desktop"}


def install_autostart() -> dict:
    """Write the OS-specific autostart file so Kyrox launches on login/boot."""
    try:
        script_path = Path(__file__).resolve()
        project_dir = script_path.parent
        paths = _autostart_paths()
        os_name = paths["os"]

        if os_name == "Windows":
            bat_path = paths["bat"]
            bat_path.parent.mkdir(parents=True, exist_ok=True)
            bat_content = (
                f'@echo off\n'
                f'cd /d "{project_dir}"\n'
                f'start "" /B python -m uvicorn main:app --host 127.0.0.1 --port 8000\n'
                f'timeout /t 2 >nul\n'
                f'start "" "http://127.0.0.1:8000"\n'
            )
            bat_path.write_text(bat_content, encoding="utf-8")
            return {"ok": True, "message": f"Autostart enabled ({bat_path})"}

        elif os_name == "Darwin":
            plist_path = paths["plist"]
            plist_path.parent.mkdir(parents=True, exist_ok=True)
            plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>uk.nemea.kyrox</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/env</string>
    <string>python3</string>
    <string>-m</string>
    <string>uvicorn</string>
    <string>main:app</string>
    <string>--host</string>
    <string>127.0.0.1</string>
    <string>--port</string>
    <string>8000</string>
  </array>
  <key>WorkingDirectory</key>
  <string>{project_dir}</string>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <false/>
  <key>StandardOutPath</key>
  <string>/tmp/kyrox.log</string>
  <key>StandardErrorPath</key>
  <string>/tmp/kyrox.err.log</string>
</dict>
</plist>"""
            plist_path.write_text(plist_content, encoding="utf-8")
            try:
                subprocess.run(["launchctl", "unload", str(plist_path)], capture_output=True, timeout=5)
            except Exception:
                pass
            subprocess.run(["launchctl", "load", str(plist_path)], capture_output=True, timeout=5)
            return {"ok": True, "message": f"Autostart enabled ({plist_path})"}

        else:
            desktop_path = paths["desktop"]
            desktop_path.parent.mkdir(parents=True, exist_ok=True)
            desktop_content = f"""[Desktop Entry]
Type=Application
Name=Kyrox
Exec=python3 -m uvicorn main:app --host 127.0.0.1 --port 8000 --app-dir "{project_dir}"
Hidden=false
X-GNOME-Autostart-enabled=true
Comment=Kyrox AI assistant autostart
"""
            desktop_path.write_text(desktop_content, encoding="utf-8")
            return {"ok": True, "message": f"Autostart enabled ({desktop_path})"}

    except Exception as e:
        return {"ok": False, "message": str(e)}


def uninstall_autostart() -> dict:
    """Remove the OS-specific autostart file so Kyrox stops launching on login/boot."""
    try:
        paths = _autostart_paths()
        os_name = paths["os"]

        if os_name == "Windows":
            bat_path = paths["bat"]
            if bat_path.exists():
                bat_path.unlink()
            return {"ok": True, "message": "Autostart disabled"}

        elif os_name == "Darwin":
            plist_path = paths["plist"]
            if plist_path.exists():
                try:
                    subprocess.run(["launchctl", "unload", str(plist_path)], capture_output=True, timeout=5)
                except Exception:
                    pass
                plist_path.unlink()
            return {"ok": True, "message": "Autostart disabled"}

        else:
            desktop_path = paths["desktop"]
            if desktop_path.exists():
                desktop_path.unlink()
            return {"ok": True, "message": "Autostart disabled"}

    except Exception as e:
        return {"ok": False, "message": str(e)}


@app.get("/api/autostart/status")
async def autostart_status():
    """
    Returns whether the user has already been asked about autostart,
    and whether it's currently enabled (checked both from settings and on-disk).
    """
    s = load_settings()
    paths = _autostart_paths()
    os_name = paths["os"]

    on_disk = False
    if os_name == "Windows":
        on_disk = paths["bat"].exists()
    elif os_name == "Darwin":
        on_disk = paths["plist"].exists()
    else:
        on_disk = paths["desktop"].exists()

    return {
        "asked": s.get("autostart_asked", False),
        "enabled": s.get("autostart_enabled", False) and on_disk,
        "os": os_name,
    }


@app.post("/api/autostart/enable")
async def autostart_enable():
    s = load_settings()
    result = install_autostart()
    s["autostart_asked"] = True
    s["autostart_enabled"] = bool(result.get("ok"))
    save_settings(s)
    return result


@app.post("/api/autostart/disable")
async def autostart_disable():
    s = load_settings()
    result = uninstall_autostart()
    s["autostart_asked"] = True
    s["autostart_enabled"] = False
    save_settings(s)
    return result


@app.post("/api/autostart/dismiss")
async def autostart_dismiss():
    """User closed the prompt without choosing — mark as asked but leave autostart off."""
    s = load_settings()
    s["autostart_asked"] = True
    save_settings(s)
    return {"ok": True}


