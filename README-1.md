# KYROX AI

**Your AI. Your Machine. Your Rules.**

Kyrox AI runs entirely on your computer. No cloud. No subscriptions. No one reading your conversations.

---

## Install

### Windows
```powershell
irm https://raw.githubusercontent.com/YOURUSERNAME/kyrox/main/install.ps1 | iex
```

### macOS / Linux
```bash
curl -fsSL https://raw.githubusercontent.com/YOURUSERNAME/kyrox/main/install.sh | bash
```

Then open a new terminal and type:
```
kyrox
```

Your browser opens at `http://127.0.0.1/kyrox`.

---

## What it does

- Runs a local web server on your machine
- Opens the Kyrox chat UI in your browser
- Connects to [Ollama](https://ollama.com) to run AI models locally
- **29 models** available — from tiny 1B to massive 70B
- Download, switch, and delete models from the UI
- Configurable system prompt, temperature, and more
- Works on your local network — share with other devices on the same WiFi

---

## Requirements

- Python 3.8+
- [Ollama](https://ollama.com) (auto-installed by the installer)
- ~2GB disk space for the default model (llama3.2)

---

## Models included

| Model | Size | Notes |
|-------|------|-------|
| Llama 3.2 3B | 2.0 GB | Default — fast & capable |
| Llama 3.2 1B | 1.3 GB | Ultra-fast, lightweight |
| Llama 3.1 8B | 4.7 GB | Balanced |
| Mistral 7B | 4.1 GB | Sharp reasoning |
| Gemma 3 12B | 8.1 GB | Google's model |
| Qwen 2.5 14B | 9.0 GB | Multilingual |
| DeepSeek R1 7B | 4.7 GB | Reasoning / CoT |
| Phi-4 Mini 3.8B | 2.5 GB | Microsoft, fast |
| Qwen 2.5 Coder 7B | 4.7 GB | Best local coder |
| Code Llama 13B | 7.4 GB | Meta's coder |
| + 19 more... | | Available in Models tab |

---

## Running manually

```bash
python ~/.kyrox/kyrox.py
# Windows:
python %USERPROFILE%\.kyrox\kyrox.py
```

---

## Config

Settings stored at `~/.kyrox/config.json`. Edit from the UI under **Settings**.

```json
{
  "model": "llama3.2",
  "ollama_url": "http://localhost:11434",
  "port": 80,
  "system_prompt": "You are Kyrox...",
  "temperature": 0.7
}
```

---

Made by [Nemea](https://nemea.uk) · Part of the [Kyrox](https://kyrox.nemea.uk) ecosystem
