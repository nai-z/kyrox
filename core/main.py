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
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
VISION_MODEL   = "google/gemini-flash-1.5"

DEFAULT_SYSTEM_PROMPT = (
    "You are Kyrox, an elite AI companion inspired by JARVIS from Iron Man. "
    "You are sharp, confident, slightly witty, and deeply helpful. "
    "You remember everything about your user and use it naturally in conversation. "
    "Speak in short, punchy sentences unless a detailed answer is needed. "
    "When asked to open an app or website, emit an action block:\n"
    "```action\n{\"type\":\"open\",\"target\":\"app_or_url\",\"label\":\"name\"}\n```\n"
    "When asked to search the web:\n"
    "```action\n{\"type\":\"search\",\"query\":\"...\"}\n```\n"
    "When asked to run a script:\n"
    "```action\n{\"type\":\"run_script\",\"lang\":\"python\",\"code\":\"...\"}\n```\n"
    "When asked to read a file:\n"
    "```action\n{\"type\":\"read_file\",\"path\":\"...\"}\n```\n"
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
    "socials": {"twitch":"","twitter":"","instagram":"","youtube":"","discord":"","github":""},
    "apps": {
        "steam":"steam://open/main","spotify":"spotify:","discord":"discord:",
        "chrome":"chrome","firefox":"firefox","vscode":"code",
        "notepad":"notepad","calculator":"calc","explorer":"explorer",
    },
    "context_files": [],   # list of paths scanned at startup
    "context_text": "",    # aggregated content from .md/.txt files
}

# ── Settings ───────────────────────────────────────────────────────────────
def load_settings() -> dict:
    if SETTINGS_FILE.exists():
        with open(SETTINGS_FILE) as f:
            data = json.load(f)
        merged = {**DEFAULT_SETTINGS, **data}
        for key in ("socials","apps"):
            merged[key] = {**DEFAULT_SETTINGS[key], **data.get(key, {})}
        return merged
    return DEFAULT_SETTINGS.copy()

def save_settings(data: dict):
    with open(SETTINGS_FILE,"w") as f:
        json.dump(data, f, indent=2)

# ── Per-user data (history + memory) ──────────────────────────────────────
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
    return json.loads(p.read_text()) if p.exists() else {"facts":[],"preferences":{}}

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
            name = next((f.split("name is ")[-1] for f in mem.get("facts",[]) if "name is" in f.lower()), d.name[:8])
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

# ── Context file reader (.md / .txt) ──────────────────────────────────────
def scan_context_files(paths: list[str]) -> str:
    """Read .md and .txt files from given paths, return combined text (truncated)."""
    chunks = []
    for raw in paths:
        p = Path(raw).expanduser()
        if p.is_file() and p.suffix.lower() in (".md",".txt"):
            try:
                chunks.append(f"[File: {p.name}]\n{p.read_text(errors='replace')[:4000]}")
            except Exception:
                pass
        elif p.is_dir():
            for f in sorted(p.rglob("*"))[:20]:
                if f.is_file() and f.suffix.lower() in (".md",".txt"):
                    try:
                        chunks.append(f"[File: {f.name}]\n{f.read_text(errors='replace')[:2000]}")
                    except Exception:
                        pass
    combined = "\n\n---\n\n".join(chunks)
    return combined[:12000]   # hard cap

