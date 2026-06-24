#!/usr/bin/env bash
# Kyrox Installer for macOS & Linux
# Usage: curl -fsSL kyrox.nemea.uk/install.sh | bash

set -e

KYROX_VERSION="1.0.0"
KYROX_DIR="$HOME/.kyrox"
KYROX_REPO="https://raw.githubusercontent.com/nai-z/kyrox/main"

RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
WHITE='\033[1;37m'
GRAY='\033[0;37m'
DIM='\033[2m'
NC='\033[0m'

print_header() {
    clear
    echo ""
    echo -e "${WHITE}  ██╗  ██╗██╗   ██╗██████╗  ██████╗ ██╗  ██╗${NC}"
    echo -e "${WHITE}  ██║ ██╔╝╚██╗ ██╔╝██╔══██╗██╔═══██╗╚██╗██╔╝${NC}"
    echo -e "${WHITE}  █████╔╝  ╚████╔╝ ██████╔╝██║   ██║ ╚███╔╝ ${NC}"
    echo -e "${WHITE}  ██╔═██╗   ╚██╔╝  ██╔══██╗██║   ██║ ██╔██╗ ${NC}"
    echo -e "${WHITE}  ██║  ██╗   ██║   ██║  ██║╚██████╔╝██╔╝ ██╗${NC}"
    echo -e "${WHITE}  ╚═╝  ╚═╝   ╚═╝   ╚═╝  ╚═╝ ╚═════╝ ╚═╝  ╚═╝${NC}"
    echo ""
    echo -e "${GRAY}  Your AI. Your Machine. Your Rules.${NC}"
    echo -e "${DIM}  Installer v${KYROX_VERSION}${NC}"
    echo ""
}

step()   { echo -e "${CYAN}  → $1${NC}"; }
ok()     { echo -e "${GREEN}  ✓ $1${NC}"; }
warn()   { echo -e "${YELLOW}  ⚠ $1${NC}"; }
fail()   { echo -e "${RED}  ✗ $1${NC}"; exit 1; }

print_header

OS="$(uname -s)"

# ── 1. Check Python ───────────────────────────────────────────────────────────
step "Checking Python..."

PYTHON=""
for cmd in python3 python; do
    if command -v "$cmd" &>/dev/null; then
        VER=$("$cmd" --version 2>&1 | grep -oP '3\.\K\d+')
        if [ -n "$VER" ] && [ "$VER" -ge 8 ]; then
            PYTHON="$cmd"
            ok "Python found: $($cmd --version)"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    warn "Python 3.8+ not found. Installing..."
    if [ "$OS" = "Darwin" ]; then
        if command -v brew &>/dev/null; then
            brew install python3
        else
            fail "Please install Homebrew (https://brew.sh) or Python 3.8+ manually."
        fi
    elif command -v apt-get &>/dev/null; then
        sudo apt-get update -qq && sudo apt-get install -y python3 python3-pip
    elif command -v dnf &>/dev/null; then
        sudo dnf install -y python3
    elif command -v pacman &>/dev/null; then
        sudo pacman -S --noconfirm python
    else
        fail "Could not auto-install Python. Please install Python 3.8+ manually."
    fi
    PYTHON="python3"
    ok "Python installed"
fi

# ── 2. Check Ollama ───────────────────────────────────────────────────────────
step "Checking Ollama..."

if command -v ollama &>/dev/null; then
    ok "Ollama found: $(ollama --version)"
else
    warn "Ollama not found. Installing..."
    curl -fsSL https://ollama.com/install.sh | sh
    ok "Ollama installed"
fi

# ── 3. Start Ollama if not running ────────────────────────────────────────────
step "Starting Ollama service..."

if curl -s http://localhost:11434/api/tags &>/dev/null; then
    ok "Ollama already running"
else
    ollama serve &>/dev/null &
    sleep 3
    ok "Ollama started"
fi

# ── 4. Pull default model ─────────────────────────────────────────────────────
step "Pulling default model (llama3.2 ~2GB)..."
echo -e "${DIM}  This may take a few minutes on first install.${NC}"
if ollama pull llama3.2; then
    ok "Model ready"
else
    warn "Could not pull model. You can download models from the Kyrox UI."
fi

# ── 5. Install Kyrox files ────────────────────────────────────────────────────
step "Installing Kyrox to $KYROX_DIR..."

mkdir -p "$KYROX_DIR/static"

curl -fsSL "$KYROX_REPO/kyrox.py" -o "$KYROX_DIR/kyrox.py"
curl -fsSL "$KYROX_REPO/static/index.html" -o "$KYROX_DIR/static/index.html"

chmod +x "$KYROX_DIR/kyrox.py"
ok "Kyrox files installed"

# ── 6. Register kyrox command ─────────────────────────────────────────────────
step "Registering 'kyrox' command..."

SCRIPT_PATH="/usr/local/bin/kyrox"
cat > /tmp/kyrox_cmd << EOF
#!/usr/bin/env bash
$PYTHON $KYROX_DIR/kyrox.py "\$@"
EOF

if [ -w "/usr/local/bin" ]; then
    mv /tmp/kyrox_cmd "$SCRIPT_PATH"
    chmod +x "$SCRIPT_PATH"
else
    sudo mv /tmp/kyrox_cmd "$SCRIPT_PATH"
    sudo chmod +x "$SCRIPT_PATH"
fi

ok "Command registered at $SCRIPT_PATH"

# ── Setup Ollama autostart (optional, macOS launchd / Linux systemd) ──────────
if [ "$OS" = "Darwin" ]; then
    PLIST="$HOME/Library/LaunchAgents/com.ollama.server.plist"
    if [ ! -f "$PLIST" ]; then
        cat > "$PLIST" << 'PLIST_EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>com.ollama.server</string>
    <key>ProgramArguments</key><array><string>/usr/local/bin/ollama</string><string>serve</string></array>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><true/>
    <key>StandardOutPath</key><string>/tmp/ollama.log</string>
    <key>StandardErrorPath</key><string>/tmp/ollama.err</string>
</dict>
</plist>
PLIST_EOF
        launchctl load "$PLIST" 2>/dev/null || true
        ok "Ollama set to start on login (macOS)"
    fi
fi

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo -e "${DIM}  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo -e "${WHITE}  Kyrox is installed!${NC}"
echo ""
echo -e "${GRAY}  Open a new terminal and type:${NC}"
echo ""
echo -e "${WHITE}      kyrox${NC}"
echo ""
echo -e "${GRAY}  Your browser will open at http://127.0.0.1/kyrox${NC}"
echo ""
echo -e "${DIM}  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

# Launch now?
echo -ne "${GRAY}  Launch Kyrox now? (Y/n): ${NC}"
read -r LAUNCH
if [[ "$LAUNCH" != "n" && "$LAUNCH" != "N" ]]; then
    echo ""
    echo -e "${CYAN}  Starting Kyrox...${NC}"
    "$PYTHON" "$KYROX_DIR/kyrox.py"
fi
