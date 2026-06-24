#!/usr/bin/env python3
"""
Kyrox - Your AI. Your Machine. Your Rules.
Local AI chat server powered by Ollama.
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
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

KYROX_DIR = Path(__file__).parent
STATIC_DIR = KYROX_DIR / "static"
CONFIG_FILE = KYROX_DIR / "config.json"

DEFAULT_CONFIG = {
    "model": "llama3.2",
    "ollama_url": "http://localhost:11434",
    "port": 80,
    "system_prompt": "You are Kyrox, a fast and private local AI assistant. You run entirely on the user's machine — no cloud, no tracking, no subscriptions. Be helpful, direct, and concise.",
    "temperature": 0.7,
}

AVAILABLE_MODELS = [
    {"id": "llama3.2",         "name": "Llama 3.2 3B",        "size": "2.0 GB",  "desc": "Fast & great for everyday tasks"},
    {"id": "llama3.2:1b",      "name": "Llama 3.2 1B",        "size": "1.3 GB",  "desc": "Ultra-fast, lightweight"},
    {"id": "llama3.1:8b",      "name": "Llama 3.1 8B",        "size": "4.7 GB",  "desc": "Balanced power and speed"},
    {"id": "llama3.1:70b",     "name": "Llama 3.1 70B",       "size": "40 GB",   "desc": "Most powerful Llama — needs 48GB RAM"},
    {"id": "mistral",          "name": "Mistral 7B",           "size": "4.1 GB",  "desc": "Sharp reasoning, great at instructions"},
    {"id": "mistral-nemo",     "name": "Mistral Nemo 12B",     "size": "7.1 GB",  "desc": "Longer context, very capable"},
    {"id": "gemma3:4b",        "name": "Gemma 3 4B",           "size": "3.3 GB",  "desc": "Google's efficient model"},
    {"id": "gemma3:12b",       "name": "Gemma 3 12B",          "size": "8.1 GB",  "desc": "Google's powerful model"},
    {"id": "gemma3:27b",       "name": "Gemma 3 27B",          "size": "17 GB",   "desc": "Google's best — needs 24GB RAM"},
    {"id": "qwen2.5:7b",       "name": "Qwen 2.5 7B",          "size": "4.7 GB",  "desc": "Excellent multilingual support"},
    {"id": "qwen2.5:14b",      "name": "Qwen 2.5 14B",         "size": "9.0 GB",  "desc": "Strong coder and reasoner"},
    {"id": "qwen2.5:32b",      "name": "Qwen 2.5 32B",         "size": "20 GB",   "desc": "Top-tier open model"},
    {"id": "qwen2.5-coder:7b", "name": "Qwen 2.5 Coder 7B",   "size": "4.7 GB",  "desc": "Best local coding assistant"},
    {"id": "deepseek-r1:7b",   "name": "DeepSeek R1 7B",       "size": "4.7 GB",  "desc": "Reasoning model with chain-of-thought"},
    {"id": "deepseek-r1:14b",  "name": "DeepSeek R1 14B",      "size": "9.0 GB",  "desc": "Powerful reasoning — thinks before answering"},
    {"id": "deepseek-r1:32b",  "name": "DeepSeek R1 32B",      "size": "20 GB",   "desc": "Elite reasoning model"},
    {"id": "phi4",             "name": "Phi-4 14B",             "size": "9.1 GB",  "desc": "Microsoft's compact powerhouse"},
    {"id": "phi4-mini",        "name": "Phi-4 Mini 3.8B",      "size": "2.5 GB",  "desc": "Microsoft's fastest model"},
    {"id": "command-r",        "name": "Command R 35B",         "size": "20 GB",   "desc": "Cohere's model, great at RAG & search"},
    {"id": "solar-pro",        "name": "Solar Pro 22B",         "size": "13 GB",   "desc": "Upstage's top performer"},
    {"id": "falcon3:7b",       "name": "Falcon 3 7B",           "size": "4.5 GB",  "desc": "TII's efficient open model"},
    {"id": "vicuna",           "name": "Vicuna 7B",             "size": "3.8 GB",  "desc": "Classic fine-tuned Llama"},
    {"id": "openchat",         "name": "OpenChat 7B",           "size": "4.1 GB",  "desc": "High-quality chat model"},
    {"id": "neural-chat",      "name": "Neural Chat 7B",        "size": "4.1 GB",  "desc": "Intel-optimized chat model"},
    {"id": "starling-lm",      "name": "Starling LM 7B",        "size": "4.1 GB",  "desc": "RLHF-trained, follows instructions well"},
    {"id": "codellama:7b",     "name": "Code Llama 7B",         "size": "3.8 GB",  "desc": "Meta's dedicated code model"},
    {"id": "codellama:13b",    "name": "Code Llama 13B",        "size": "7.4 GB",  "desc": "Stronger coding — Python, JS, C++"},
    {"id": "starcoder2:7b",    "name": "StarCoder2 7B",         "size": "4.0 GB",  "desc": "BigCode's open coding model"},
    {"id": "nomic-embed-text", "name": "Nomic Embed",           "size": "274 MB",  "desc": "Text embeddings for search/RAG"},
]


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

        # Redirect root to /kyrox
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
