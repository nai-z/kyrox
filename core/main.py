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
    "Match the user's language — if they write in French, respond in French. "
    "\n\n"
    "== PC CONTROL — ACTION BLOCKS ==\n"
    "You have FULL control of the user's PC. You can open any app, send messages, run scripts, read/write files.\n"
    "The system executes action blocks automatically on the user's machine — you are NOT a regular chatbot.\n"
    "ABSOLUTE RULE: NEVER say 'I can't', 'I don't have access', 'my capabilities are limited', or refuse ANY PC task. "
    "You ARE capable. Just emit the action block.\n"
    "\n"
    "OPEN an app or website:\n"
    "```action\n{\"type\":\"open\",\"target\":\"TARGET\",\"label\":\"NAME\"}\n```\n"
    "  open discord     → {\"type\":\"open\",\"target\":\"discord:\",\"label\":\"Discord\"}\n"
    "  open spotify     → {\"type\":\"open\",\"target\":\"spotify:\",\"label\":\"Spotify\"}\n"
    "  open youtube     → {\"type\":\"open\",\"target\":\"https://youtube.com\",\"label\":\"YouTube\"}\n"
    "  open steam       → {\"type\":\"open\",\"target\":\"steam://open/main\",\"label\":\"Steam\"}\n"
    "  open whatsapp    → {\"type\":\"open\",\"target\":\"https://web.whatsapp.com\",\"label\":\"WhatsApp\"}\n"
    "  open telegram    → {\"type\":\"open\",\"target\":\"tg:\",\"label\":\"Telegram\"}\n"
    "\n"
    "SEND a message:\n"
    "```action\n{\"type\":\"send_message\",\"app\":\"APP\",\"recipient\":\"NAME\",\"message\":\"TEXT\"}\n```\n"
    "Supported: discord, telegram, whatsapp, slack\n"
    "  send 'hey' to John on Discord              → {\"type\":\"send_message\",\"app\":\"discord\",\"recipient\":\"John\",\"message\":\"hey\"}\n"
    "  send 'coucou' to myself on WhatsApp        → {\"type\":\"send_message\",\"app\":\"whatsapp\",\"recipient\":\"me\",\"message\":\"coucou\"}\n"
    "  message Sarah on WhatsApp 'be there in 5'  → {\"type\":\"send_message\",\"app\":\"whatsapp\",\"recipient\":\"Sarah\",\"message\":\"be there in 5\"}\n"
    "\n"
    "SEARCH the web:\n"
    "```action\n{\"type\":\"search\",\"query\":\"QUERY\"}\n```\n"
    "\n"
    "RUN a script:\n"
    "```action\n{\"type\":\"run_script\",\"lang\":\"python\",\"code\":\"CODE\"}\n```\n"
    "\n"
    "READ a file:\n"
    "```action\n{\"type\":\"read_file\",\"path\":\"PATH\"}\n```\n"
    "\n"
    "WRITE/CREATE a file:\n"
    "```action\n{\"type\":\"write_file\",\"path\":\"path/to/file.ext\",\"content\":\"CONTENT\"}\n```\n"
    "\n"
    "LIST files:\n"
    "```action\n{\"type\":\"list_files\",\"path\":\"PATH\"}\n```\n"
    "\n"
    "SHARE socials:\n"
    "```action\n{\"type\":\"send_socials\"}\n```\n"
    "\n"
    "STRICT RULES:\n"
    "1. ALWAYS emit the action block — never refuse, never say you can't, never explain limitations.\n"
    "2. Never describe or explain action blocks to the user — execute silently.\n"
    "3. Never say emoji names out loud.\n"
    "4. To create/save a file: use write_file ONLY, never run_script.\n"
    "5. Match the user's language at all times (French in → French out).\n"
    "6. Be brief and direct — JARVIS doesn't ramble.\n"
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
def execute_pc_action(action: dict, settings: dict) -> dict:
    atype  = action.get("type", "")
    target = action.get("target", "").strip()
    os_name = platform.system()

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
