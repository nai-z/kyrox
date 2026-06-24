#!/data/data/com.termux/files/usr/bin/bash
# ┌─────────────────────────────────────────────┐
# │  Kyrox — Termux Installer (Android)         │
# │  Usage: curl -fsSL <url>/termux.sh | bash   │
# └─────────────────────────────────────────────┘

set -e

# ── Colours ────────────────────────────────────────────────────────────────
C_PURPLE='\033[0;35m'
C_CYAN='\033[0;36m'
C_GREEN='\033[0;32m'
C_YELLOW='\033[1;33m'
C_RED='\033[0;31m'
C_GRAY='\033[0;90m'
C_RESET='\033[0m'
C_BOLD='\033[1m'

step()  { echo -e "${C_CYAN}  →  $1${C_RESET}"; }
ok()    { echo -e "${C_GREEN}  ✓  $1${C_RESET}"; }
warn()  { echo -e "${C_YELLOW}  ⚠  $1${C_RESET}"; }
err()   { echo -e "${C_RED}  ✗  $1${C_RESET}"; exit 1; }
info()  { echo -e "${C_GRAY}     $1${C_RESET}"; }

banner() {
echo ""
echo -e "${C_PURPLE}${C_BOLD}"
echo "  ██╗  ██╗██╗   ██╗██████╗  ██████╗ ██╗  ██╗"
echo "  ██║ ██╔╝╚██╗ ██╔╝██╔══██╗██╔═══██╗╚██╗██╔╝"
echo "  █████╔╝  ╚████╔╝ ██████╔╝██║   ██║ ╚███╔╝ "
echo "  ██╔═██╗   ╚██╔╝  ██╔══██╗██║   ██║ ██╔██╗ "
echo "  ██║  ██╗   ██║   ██║  ██║╚██████╔╝██╔╝ ██╗"
echo "  ╚═╝  ╚═╝   ╚═╝   ╚═╝  ╚═╝ ╚═════╝ ╚═╝  ╚═╝"
echo -e "${C_RESET}"
echo -e "  ${C_BOLD}Termux Installer — Android Edition${C_RESET}"
echo -e "  ${C_GRAY}github.com/nai-z/kyrox${C_RESET}"
echo ""
}

INSTALL_DIR="$HOME/kyrox"

# ── 1. Update Termux packages ──────────────────────────────────────────────
update_termux() {
  step "Updating Termux packages..."
  pkg update -y -q 2>/dev/null || true
  pkg upgrade -y -q 2>/dev/null || true
  ok "Termux updated"
}

# ── 2. Install system deps ─────────────────────────────────────────────────
install_system_deps() {
  step "Installing system packages..."
  pkg install -y -q python git curl openssl 2>/dev/null
  ok "System packages ready"
}

# ── 3. Install Ollama for Android/Termux ──────────────────────────────────
install_ollama() {
  step "Checking Ollama..."
  if command -v ollama &>/dev/null; then
    ok "Ollama already installed"
    return
  fi

  step "Installing Ollama..."
  # Termux-compatible Ollama install
  # Try the official linux arm64 binary (works on most Android devices)
  OLLAMA_URL="https://github.com/ollama/ollama/releases/latest/download/ollama-linux-arm64"
  OLLAMA_BIN="$PREFIX/bin/ollama"

  if curl -fsSL "$OLLAMA_URL" -o "$OLLAMA_BIN" 2>/dev/null; then
    chmod +x "$OLLAMA_BIN"
    ok "Ollama installed"
  else
    warn "Could not auto-install Ollama."
    info "Install manually: pkg install ollama"
    info "Or visit: https://ollama.com"
  fi
}

# ── 4. Pull default model ──────────────────────────────────────────────────
pull_model() {
  step "Checking for Ollama model..."
  # Start ollama in background for model pull
  ollama serve &>/dev/null &
  OLLAMA_PID=$!
  sleep 3

  if ollama list 2>/dev/null | grep -q "llama"; then
    ok "LLM model already present"
  else
    step "Pulling llama3.2 (small & fast, ~2GB)..."
    info "This may take a few minutes on first install..."
    ollama pull llama3.2 || warn "Model pull failed — you can run: ollama pull llama3.2"
  fi

  kill $OLLAMA_PID 2>/dev/null || true
}

