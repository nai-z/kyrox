cat > /mnt/user-data/outputs/kyrox.py << 'ENDOFFILE'
#!/usr/bin/env python3
"""
Kyrox - Your AI. Your Machine. Your Rules.
Local AI assistant with PC control + voice + file system access.
"""

import json
import os
import sys
import socket
import threading
import webbrowser
import time
import urllib.request
import urllib.parse
import urllib.error
import subprocess
import re
import glob
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

KYROX_DIR = Path(__file__).parent
STATIC_DIR = KYROX_DIR / "static"
CONFIG_FILE = KYROX_DIR / "config.json"

SYSTEM_PROMPT = """You are Kyrox — a sharp, no-nonsense local AI that runs entirely on the user's machine. No cloud, no tracking, no subscriptions. Just raw intelligence, offline.

Your personality:
- You speak like a smart friend who knows tech — casual but competent
- You're direct, never verbose. Get to the point.
- You refer to yourself as Kyrox, never "I am an AI" or "as a language model"
- You have a subtle confidence. You know what you're doing.
- You never say "Certainly!", "Of course!", "Sure!" — just do the thing.

When creating files or projects, you MUST ask the user which folder to use by outputting:
NEED_FOLDER:<reason why you need a folder>

Example: if user says "create a game", output:
NEED_FOLDER:I need a folder to save the game files

Once the user provides a folder path (they'll send it as FOLDER_PATH:/some/path), you can then use file actions.

When the user asks you to do something on their PC, output an ACTION block on its own line BEFORE your response:

ACTION:{"type": "open_app", "app": "chrome"}

Available actions:
- open_app: {"type": "open_app", "app": "chrome|notepad|explorer|spotify|discord|vscode|calc|cmd|powershell|paint|roblox|steam|vlc|word|excel"}
- web_search: {"type": "web_search", "query": "search query"}
- open_url: {"type": "open_url", "url": "https://..."}
- screenshot: {"type": "screenshot"}
- volume: {"type": "volume", "action": "up|down|mute"}
- media: {"type": "media", "action": "play_pause|next|prev"}
- run_command: {"type": "run_command", "command": "shell command"}
- close_app: {"type": "close_app", "app": "app name"}
- create_file: {"type": "create_file", "path": "/full/path/to/file.ext", "content": "file content here"}
- create_folder: {"type": "create_folder", "path": "/full/path/to/folder"}
- read_file: {"type": "read_file", "path": "/full/path/to/file"}
- list_folder: {"type": "list_folder", "path": "/full/path/to/folder"}

You can chain multiple files by outputting multiple ACTION lines.
Always put ACTION lines first, then your message.
If no action is needed, just respond — no ACTION block."""

DEFAULT_CONFIG = {
    "model": "llama3.2",
    "ollama_url": "http://localhost:11434",
    "port": 80,
    "temperature": 0.7,
    "system_prompt": SYSTEM_PROMPT,
}

AVAILABLE_MODELS = [
    {"id": "llama3.2",         "name": "Llama 3.2 3B",        "size": "2.0 GB",  "desc": "Fast & great for everyday tasks"},
    {"id": "llama3.2:1b",      "name": "Llama 3.2 1B",        "size": "1.3 GB",  "desc": "Ultra-fast, lightweight"},
    {"id": "llama3.1:8b",      "name": "Llama 3.1 8B",        "size": "4.7 GB",  "desc": "Balanced power and speed"},
    {"id": "mistral",          "name": "Mistral 7B",           "size": "4.1 GB",  "desc": "Sharp reasoning, great at instructions"},
    {"id": "gemma3:4b",        "name": "Gemma 3 4B",           "size": "3.3 GB",  "desc": "Google's efficient model"},
    {"id": "qwen2.5:7b",       "name": "Qwen 2.5 7B",          "size": "4.7 GB",  "desc": "Excellent multilingual support"},
    {"id": "qwen2.5-coder:7b", "name": "Qwen 2.5 Coder 7B",   "size": "4.7 GB",  "desc": "Best local coding assistant"},
    {"id": "deepseek-r1:7b",   "name": "DeepSeek R1 7B",       "size": "4.7 GB",  "desc": "Reasoning model with chain-of-thought"},
    {"id": "phi4-mini",        "name": "Phi-4 Mini 3.8B",      "size": "2.5 GB",  "desc": "Microsoft's fastest model"},
]

