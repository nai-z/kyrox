# kyrox

local ai companion. voice, wakeword, thinking traces. no cloud, no api keys.

runs on your phone or pc via ollama.

---

## install

**MACOS**

the command to install kyrox on macos is :

```bash
curl -fsSL https://raw.githubusercontent.com/nai-z/kyrox/main/install.sh | bash
```



**windows**

```powershell
irm https://raw.githubusercontent.com/nai-z/kyrox/main/install.ps1 | iex
```

installs python if you don't have it, adds `kyrox` to PATH, drops a shortcut on the desktop.

---


## features

- chat history, auto-saved
- say "hey kyrox" → it listens → answers out loud
- shows the model's `<think>` reasoning while it's working
- settings panel: swap models, edit the system prompt, change the wakeword, toggle tts
- works fine on android browser over localhost

---



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