# ── 5. Download Kyrox files ────────────────────────────────────────────────
download_kyrox() {
  step "Downloading Kyrox..."
  RAW="https://raw.githubusercontent.com/nai-z/kyrox/main"

  mkdir -p "$INSTALL_DIR/core"
  mkdir -p "$INSTALL_DIR/templates"
  mkdir -p "$INSTALL_DIR/static"
  mkdir -p "$INSTALL_DIR/plugins"

  FILES=(
    "core/main.py"
    "templates/index.html"
    "requirements.txt"
  )

  for f in "${FILES[@]}"; do
    dest="$INSTALL_DIR/$f"
    mkdir -p "$(dirname $dest)"
    if curl -fsSL "$RAW/$f" -o "$dest" 2>/dev/null; then
      info "Downloaded $f"
    else
      warn "Could not download $f (check internet / repo)"
    fi
  done

  ok "Kyrox files ready at $INSTALL_DIR"
}

# ── 6. Install Python deps ─────────────────────────────────────────────────
install_python_deps() {
  step "Installing Python dependencies..."
  pip install --quiet fastapi uvicorn httpx pydantic 2>/dev/null
  ok "Python packages installed"
}

# ── 7. Create kyrox launcher command ──────────────────────────────────────
create_launcher() {
  step "Creating 'kyrox' command..."

  cat > "$PREFIX/bin/kyrox" << 'LAUNCHER'
#!/data/data/com.termux/files/usr/bin/bash

KYROX_DIR="$HOME/kyrox"
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
GRAY='\033[0;90m'
RESET='\033[0m'
BOLD='\033[1m'

echo ""
echo -e "${PURPLE}${BOLD}  ✦ Kyrox is starting...${RESET}"
echo ""

# Start Ollama in background if not running
if ! curl -sf http://localhost:11434/api/tags >/dev/null 2>&1; then
  echo -e "${GRAY}  Starting Ollama...${RESET}"
  ollama serve &>/dev/null &
  sleep 3
fi

# Get local IP
LOCAL_IP=$(ip route get 1 2>/dev/null | awk '{print $7; exit}' || \
           ifconfig 2>/dev/null | grep 'inet ' | grep -v 127 | awk '{print $2}' | head -1)

echo -e "${CYAN}  ✦ Local:   http://localhost:8000${RESET}"
if [ -n "$LOCAL_IP" ]; then
  echo -e "${CYAN}  ✦ Network: http://$LOCAL_IP:8000${RESET}"
fi
echo -e "${GRAY}  Open the URL above in your browser${RESET}"
echo -e "${GRAY}  Press Ctrl+C to stop${RESET}"
echo ""

cd "$KYROX_DIR"
python -m uvicorn core.main:app --host 0.0.0.0 --port 8000
LAUNCHER

  chmod +x "$PREFIX/bin/kyrox"
  ok "'kyrox' command created"
}

# ── 8. Create auto-start alias ─────────────────────────────────────────────
create_alias() {
  step "Adding shell alias..."
  SHELL_RC="$HOME/.bashrc"
  if ! grep -q "alias kyrox=" "$SHELL_RC" 2>/dev/null; then
    echo "" >> "$SHELL_RC"
    echo "# Kyrox AI Companion" >> "$SHELL_RC"
    echo "alias kyrox='$PREFIX/bin/kyrox'" >> "$SHELL_RC"
  fi
  ok "Alias added to .bashrc"
}

# ── Done ───────────────────────────────────────────────────────────────────
print_done() {
  echo ""
  echo -e "${C_GRAY}  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${C_RESET}"
  echo -e "${C_GREEN}${C_BOLD}  ✓ Kyrox installed successfully!${C_RESET}"
  echo ""
  echo -e "${C_BOLD}  To start Kyrox:${C_RESET}"
  echo -e "${C_CYAN}     kyrox${C_RESET}"
  echo ""
  echo -e "${C_BOLD}  Then open in your browser:${C_RESET}"
  echo -e "${C_CYAN}     http://localhost:8000${C_RESET}"
  echo ""
  echo -e "${C_GRAY}  Tip: Run in two Termux sessions if needed.${C_RESET}"
  echo -e "${C_GRAY}  Session 1: ollama serve${C_RESET}"
  echo -e "${C_GRAY}  Session 2: kyrox${C_RESET}"
  echo -e "${C_GRAY}  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${C_RESET}"
  echo ""
}

# ── Ask to launch ──────────────────────────────────────────────────────────
ask_launch() {
  echo -ne "${C_PURPLE}  Launch Kyrox now? [y/n]: ${C_RESET}"
  read -r answer
  if [[ "$answer" == "y" || "$answer" == "Y" ]]; then
    kyrox
  else
    echo -e "${C_GRAY}  Run 'kyrox' anytime to start.${C_RESET}"
    echo ""
  fi
}

# ── Main ───────────────────────────────────────────────────────────────────
banner
update_termux
install_system_deps
install_ollama
pull_model
download_kyrox
install_python_deps
create_launcher
create_alias
print_done
ask_launch
