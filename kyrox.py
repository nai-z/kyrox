#!/usr/bin/env python3
"""
Kyrox - Your AI. Your Machine. Your Rules.
Local AI assistant with PC control + voice recognition.
"""

import json
import os
import sys
import socket
import threading
import webbrowser
import time
import urllib.request
import urllib.error
import subprocess
import platform
import re
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

KYROX_DIR = Path(__file__).parent
STATIC_DIR = KYROX_DIR / "static"
CONFIG_FILE = KYROX_DIR / "config.json"

DEFAULT_CONFIG = {
    "model": "llama3.2",
    "ollama_url": "http://localhost:11434",
    "port": 80,
    "temperature": 0.7,
    "system_prompt": (
        "You are Kyrox, a fast and private local AI assistant that also controls the user's PC. "
        "You run entirely on the user's machine — no cloud, no tracking, no subscriptions.\n\n"
        "When the user asks you to do something on their PC (open an app, search the web, take a screenshot, etc.), "
        "you MUST respond with a JSON action block like this, on its own line:\n"
        "ACTION:{\"type\": \"open_app\", \"app\": \"chrome\"}\n\n"
        "Available action types:\n"
        "- open_app: {\"type\": \"open_app\", \"app\": \"chrome|notepad|explorer|spotify|discord|vscode|calc|cmd|powershell|paint|wordpad\"}\n"
        "- web_search: {\"type\": \"web_search\", \"query\": \"your search query\"}\n"
        "- open_url: {\"type\": \"open_url\", \"url\": \"https://example.com\"}\n"
        "- screenshot: {\"type\": \"screenshot\"}\n"
        "- volume: {\"type\": \"volume\", \"action\": \"up|down|mute\"}\n"
        "- media: {\"type\": \"media\", \"action\": \"play_pause|next|prev\"}\n"
        "- type_text: {\"type\": \"type_text\", \"text\": \"text to type\"}\n"
        "- run_command: {\"type\": \"run_command\", \"command\": \"shell command here\"}\n"
        "- close_app: {\"type\": \"close_app\", \"app\": \"app name\"}\n\n"
        "Always put the ACTION line first, then your normal response. "
        "If no PC action is needed, just respond normally without any ACTION block."
    ),
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

# ── App name → executable mapping ──────────────────────────────────────────────
APP_MAP = {
    "chrome":       ["chrome", "google-chrome", r"C:\Program Files\Google\Chrome\Application\chrome.exe"],
    "firefox":      ["firefox"],
    "edge":         ["msedge", r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"],
    "notepad":      ["notepad"],
    "wordpad":      ["wordpad"],
    "explorer":     ["explorer"],
    "calc":         ["calc"],
    "calculator":   ["calc"],
    "paint":        ["mspaint"],
    "cmd":          ["cmd", "/k"],
    "powershell":   ["powershell"],
    "discord":      ["discord", r"%LOCALAPPDATA%\Discord\Update.exe", "--processStart", "Discord.exe"],
    "spotify":      ["spotify", r"%APPDATA%\Spotify\Spotify.exe"],
    "vscode":       ["code"],
    "vs code":      ["code"],
    "steam":        ["steam", r"C:\Program Files (x86)\Steam\steam.exe"],
    "vlc":          ["vlc"],
    "task manager": ["taskmgr"],
    "taskmgr":      ["taskmgr"],
    "snipping tool":["snippingtool"],
    "word":         ["winword"],
    "excel":        ["excel"],
    "outlook":      ["outlook"],
}


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


# ── PC CONTROL ─────────────────────────────────────────────────────────────────

def execute_action(action: dict) -> str:
    """Execute a PC action and return a status string."""
    atype = action.get("type", "")

    try:
        if atype == "open_app":
            app = action.get("app", "").lower()
            cmds = APP_MAP.get(app, [app])
            subprocess.Popen(cmds, shell=True)
            return f"✓ Opened {app}"

        elif atype == "web_search":
            query = action.get("query", "")
            url = f"https://www.google.com/search?q={urllib.parse.quote(query)}"
            webbrowser.open(url)
            return f"✓ Searching: {query}"

        elif atype == "open_url":
            url = action.get("url", "")
            webbrowser.open(url)
            return f"✓ Opened {url}"

        elif atype == "screenshot":
            import datetime
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            path = str(Path.home() / "Desktop" / f"kyrox_screenshot_{ts}.png")
            # Try multiple methods
            try:
                import PIL.ImageGrab
                img = PIL.ImageGrab.grab()
                img.save(path)
            except ImportError:
                subprocess.run(
                    ["powershell", "-command",
                     f"Add-Type -AssemblyName System.Windows.Forms; "
                     f"[System.Windows.Forms.Screen]::PrimaryScreen | Out-Null; "
                     f"$bmp = [System.Drawing.Bitmap]::new([System.Windows.Forms.Screen]::PrimaryScreen.Bounds.Width, [System.Windows.Forms.Screen]::PrimaryScreen.Bounds.Height); "
                     f"$g = [System.Drawing.Graphics]::FromImage($bmp); "
                     f"$g.CopyFromScreen(0,0,0,0,$bmp.Size); "
                     f"$bmp.Save('{path}')"],
                    shell=True
                )
            return f"✓ Screenshot saved to Desktop"

        elif atype == "volume":
            vol_action = action.get("action", "")
            if vol_action == "up":
                subprocess.run(["powershell", "-command",
                    "$obj = New-Object -ComObject WScript.Shell; $obj.SendKeys([char]175)"], shell=True)
            elif vol_action == "down":
                subprocess.run(["powershell", "-command",
                    "$obj = New-Object -ComObject WScript.Shell; $obj.SendKeys([char]174)"], shell=True)
            elif vol_action == "mute":
                subprocess.run(["powershell", "-command",
                    "$obj = New-Object -ComObject WScript.Shell; $obj.SendKeys([char]173)"], shell=True)
            return f"✓ Volume {vol_action}"

        elif atype == "media":
            med_action = action.get("action", "")
            key_map = {"play_pause": 179, "next": 176, "prev": 177}
            key = key_map.get(med_action, 179)
            subprocess.run(["powershell", "-command",
                f"$obj = New-Object -ComObject WScript.Shell; $obj.SendKeys([char]{key})"], shell=True)
            return f"✓ Media: {med_action}"

        elif atype == "type_text":
            text = action.get("text", "")
            subprocess.run(["powershell", "-command",
                f"$obj = New-Object -ComObject WScript.Shell; $obj.SendKeys('{text}')"], shell=True)
            return f"✓ Typed text"

        elif atype == "run_command":
            command = action.get("command", "")
            subprocess.Popen(["cmd", "/c", command], shell=True)
            return f"✓ Ran: {command}"

        elif atype == "close_app":
            app = action.get("app", "")
            subprocess.run(["taskkill", "/f", "/im", f"{app}.exe"], shell=True)
            return f"✓ Closed {app}"

        return f"Unknown action: {atype}"

    except Exception as e:
        return f"✗ Action failed: {e}"


# Add urllib.parse import
import urllib.parse


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
            # Direct action execution endpoint
            action = body.get("action", {})
            result = execute_action(action)
            self.send_json({"result": result})

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

                            # Check for ACTION block and execute it
                            if "ACTION:" in full_response and done:
                                action_match = re.search(r'ACTION:(\{.*?\})', full_response, re.DOTALL)
                                if action_match:
                                    try:
                                        action_data = json.loads(action_match.group(1))
                                        action_result = execute_action(action_data)
                                        # Send action result as special event
                                        action_event = json.dumps({
                                            "action_result": action_result,
                                            "action": action_data,
                                            "token": "",
                                            "done": False
                                        })
                                        self.wfile.write(f"data: {action_event}\n\n".encode())
                                        self.wfile.flush()
                                        # Remove ACTION line from response
                                        full_response = re.sub(r'ACTION:\{.*?\}\n?', '', full_response, flags=re.DOTALL)
                                    except:
                                        pass

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


def check_voice_deps():
    """Check if voice recognition dependencies are installed."""
    try:
        import speech_recognition
        return True
    except ImportError:
        return False


def install_voice_deps():
    """Install voice recognition dependencies."""
    print("  Installing voice recognition dependencies...")
    subprocess.run([sys.executable, "-m", "pip", "install", "SpeechRecognition", "pyaudio"], check=True)
    print("  ✓ Voice deps installed")


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

    has_voice = check_voice_deps()
    if has_voice:
        print("  🎤 Voice recognition: ready")
    else:
        print("  🎤 Voice recognition: not installed (install with: pip install SpeechRecognition pyaudio)")
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