# ── PC Actions ────────────────────────────────────────────────────────────
def execute_pc_action(action: dict, settings: dict) -> dict:
    atype  = action.get("type","")
    target = action.get("target","")
    os_name = platform.system()

    if atype == "open":
        try:
            if target.startswith(("http://","https://")):
                webbrowser.open(target)
                return {"ok":True,"message":f"Opened {target}"}
            if "://" in target or target.endswith(":"):
                if os_name == "Windows": os.startfile(target)
                else: subprocess.Popen(["xdg-open",target])
                return {"ok":True,"message":f"Launched {target}"}
            reg = settings.get("apps",{})
            tl = target.lower()
            for name, cmd in reg.items():
                if name in tl or tl in name:
                    if cmd.startswith("http") or "://" in cmd:
                        webbrowser.open(cmd)
                    elif os_name == "Windows":
                        os.startfile(cmd) if os.path.exists(cmd) else subprocess.Popen(cmd,shell=True)
                    else:
                        subprocess.Popen([cmd],shell=True)
                    return {"ok":True,"message":f"Launched {name}"}
            if os_name == "Windows":   subprocess.Popen(target,shell=True)
            elif os_name == "Darwin":  subprocess.Popen(["open","-a",target])
            else:                       subprocess.Popen([target])
            return {"ok":True,"message":f"Launched {target}"}
        except Exception as e:
            return {"ok":False,"message":str(e)}

    elif atype == "run_script":
        lang = action.get("lang","python").lower()
        code = action.get("code","")
        if not code.strip():
            return {"ok":False,"message":"No code provided"}
        try:
            ext = {
                "python":".py","py":".py","bash":".sh","shell":".sh",
                "powershell":".ps1","batch":".bat","js":".js","javascript":".js"
            }.get(lang,".py")
            with tempfile.NamedTemporaryFile(mode="w",suffix=ext,delete=False,encoding="utf-8") as f:
                f.write(code); tmp = f.name
            if lang in ("python","py"):
                proc = subprocess.run(["python",tmp],capture_output=True,text=True,timeout=30)
            elif lang in ("bash","shell"):
                proc = subprocess.run(["bash",tmp],capture_output=True,text=True,timeout=30)
            elif lang == "powershell":
                proc = subprocess.run(["powershell","-File",tmp],capture_output=True,text=True,timeout=30)
            else:
                proc = subprocess.run(["python",tmp],capture_output=True,text=True,timeout=30)
            os.unlink(tmp)
            out = (proc.stdout or "")+(proc.stderr or "")
            return {"ok":proc.returncode==0,"message":out.strip() or "Executed (no output)"}
        except subprocess.TimeoutExpired:
            return {"ok":False,"message":"Script timed out (30s)"}
        except Exception as e:
            return {"ok":False,"message":str(e)}

    elif atype == "read_file":
        p = Path(target)
        try:
            if not p.exists(): return {"ok":False,"message":f"Not found: {target}"}
            if p.stat().st_size > 5*1024*1024: return {"ok":False,"message":"File too large (>5MB)"}
            content = p.read_text(encoding="utf-8",errors="replace")
            return {"ok":True,"message":f"Read {len(content)} chars","content":content[:8000]}
        except Exception as e:
            return {"ok":False,"message":str(e)}

    elif atype == "send_socials":
        soc = {k:v for k,v in settings.get("socials",{}).items() if v and v.strip()}
        if not soc: return {"ok":False,"message":"No socials configured"}
        return {"ok":True,"message":"\n".join(f"{k}: {v}" for k,v in soc.items()),"display":True}

    elif atype == "search":
        q = action.get("query",target)
        url = f"https://www.google.com/search?q={q.replace(' ','+')}"
        webbrowser.open(url)
        return {"ok":True,"message":f"Searched: {q}"}

    return {"ok":False,"message":"Unknown action"}

# ── Screenshot + Vision ───────────────────────────────────────────────────
def take_screenshot() -> Optional[str]:
    try:
        import mss
        with mss.mss() as sct:
            mon = sct.monitors[1]
            img = sct.grab(mon)
            try:
                from PIL import Image
                pil = Image.frombytes("RGB",img.size,img.bgra,"raw","BGRX")
                if pil.width > 1280:
                    r = 1280/pil.width
                    pil = pil.resize((1280,int(pil.height*r)))
                buf = io.BytesIO(); pil.save(buf,"PNG",optimize=True)
                return base64.b64encode(buf.getvalue()).decode()
            except ImportError:
                raw = mss.tools.to_png(img.rgb,img.size)
                return base64.b64encode(raw).decode()
    except Exception:
        pass
    try:
        import pyautogui
        from PIL import Image
        img = pyautogui.screenshot()
        buf = io.BytesIO(); img.save(buf,"PNG",optimize=True)
        return base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return None

async def is_screen_request(text:str, api_key:str) -> bool:
    kw = ("screen","écran","mon écran","regarde","capture","screenshot","display","bureau","fenêtre")
    if any(k in text.lower() for k in kw):
        return True
    return False

