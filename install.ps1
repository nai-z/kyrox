# Kyrox Installer for Windows
# Usage: irm kyrox.nemea.uk/install.ps1 | iex

$ErrorActionPreference = "Stop"

$KYROX_VERSION = "1.0.0"
$KYROX_DIR = "$env:USERPROFILE\.kyrox"
$KYROX_REPO = "https://raw.githubusercontent.com/nai-z/kyrox/main"

function Write-Header {
    Clear-Host
    Write-Host ""
    Write-Host "  ██╗  ██╗██╗   ██╗██████╗  ██████╗ ██╗  ██╗" -ForegroundColor White
    Write-Host "  ██║ ██╔╝╚██╗ ██╔╝██╔══██╗██╔═══██╗╚██╗██╔╝" -ForegroundColor White
    Write-Host "  █████╔╝  ╚████╔╝ ██████╔╝██║   ██║ ╚███╔╝ " -ForegroundColor White
    Write-Host "  ██╔═██╗   ╚██╔╝  ██╔══██╗██║   ██║ ██╔██╗ " -ForegroundColor White
    Write-Host "  ██║  ██╗   ██║   ██║  ██║╚██████╔╝██╔╝ ██╗" -ForegroundColor White
    Write-Host "  ╚═╝  ╚═╝   ╚═╝   ╚═╝  ╚═╝ ╚═════╝ ╚═╝  ╚═╝" -ForegroundColor White
    Write-Host ""
    Write-Host "  Your AI. Your Machine. Your Rules." -ForegroundColor Gray
    Write-Host "  Installer v$KYROX_VERSION" -ForegroundColor DarkGray
    Write-Host ""
}

function Write-Step {
    param($msg)
    Write-Host "  → $msg" -ForegroundColor Cyan
}

function Write-OK {
    param($msg)
    Write-Host "  ✓ $msg" -ForegroundColor Green
}

function Write-Warn {
    param($msg)
    Write-Host "  ⚠ $msg" -ForegroundColor Yellow
}

function Write-Fail {
    param($msg)
    Write-Host "  ✗ $msg" -ForegroundColor Red
}

Write-Header

# ── 1. Check Python ──────────────────────────────────────────────────────────
Write-Step "Checking Python..."

$python = $null
foreach ($cmd in @("python", "python3", "py")) {
    try {
        $ver = & $cmd --version 2>&1
        if ($ver -match "Python 3\.(\d+)") {
            $minor = [int]$Matches[1]
            if ($minor -ge 8) {
                $python = $cmd
                Write-OK "Python found: $ver"
                break
            }
        }
    } catch {}
}

if (-not $python) {
    Write-Warn "Python 3.8+ not found. Installing via winget..."
    try {
        winget install -e --id Python.Python.3.11 --silent --accept-source-agreements --accept-package-agreements
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
        $python = "python"
        Write-OK "Python installed"
    } catch {
        Write-Fail "Could not auto-install Python."
        Write-Host "  Please install Python 3.8+ from https://python.org then re-run this installer." -ForegroundColor Gray
        exit 1
    }
}

# ── 2. Check Ollama ───────────────────────────────────────────────────────────
Write-Step "Checking Ollama..."

$ollamaInstalled = $false
try {
    $ollamaVer = & ollama --version 2>&1
    if ($ollamaVer -match "ollama") {
        $ollamaInstalled = $true
        Write-OK "Ollama found: $ollamaVer"
    }
} catch {}

if (-not $ollamaInstalled) {
    Write-Warn "Ollama not found. Downloading..."
    $ollamaInstaller = "$env:TEMP\OllamaSetup.exe"
    try {
        Invoke-WebRequest -Uri "https://ollama.com/download/OllamaSetup.exe" -OutFile $ollamaInstaller -UseBasicParsing
        Write-Step "Running Ollama installer (follow the prompts)..."
        Start-Process -FilePath $ollamaInstaller -Wait
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
        Write-OK "Ollama installed"
    } catch {
        Write-Fail "Could not download Ollama."
        Write-Host "  Please install manually from https://ollama.com" -ForegroundColor Gray
        exit 1
    }
}

# ── 3. Start Ollama if not running ────────────────────────────────────────────
Write-Step "Starting Ollama service..."
try {
    $response = Invoke-WebRequest -Uri "http://localhost:11434/api/tags" -UseBasicParsing -TimeoutSec 3 -ErrorAction SilentlyContinue
    Write-OK "Ollama already running"
} catch {
    Start-Process "ollama" -ArgumentList "serve" -WindowStyle Hidden
    Start-Sleep -Seconds 3
    Write-OK "Ollama started"
}

# ── 4. Pull default model ─────────────────────────────────────────────────────
Write-Step "Pulling default model (llama3.2 ~2GB)..."
Write-Host "  This may take a few minutes on first install." -ForegroundColor DarkGray
try {
    & ollama pull llama3.2
    Write-OK "Model ready"
} catch {
    Write-Warn "Could not pull model automatically. You can download models from the Kyrox UI."
}

# ── 5. Create Kyrox directory ─────────────────────────────────────────────────
Write-Step "Installing Kyrox to $KYROX_DIR..."

if (-not (Test-Path $KYROX_DIR)) {
    New-Item -ItemType Directory -Path $KYROX_DIR | Out-Null
}
if (-not (Test-Path "$KYROX_DIR\static")) {
    New-Item -ItemType Directory -Path "$KYROX_DIR\static" | Out-Null
}

# Download files
$files = @{
    "kyrox.py"           = "$KYROX_REPO/kyrox.py"
    "static/index.html"  = "$KYROX_REPO/static/index.html"
}

foreach ($file in $files.GetEnumerator()) {
    $dest = "$KYROX_DIR\$($file.Key)"
    Invoke-WebRequest -Uri $file.Value -OutFile $dest -UseBasicParsing
}

Write-OK "Kyrox files installed"

# ── 6. Create kyrox.bat command ───────────────────────────────────────────────
Write-Step "Registering 'kyrox' command..."

$batContent = "@echo off`n$python `"$KYROX_DIR\kyrox.py`" %*"
$batPath = "$KYROX_DIR\kyrox.bat"
Set-Content -Path $batPath -Value $batContent -Encoding ASCII

# Add to PATH if not already there
$userPath = [System.Environment]::GetEnvironmentVariable("Path", "User")
if ($userPath -notlike "*$KYROX_DIR*") {
    [System.Environment]::SetEnvironmentVariable("Path", "$userPath;$KYROX_DIR", "User")
    $env:Path += ";$KYROX_DIR"
}

Write-OK "Command registered"

# ── Done ──────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor DarkGray
Write-Host ""
Write-Host "  Kyrox is installed!" -ForegroundColor White
Write-Host ""
Write-Host "  Open a new terminal and type:" -ForegroundColor Gray
Write-Host ""
Write-Host "      kyrox" -ForegroundColor White
Write-Host ""
Write-Host "  Your browser will open at http://127.0.0.1/kyrox" -ForegroundColor Gray
Write-Host ""
Write-Host "  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor DarkGray
Write-Host ""

# Launch now?
$launch = Read-Host "  Launch Kyrox now? (Y/n)"
if ($launch -ne "n" -and $launch -ne "N") {
    Write-Host ""
    Write-Host "  Starting Kyrox..." -ForegroundColor Cyan
    & $python "$KYROX_DIR\kyrox.py"
}