# ── App finder ──────────────────────────────────────────────────────────────
APP_MAP = {
    "chrome":        [r"C:\Program Files\Google\Chrome\Application\chrome.exe", "chrome"],
    "firefox":       ["firefox"],
    "edge":          [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe", "msedge"],
    "notepad":       ["notepad"],
    "wordpad":       ["wordpad"],
    "explorer":      ["explorer"],
    "calc":          ["calc"],
    "calculator":    ["calc"],
    "paint":         ["mspaint"],
    "cmd":           ["cmd", "/k"],
    "powershell":    ["powershell"],
    "discord":       [os.path.expandvars(r"%LOCALAPPDATA%\Discord\Update.exe"), "--processStart", "Discord.exe"],
    "spotify":       [os.path.expandvars(r"%APPDATA%\Spotify\Spotify.exe")],
    "roblox":        [os.path.expandvars(r"%LOCALAPPDATA%\Roblox\Versions\RobloxPlayerLauncher.exe")],
    "vscode":        ["code"],
    "vs code":       ["code"],
    "steam":         [r"C:\Program Files (x86)\Steam\steam.exe", "steam"],
    "vlc":           [r"C:\Program Files\VideoLAN\VLC\vlc.exe", "vlc"],
    "task manager":  ["taskmgr"],
    "word":          ["winword"],
    "excel":         ["excel"],
    "outlook":       ["outlook"],
    "obs":           [r"C:\Program Files\obs-studio\bin\64bit\obs64.exe", "obs64"],
}

def find_and_launch(app_name: str) -> str:
    """Try to launch an app, searching common paths if needed."""
    app_name = app_name.lower().strip()
    candidates = APP_MAP.get(app_name, [app_name])

    for candidate in candidates:
        candidate = os.path.expandvars(candidate)
        try:
            if os.path.isfile(candidate):
                subprocess.Popen([candidate], shell=False)
                return f"✓ Opened {app_name}"
            else:
                subprocess.Popen(candidate, shell=True)
                return f"✓ Opened {app_name}"
        except:
            continue

    # Last resort: search in common Program Files dirs
    search_dirs = [
        r"C:\Program Files",
        r"C:\Program Files (x86)",
        os.path.expandvars(r"%LOCALAPPDATA%"),
        os.path.expandvars(r"%APPDATA%"),
    ]
    for d in search_dirs:
        matches = glob.glob(os.path.join(d, "**", f"*{app_name}*.exe"), recursive=True)
        if matches:
            subprocess.Popen([matches[0]], shell=False)
            return f"✓ Opened {app_name} ({matches[0]})"

    return f"✗ Could not find {app_name}. Make sure it's installed."


# ── PC & File actions ────────────────────────────────────────────────────────
def execute_action(action: dict) -> dict:
    """Execute a PC/file action. Returns {result, data}."""
    atype = action.get("type", "")
    try:
        if atype == "open_app":
            app = action.get("app", "").lower()
            msg = find_and_launch(app)
            return {"result": msg}

        elif atype == "web_search":
            query = action.get("query", "")
            url = f"https://www.google.com/search?q={urllib.parse.quote(query)}"
            webbrowser.open(url)
            return {"result": f"✓ Searching: {query}"}

        elif atype == "open_url":
            url = action.get("url", "")
            webbrowser.open(url)
            return {"result": f"✓ Opened {url}"}

        elif atype == "screenshot":
            import datetime
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            path = str(Path.home() / "Desktop" / f"kyrox_{ts}.png")
            try:
                import PIL.ImageGrab
                PIL.ImageGrab.grab().save(path)
            except ImportError:
                subprocess.run(["powershell", "-command",
                    f"Add-Type -AssemblyName System.Windows.Forms,System.Drawing; "
                    f"$b=[System.Drawing.Bitmap]::new([System.Windows.Forms.Screen]::PrimaryScreen.Bounds.Width,[System.Windows.Forms.Screen]::PrimaryScreen.Bounds.Height); "
                    f"$g=[System.Drawing.Graphics]::FromImage($b); $g.CopyFromScreen(0,0,0,0,$b.Size); $b.Save('{path}')"], shell=True)
            return {"result": f"✓ Screenshot saved to Desktop"}

        elif atype == "volume":
            keys = {"up": 175, "down": 174, "mute": 173}
            k = keys.get(action.get("action", ""), 175)
            subprocess.run(["powershell", "-command",
                f"$o=New-Object -ComObject WScript.Shell; $o.SendKeys([char]{k})"], shell=True)
            return {"result": f"✓ Volume {action.get('action')}"}

        elif atype == "media":
            keys = {"play_pause": 179, "next": 176, "prev": 177}
            k = keys.get(action.get("action", ""), 179)
            subprocess.run(["powershell", "-command",
                f"$o=New-Object -ComObject WScript.Shell; $o.SendKeys([char]{k})"], shell=True)
            return {"result": f"✓ Media: {action.get('action')}"}

        elif atype == "run_command":
            command = action.get("command", "")
            subprocess.Popen(["cmd", "/c", command], shell=True)
            return {"result": f"✓ Ran: {command}"}

        elif atype == "close_app":
            app = action.get("app", "")
            subprocess.run(["taskkill", "/f", "/im", f"{app}.exe"], shell=True)
            return {"result": f"✓ Closed {app}"}

        elif atype == "create_file":
            path = action.get("path", "")
            content = action.get("content", "")
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            return {"result": f"✓ Created {Path(path).name}"}

        elif atype == "create_folder":
            path = action.get("path", "")
            Path(path).mkdir(parents=True, exist_ok=True)
            return {"result": f"✓ Created folder {path}"}

        elif atype == "read_file":
            path = action.get("path", "")
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            return {"result": f"✓ Read {Path(path).name}", "data": content}

        elif atype == "list_folder":
            path = action.get("path", "")
            items = list(Path(path).iterdir())
            files = [{"name": i.name, "type": "folder" if i.is_dir() else "file"} for i in items]
            return {"result": f"✓ Listed {path}", "data": files}

        return {"result": f"✗ Unknown action: {atype}"}

    except Exception as e:
        return {"result": f"✗ {atype} failed: {e}"}


def load_config():
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE) as f:
                cfg = json.load(f)
            for k, v in DEFAULT_CONFIG.items():
                if k not in cfg:
                    cfg[k] = v
            return cfg
        except:
            pass
    return DEFAULT_CONFIG.copy()


