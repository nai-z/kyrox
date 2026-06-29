#!/usr/bin/env bash
# Kyrox Installer — nai-z/kyrox
# Usage: curl -fsSL https://raw.githubusercontent.com/nai-z/kyrox/main/install.sh | bash

set -euo pipefail

KYROX_VERSION="1.0.0"
REPO_URL="https://github.com/nai-z/kyrox"
RAW_URL="https://raw.githubusercontent.com/nai-z/kyrox/main"
INSTALL_DIR="$HOME/.local/share/kyrox"
BIN_DIR="$HOME/.local/bin"
PLIST_PATH="$HOME/Library/LaunchAgents/uk.nemea.kyrox.plist"

# ── Colours ────────────────────────────────────────────────────────────────
CYAN='\033[0;36m'; GREEN='\033[0;32m'; YELLOW='\033[0;33m'
RED='\033[0;31m'; MAGENTA='\033[0;35m'; GRAY='\033[0;90m'; RESET='\033[0m'; BOLD='\033[1m'

step()  { echo -e "  ${CYAN}->$RESET $1"; }
ok()    { echo -e "  ${GREEN}✔$RESET $1"; }
warn()  { echo -e "  ${YELLOW}!$RESET $1"; }
err()   { echo -e "  ${RED}✘$RESET $1"; exit 1; }

banner() {
  echo ""
  echo -e "${MAGENTA}  ██╗  ██╗██╗   ██╗██████╗  ██████╗ ██╗  ██╗${RESET}"
  echo -e "${MAGENTA}  ██║ ██╔╝╚██╗ ██╔╝██╔══██╗██╔═══██╗╚██╗██╔╝${RESET}"
  echo -e "${MAGENTA}  █████╔╝  ╚████╔╝ ██████╔╝██║   ██║ ╚███╔╝ ${RESET}"
  echo -e "${MAGENTA}  ██╔═██╗   ╚██╔╝  ██╔══██╗██║   ██║ ██╔██╗ ${RESET}"
  echo -e "${MAGENTA}  ██║  ██╗   ██║   ██║  ██║╚██████╔╝██╔╝ ██╗${RESET}"
  echo -e "${MAGENTA}  ╚═╝  ╚═╝   ╚═╝   ╚═╝  ╚═╝ ╚═════╝ ╚═╝  ╚═╝${RESET}"
  echo ""
  echo -e "  ${BOLD}AI Companion Installer v$KYROX_VERSION${RESET}"
  echo -e "  ${GRAY}$REPO_URL${RESET}"
  echo ""
}

# ── Check / install Python ─────────────────────────────────────────────────
ensure_python() {
  step "Checking Python..."
  if command -v python3 &>/dev/null; then
    local ver
    ver=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
    local major minor
    major=$(echo "$ver" | cut -d. -f1)
    minor=$(echo "$ver" | cut -d. -f2)
    if [ "$major" -ge 3 ] && [ "$minor" -ge 10 ]; then
      ok "Python $ver found"
      return
    fi
  fi

  step "Python 3.10+ not found. Installing via Homebrew..."
  if ! command -v brew &>/dev/null; then
    step "Installing Homebrew first..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)" || \
      err "Failed to install Homebrew. Install manually: https://brew.sh"
    # Add brew to PATH for Apple Silicon
    eval "$(/opt/homebrew/bin/brew shellenv 2>/dev/null || /usr/local/bin/brew shellenv 2>/dev/null || true)"
  fi
  brew install python@3.11 || err "Failed to install Python. Install manually: https://python.org/downloads"
  ok "Python installed"
}

# ── Check Ollama ───────────────────────────────────────────────────────────
check_ollama() {
  step "Checking Ollama..."
  if curl -sf http://localhost:11434/api/tags &>/dev/null; then
    ok "Ollama is running"
  else
    warn "Ollama not detected at localhost:11434"
    echo -e "  ${YELLOW}Get Ollama from: https://ollama.com/download${RESET}"
    echo -e "  ${YELLOW}Then run: ollama pull llama3${RESET}"
  fi
}

# ── Download project files ─────────────────────────────────────────────────
download_kyrox() {
  step "Setting up Kyrox in $INSTALL_DIR..."
  mkdir -p "$INSTALL_DIR"/{core,templates,static,plugins,skills,data}

  declare -A files=(
    ["core/main.py"]="core/main.py"
    ["templates/index.html"]="templates/index.html"
    ["requirements.txt"]="requirements.txt"
    ["lens.py"]="lens.py"
  )

  for remote in "${!files[@]}"; do
    local dest="$INSTALL_DIR/${files[$remote]}"
    curl -fsSL "$RAW_URL/$remote" -o "$dest" 2>/dev/null || \
      warn "Could not download $remote — skipping"
  done
  ok "Files downloaded"

  # ── Download skills ────────────────────────────────────────────────────
  step "Installing skills..."
  local skills=("frontend" "python" "javascript" "api" "debugging" "writing" "data")
  local count=0
  for skill in "${skills[@]}"; do
    if curl -fsSL "$RAW_URL/skills/$skill.md" -o "$INSTALL_DIR/skills/$skill.md" 2>/dev/null; then
      ((count++)) || true
    else
      warn "Could not download skill: $skill"
    fi
  done
  ok "$count skill(s) installed"
}