async def call_vision(api_key:str, img_b64:str, msg:str, sys_prompt:str) -> str:
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(
                OPENROUTER_URL,
                headers={"Authorization":f"Bearer {api_key}","Content-Type":"application/json",
                         "HTTP-Referer":"https://kyrox.nemea.uk","X-Title":"Kyrox AI"},
                json={
                    "model":VISION_MODEL,
                    "messages":[
                        {"role":"system","content":sys_prompt},
                        {"role":"user","content":[
                            {"type":"image_url","image_url":{"url":f"data:image/png;base64,{img_b64}"}},
                            {"type":"text","text":msg or "Describe my screen in detail."}
                        ]}
                    ],
                    "max_tokens":1024,
                }
            )
            if r.status_code == 200:
                return r.json()["choices"][0]["message"]["content"]
            return f"Vision error {r.status_code}"
    except Exception as e:
        return f"Vision error: {e}"

# ── Auto-memory extraction ────────────────────────────────────────────────
MEMORY_PATTERNS = [
    (r"(?:my name is|i'm called|call me|je m'appelle|mon nom est)\s+(\w+)", "User's name is {}"),
    (r"i(?:'m| am)\s+(\d+)\s*(?:years?\s*old|ans?)", "User is {} years old"),
    (r"i\s+(?:love|like|enjoy|adore|j'aime)\s+([^,.!?\n]{3,40})", "User likes: {}"),
    (r"i\s+(?:hate|dislike|déteste)\s+([^,.!?\n]{3,40})", "User dislikes: {}"),
    (r"i\s+(?:live|am)\s+in\s+([^,.!?\n]{3,40})", "User lives in {}"),
    (r"i(?:'m| am)\s+(?:a\s+)?(?:developer|programmer|designer|student|engineer|gamer|streamer|artist)", "User is a {}"),
    (r"my\s+(?:favorite|fav)\s+\w+\s+is\s+([^,.!?\n]{2,30})", "User's favorite: {}"),
]
def extract_facts(text:str) -> list[str]:
    facts = []
    for pat, tmpl in MEMORY_PATTERNS:
        m = re.search(pat, text.lower())
        if m:
            val = m.group(1).strip().title() if m.lastindex else m.group(0).strip()
            facts.append(tmpl.format(val))
    return facts

# ── FastAPI app ────────────────────────────────────────────────────────────
app = FastAPI(title="Kyrox AI")
app.add_middleware(CORSMiddleware,allow_origins=["*"],allow_methods=["*"],allow_headers=["*"])
app.mount("/static",StaticFiles(directory=str(STATIC_DIR)),name="static")

# ── REST endpoints ─────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def index():
    return HTMLResponse((TEMPLATES_DIR/"index.html").read_text(encoding="utf-8"))

@app.get("/api/settings")
async def get_settings():
    s = load_settings()
    s["free_models"]   = FREE_MODELS
    s["current_model"] = FREE_MODELS[s.get("current_model_index",0) % len(FREE_MODELS)]
    return s

class SettingsIn(BaseModel):
    backend:            Optional[str]  = None
    openrouter_key:     Optional[str]  = None
    ollama_url:         Optional[str]  = None
    ollama_model:       Optional[str]  = None
    system_prompt:      Optional[str]  = None
    wakeword:           Optional[str]  = None
    tts:                Optional[bool] = None
    socials:            Optional[dict] = None
    apps:               Optional[dict] = None
    context_files:      Optional[list] = None

@app.post("/api/settings")
async def post_settings(body: SettingsIn):
    s = load_settings()
    update = body.model_dump(exclude_none=True)
    for k, v in update.items():
        if k in ("socials","apps") and isinstance(v,dict):
            s[k] = {**s.get(k,{}),**v}
        else:
            s[k] = v
    # re-scan context files if paths changed
    if "context_files" in update:
        s["context_text"] = scan_context_files(s.get("context_files",[]))
    save_settings(s)
    return {"ok":True,"settings":s}

@app.post("/api/action")
async def run_action(req: Request):
    body = await req.json()
    s = load_settings()
    return execute_pc_action(body.get("action",{}), s)

@app.get("/api/users")
async def get_users():
    return list_users()

@app.get("/api/history/{uid}")
async def get_history(uid:str):
    return load_history(uid)

@app.delete("/api/history/{uid}")
async def del_history(uid:str):
    save_history(uid,[])
    return {"ok":True}

@app.get("/api/memory/{uid}")
async def get_memory(uid:str):
    return load_memory(uid)