def save_config(cfg):
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)


def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "127.0.0.1"


def ollama_request(path, data=None, method="GET", ollama_url="http://localhost:11434"):
    url = ollama_url + path
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, method=method,
                                  headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read())
    except:
        return None


def get_installed_models(ollama_url):
    result = ollama_request("/api/tags", ollama_url=ollama_url)
    if result and "models" in result:
        return [m["name"] for m in result["models"]]
    return []


class KyroxHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def send_json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, path, content_type):
        try:
            with open(path, "rb") as f:
                data = f.read()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", len(data))
            self.end_headers()
            self.wfile.write(data)
        except FileNotFoundError:
            self.send_response(404)
            self.end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        cfg = load_config()
        p = self.path.rstrip("/")

        if p == "":
            self.send_response(302)
            self.send_header("Location", "/kyrox")
            self.end_headers()
        elif p == "/kyrox":
            self.send_file(STATIC_DIR / "index.html", "text/html; charset=utf-8")
        elif p == "/kyrox/api/config":
            installed = get_installed_models(cfg["ollama_url"])
            self.send_json({**cfg, "installed_models": installed, "available_models": AVAILABLE_MODELS})
        elif p == "/kyrox/api/models":
            installed = get_installed_models(cfg["ollama_url"])
            self.send_json({"available": AVAILABLE_MODELS, "installed": installed})
        elif p == "/kyrox/api/status":
            result = ollama_request("/api/tags", ollama_url=cfg["ollama_url"])
            self.send_json({"ollama": result is not None})
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length)) if length else {}
        cfg = load_config()

        if self.path == "/kyrox/api/config":
            for k in ["model", "system_prompt", "temperature", "ollama_url"]:
                if k in body:
                    cfg[k] = body[k]
            save_config(cfg)
            self.send_json({"ok": True})

        elif self.path == "/kyrox/api/action":
            action = body.get("action", {})
            result = execute_action(action)
            self.send_json(result)

        elif self.path == "/kyrox/api/chat":
            messages = body.get("messages", [])
            model = body.get("model", cfg["model"])
            system = body.get("system_prompt", cfg["system_prompt"])
            temperature = body.get("temperature", cfg["temperature"])

            payload = {
                "model": model,
                "messages": [{"role": "system", "content": system}] + messages,
                "stream": True,
                "options": {"temperature": temperature}
            }

            url = cfg["ollama_url"] + "/api/chat"
            req_body = json.dumps(payload).encode()
            req = urllib.request.Request(url, data=req_body, method="POST",
                                          headers={"Content-Type": "application/json"})

            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()

            full_response = ""

            try:
                with urllib.request.urlopen(req, timeout=120) as resp:
                    for line in resp:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            chunk = json.loads(line)
                            token = chunk.get("message", {}).get("content", "")
                            done = chunk.get("done", False)
                            full_response += token

                            if done:
                                # Execute all ACTION blocks
                                action_results = []
                                for match in re.finditer(r'ACTION:(\{[^}]+\})', full_response, re.DOTALL):
                                    try:
                                        action_data = json.loads(match.group(1))
                                        res = execute_action(action_data)
                                        action_results.append({"action": action_data, "result": res["result"]})
                                    except:
                                        pass

                                # Check for NEED_FOLDER
                                folder_match = re.search(r'NEED_FOLDER:(.+?)(?:\n|$)', full_response)
                                if folder_match:
                                    reason = folder_match.group(1).strip()
                                    evt = json.dumps({"need_folder": True, "reason": reason, "token": "", "done": False})
                                    self.wfile.write(f"data: {evt}\n\n".encode())
                                    self.wfile.flush()

                                if action_results:
                                    evt = json.dumps({"action_results": action_results, "token": "", "done": False})
                                    self.wfile.write(f"data: {evt}\n\n".encode())
                                    self.wfile.flush()

                            data = json.dumps({"token": token, "done": done})
                            self.wfile.write(f"data: {data}\n\n".encode())
                            self.wfile.flush()
                            if done:
                                break
                        except:
                            pass
            except Exception as e:
                err = json.dumps({"error": str(e), "done": True})
                self.wfile.write(f"data: {err}\n\n".encode())
                self.wfile.flush()

        elif self.path == "/kyrox/api/pull":
            model = body.get("model", "")
            if not model:
                self.send_json({"error": "No model specified"}, 400)
                return

            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()

            url = cfg["ollama_url"] + "/api/pull"
            req_body = json.dumps({"name": model, "stream": True}).encode()
            req = urllib.request.Request(url, data=req_body, method="POST",
                                          headers={"Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=3600) as resp:
                    for line in resp:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            chunk = json.loads(line)
                            data = json.dumps(chunk)
                            self.wfile.write(f"data: {data}\n\n".encode())
                            self.wfile.flush()
                        except:
                            pass
            except Exception as e:
                err = json.dumps({"error": str(e)})
                self.wfile.write(f"data: {err}\n\n".encode())

        elif self.path == "/kyrox/api/delete":
            model = body.get("model", "")
            result = ollama_request("/api/delete", {"name": model}, "DELETE", cfg["ollama_url"])
            self.send_json({"ok": result is not None})

        else:
            self.send_response(404)
            self.end_headers()


def main():
    cfg = load_config()
    port = cfg.get("port", 80)
    local_ip = get_local_ip()

    url_local   = f"http://127.0.0.1/kyrox" if port == 80 else f"http://127.0.0.1:{port}/kyrox"
    url_network = f"http://{local_ip}/kyrox"  if port == 80 else f"http://{local_ip}:{port}/kyrox"

    print("")
    print("  ██╗  ██╗██╗   ██╗██████╗  ██████╗ ██╗  ██╗")
    print("  ██║ ██╔╝╚██╗ ██╔╝██╔══██╗██╔═══██╗╚██╗██╔╝")
    print("  █████╔╝  ╚████╔╝ ██████╔╝██║   ██║ ╚███╔╝ ")
    print("  ██╔═██╗   ╚██╔╝  ██╔══██╗██║   ██║ ██╔██╗ ")
    print("  ██║  ██╗   ██║   ██║  ██║╚██████╔╝██╔╝ ██╗")
    print("  ╚═╝  ╚═╝   ╚═╝   ╚═╝  ╚═╝ ╚═════╝ ╚═╝  ╚═╝")
    print("")
    print("  Your AI. Your Machine. Your Rules.")
    print("")
    print(f"  → Local:   {url_local}")
    print(f"  → Network: {url_network}")
    print("")
    print("  Press Ctrl+C to stop.")
    print("")

    status = ollama_request("/api/tags", ollama_url=cfg["ollama_url"])
    if status is None:
        print("  ⚠  Ollama not detected. Make sure Ollama is running.")
        print("     Visit https://ollama.com to install it.")
        print("")

    server = HTTPServer(("0.0.0.0", port), KyroxHandler)

    def open_browser():
        time.sleep(0.8)
        webbrowser.open(url_local)

    threading.Thread(target=open_browser, daemon=True).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Kyrox stopped. Goodbye.\n")
        server.shutdown()


if __name__ == "__main__":
    main()