# ── Install Python deps ────────────────────────────────────────────────────
install_deps() {
  step "Installing Python dependencies..."
  local req="$INSTALL_DIR/requirements.txt"
  if [ -f "$req" ]; then
    python3 -m pip install -r "$req" --quiet --disable-pip-version-check
  else
    python3 -m pip install fastapi uvicorn httpx mss pillow pyautogui --quiet --disable-pip-version-check
  fi
  ok "Dependencies installed"
}

# ── Create kyrox launcher ──────────────────────────────────────────────────
create_launcher() {
  step "Creating 'kyrox' command..."
  mkdir -p "$BIN_DIR"

  cat > "$BIN_DIR/kyrox" << EOF
#!/usr/bin/env bash
echo ""
echo "  Starting Kyrox..."
echo "  Open in browser: http://127.0.0.1:8000"
echo "  From your phone (same WiFi): http://\$(hostname -f 2>/dev/null || hostname):8000"
echo "  Press Ctrl+C to stop"
echo ""
cd "$INSTALL_DIR"
# Launch Lens overlay in background if it exists
[ -f "$INSTALL_DIR/lens.py" ] && python3 "$INSTALL_DIR/lens.py" &>/dev/null &
python3 -m uvicorn core.main:app --host 0.0.0.0 --port 8000
EOF
  chmod +x "$BIN_DIR/kyrox"

  # Add BIN_DIR to PATH if needed
  local shell_rc=""
  if [ -f "$HOME/.zshrc" ]; then
    shell_rc="$HOME/.zshrc"
  elif [ -f "$HOME/.bash_profile" ]; then
    shell_rc="$HOME/.bash_profile"
  fi

  if [ -n "$shell_rc" ] && ! grep -q "$BIN_DIR" "$shell_rc" 2>/dev/null; then
    echo "" >> "$shell_rc"
    echo "export PATH=\"\$PATH:$BIN_DIR\"" >> "$shell_rc"
    export PATH="$PATH:$BIN_DIR"
    ok "'kyrox' command added to PATH (restart your terminal or run: source $shell_rc)"
  else
    export PATH="$PATH:$BIN_DIR"
    ok "'kyrox' command ready"
  fi
}

# ── LaunchAgent for auto-start ─────────────────────────────────────────────
create_launchagent() {
  step "Setting up auto-start on login..."
  mkdir -p "$HOME/Library/LaunchAgents"
  cat > "$PLIST_PATH" << EOF
<?xml version="1.0" encoding="UTF-8"?>
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
    <string>core.main:app</string>
    <string>--host</string>
    <string>0.0.0.0</string>
    <string>--port</string>
    <string>8000</string>
  </array>
  <key>WorkingDirectory</key>
  <string>$INSTALL_DIR</string>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <false/>
  <key>StandardOutPath</key>
  <string>$INSTALL_DIR/data/kyrox.log</string>
  <key>StandardErrorPath</key>
  <string>$INSTALL_DIR/data/kyrox.err</string>
</dict>
</plist>
EOF
  launchctl load "$PLIST_PATH" 2>/dev/null || true
  ok "Auto-start configured (LaunchAgent loaded)"
}

# ── Final summary ──────────────────────────────────────────────────────────
finish() {
  echo ""
  echo -e "  ${GRAY}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
  ok "Kyrox is installed!"
  echo ""
  echo -e "  ${BOLD}Next steps:${RESET}"
  echo -e "  1. Run: ${CYAN}kyrox${RESET}"
  echo -e "  2. Visit ${CYAN}http://127.0.0.1:8000${RESET} in your browser"
  echo -e "  3. On iPhone (same WiFi): ${CYAN}http://$(hostname):8000${RESET}"
  echo ""
  echo -e "  ${BOLD}Make sure Ollama is running with a model:${RESET}"
  echo -e "  ${GRAY}ollama pull llama3 && ollama serve${RESET}"
  echo -e "  ${GRAY}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
  echo ""

  printf "  Launch Kyrox now? (y/n) "
  read -r launch
  if [[ "$launch" =~ ^[Yy]$ ]]; then
    open "http://127.0.0.1:8000" 2>/dev/null || true
    kyrox
  fi
}

# ── Main ───────────────────────────────────────────────────────────────────
banner
ensure_python
check_ollama
download_kyrox
install_deps
create_launcher
create_launchagent
finish