@app.post("/api/memory/{uid}")
async def post_memory(uid:str, req:Request):
    body = await req.json()
    m = load_memory(uid)
    if "facts"       in body: m["facts"]       = body["facts"]
    if "preferences" in body: m["preferences"] = {**m.get("preferences",{}),**body["preferences"]}
    save_memory(uid,m)
    return {"ok":True,"memory":m}

@app.get("/api/status")
async def get_status():
    s = load_settings()
    if s.get("backend") == "ollama":
        try:
            async with httpx.AsyncClient(timeout=3) as c:
                await c.get(f"{s['ollama_url']}/api/tags")
            return {"ok":True,"backend":"ollama","model":s.get("ollama_model")}
        except:
            return {"ok":False,"backend":"ollama","error":"Ollama offline"}
    has_key = bool(s.get("openrouter_key","").strip())
    idx = s.get("current_model_index",0)
    return {"ok":has_key,"backend":"openrouter",
            "model":FREE_MODELS[idx%len(FREE_MODELS)],"has_key":has_key}

@app.post("/api/scan-context")
async def scan_context(req:Request):
    body = await req.json()
    paths = body.get("paths",[])
    text = scan_context_files(paths)
    s = load_settings()
    s["context_files"] = paths
    s["context_text"]  = text
    save_settings(s)
    return {"ok":True,"chars":len(text),"preview":text[:200]}

