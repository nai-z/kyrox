# kyrox

local ai companion. voice, wakeword, thinking traces. no cloud, no api keys.

runs on your phone or pc via ollama.

---

## install

**android**

get [termux from f-droid](https://f-droid.org/packages/com.termux/) (not the play store one, it's outdated), then paste this:

```bash
curl -fsSL https://raw.githubusercontent.com/nai-z/kyrox/main/termux.sh | bash
```

opens at `http://localhost:8000`.

if ollama is slow to respond, run it in a separate termux session:

```bash
# tab 1
ollama serve

# tab 2
kyrox
```

**windows**

```powershell
irm https://raw.githubusercontent.com/nai-z/kyrox/main/install.ps1 | iex
```

installs python if you don't have it, adds `kyrox` to PATH, drops a shortcut on the desktop.

---

## usage

```bash
kyrox
```

open `http://localhost:8000`. that's it.

---

## features

- chat history, auto-saved
- say "hey kyrox" → it listens → answers out loud
- shows the model's `<think>` reasoning while it's working
- settings panel: swap models, edit the system prompt, change the wakeword, toggle tts
- works fine on android browser over localhost

---

## requirements

[ollama](https://ollama.com/download) running with at least one model:

```bash
ollama pull llama3.2
```

---

## files

```
kyrox/
├── core/main.py          fastapi + websocket + ollama streaming
├── templates/index.html  entire ui, one file
├── plugins/              empty for now
├── termux.sh             android installer
├── install.ps1           windows installer
└── settings.json         auto-created on first run
```

---

## roadmap

- [x] chat + history
- [x] wakeword, voice in/out
- [x] thinking traces
- [x] settings
- [ ] plugin system
- [ ] web search
- [ ] twitch chat

---

mit · [nai-z](https://github.com/nai-z)