# ── WebSocket chat ─────────────────────────────────────────────────────────
@app.websocket("/ws/chat/{uid}")
async def chat_ws(ws:WebSocket, uid:str):
    await ws.accept()

    history  = load_history(uid)
    settings = load_settings()

    # Send model info on connect
    idx = settings.get("current_model_index",0)
    await ws.send_text(json.dumps({"type":"model_info","model":FREE_MODELS[idx%len(FREE_MODELS)]}))

    try:
        while True:
            raw      = await ws.receive_text()
            payload  = json.loads(raw)
            action   = payload.get("action","chat")
            settings = load_settings()
            memory   = load_memory(uid)

            # ── Control actions ──────────────────────────────────────────
            if action == "clear":
                history = []
                save_history(uid,history)
                await ws.send_text(json.dumps({"type":"cleared"}))
                continue

            if action == "learn":
                fact = payload.get("fact","").strip()
                if fact and fact not in memory.get("facts",[]):
                    memory.setdefault("facts",[]).append(fact)
                    save_memory(uid,memory)
                await ws.send_text(json.dumps({"type":"learned"}))
                continue

            # ── Chat ─────────────────────────────────────────────────────
            user_msg = payload.get("message","").strip()
            if not user_msg:
                continue

            # Auto-extract memory facts
            new_facts = extract_facts(user_msg)
            changed = False
            for f in new_facts:
                if f not in memory.get("facts",[]):
                    memory.setdefault("facts",[]).append(f)
                    changed = True
            if changed:
                save_memory(uid,memory)
                await ws.send_text(json.dumps({"type":"learned"}))

            history.append({"role":"user","content":user_msg})

            # Build system prompt
            mem_ctx = memory_summary(memory)
            ctx_text = settings.get("context_text","")
            sys_prompt = settings["system_prompt"]
            if ctx_text:
                sys_prompt = f"[CONTEXT FILES — info about the user's PC/projects]:\n{ctx_text}\n\n" + sys_prompt
            if mem_ctx:
                sys_prompt = mem_ctx + "\n\n" + sys_prompt

            # ── Vision shortcut ──────────────────────────────────────────
            api_key = settings.get("openrouter_key","").strip()
            if (api_key and settings.get("backend","openrouter") == "openrouter"
                    and await is_screen_request(user_msg, api_key)):
                await ws.send_text(json.dumps({"type":"token","content":"📸 Capturing screen…\n\n"}))
                img = take_screenshot()
                if img is None:
                    err = "⚠ Couldn't capture screen. Install: pip install mss pillow"
                    await ws.send_text(json.dumps({"type":"done","content":err}))
                    history.append({"role":"assistant","content":err})
                    save_history(uid,history)
                    continue
                await ws.send_text(json.dumps({"type":"model_info","model":VISION_MODEL}))
                resp = await call_vision(api_key,img,user_msg,sys_prompt)
                history.append({"role":"assistant","content":resp})
                save_history(uid,history)
                await ws.send_text(json.dumps({"type":"done","content":resp}))
                continue

            # ── LLM call ─────────────────────────────────────────────────
            messages = [{"role":"system","content":sys_prompt}] + history[-24:]
            full_response = ""
            success = False

            if settings.get("backend","openrouter") == "openrouter":
                if not api_key:
                    await ws.send_text(json.dumps({"type":"error","content":"no_api_key"}))
                    history.pop()
                    continue

                idx   = settings.get("current_model_index",0)
                tried = 0
                while tried < len(FREE_MODELS):
                    model = FREE_MODELS[idx % len(FREE_MODELS)]
                    await ws.send_text(json.dumps({"type":"model_info","model":model}))
                    try:
                        async with httpx.AsyncClient(timeout=90) as client:
                            async with client.stream(
                                "POST", OPENROUTER_URL,
                                headers={"Authorization":f"Bearer {api_key}",
                                         "Content-Type":"application/json",
                                         "HTTP-Referer":"https://kyrox.nemea.uk",
                                         "X-Title":"Kyrox AI"},
                                json={"model":model,"messages":messages,"stream":True},
                            ) as resp:
                                if resp.status_code == 429:
                                    await ws.send_text(json.dumps({"type":"model_switch","from":model}))
                                    idx = (idx+1)%len(FREE_MODELS); tried += 1; continue
                                if resp.status_code != 200:
                                    idx = (idx+1)%len(FREE_MODELS); tried += 1; continue
                                async for line in resp.aiter_lines():
                                    if not line or not line.startswith("data:"): continue
                                    raw2 = line[5:].strip()
                                    if raw2 == "[DONE]": break
                                    try:
                                        chunk = json.loads(raw2)
                                    except: continue
                                    token = (chunk.get("choices",[{}])[0].get("delta",{}).get("content","")) or ""
                                    full_response += token
                                    if token:
                                        await ws.send_text(json.dumps({"type":"token","content":token}))
                                settings["current_model_index"] = idx%len(FREE_MODELS)
                                save_settings(settings)
                                success = True; break
                    except Exception:
                        idx = (idx+1)%len(FREE_MODELS); tried += 1

                if not success:
                    await ws.send_text(json.dumps({"type":"error","content":"All models rate-limited. Try again shortly."}))
                    history.pop(); continue

            else:  # Ollama
                try:
                    async with httpx.AsyncClient(timeout=120) as client:
                        async with client.stream(
                            "POST", f"{settings['ollama_url']}/api/chat",
                            json={"model":settings["ollama_model"],"messages":messages,"stream":True},
                        ) as resp:
                            async for line in resp.aiter_lines():
                                if not line: continue
                                try:
                                    chunk = json.loads(line)
                                except: continue
                                token = chunk.get("message",{}).get("content","")
                                full_response += token
                                if token:
                                    await ws.send_text(json.dumps({"type":"token","content":token}))
                    success = True
                except Exception as e:
                    await ws.send_text(json.dumps({"type":"error","content":f"Ollama error: {e}"}))
                    history.pop(); continue

            # Strip <think> blocks
            clean = re.sub(r"<think>.*?</think>","",full_response,flags=re.DOTALL).strip()

            # Parse action blocks
            action_pattern = re.compile(r"```action\s*(.*?)\s*```",re.DOTALL)
            actions_found  = []
            for m2 in action_pattern.finditer(clean):
                try: actions_found.append(json.loads(m2.group(1)))
                except: pass
            display = action_pattern.sub("",clean).strip()

            # Handle read_file inline
            for act in list(actions_found):
                if act.get("type") == "read_file":
                    res = execute_pc_action(act,settings)
                    await ws.send_text(json.dumps({"type":"actions","actions":[act]}))
                    if res.get("ok") and res.get("content"):
                        history.append({"role":"assistant","content":display})
                        history.append({"role":"user","content":f"[File: {act.get('path')}]\n{res['content']}"})
                    save_history(uid,history)
                    await ws.send_text(json.dumps({"type":"done","content":display}))
                    actions_found = [a for a in actions_found if a.get("type")!="read_file"]
                    break
            else:
                history.append({"role":"assistant","content":display})
                save_history(uid,history)
                if actions_found:
                    await ws.send_text(json.dumps({"type":"actions","actions":actions_found}))
                await ws.send_text(json.dumps({"type":"done","content":display}))

    except WebSocketDisconnect:
        pass
