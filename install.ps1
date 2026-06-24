# Kyrox Installer — nai-z/kyrox
# Usage: irm https://raw.githubusercontent.com/nai-z/kyrox/main/install.ps1 | iex

$ErrorActionPreference = "Stop"
$KyroxVersion = "1.0.0"
$RepoUrl = "https://github.com/nai-z/kyrox"
$RawUrl = "https://raw.githubusercontent.com/nai-z/kyrox/main"
$InstallDir = "$env:LOCALAPPDATA\Kyrox"

# ── Colours ────────────────────────────────────────────────────────────────
function Write-Step($msg)  { Write-Host "  → $msg" -ForegroundColor Cyan }
function Write-Ok($msg)    { Write-Host "  ✓ $msg" -ForegroundColor Green }
function Write-Warn($msg)  { Write-Host "  ⚠ $msg" -ForegroundColor Yellow }
function Write-Err($msg)   { Write-Host "  ✗ $msg" -ForegroundColor Red }

function Write-Banner {
  Write-Host ""
  Write-Host "  ██╗  ██╗██╗   ██╗██████╗  ██████╗ ██╗  ██╗" -ForegroundColor Magenta
  Write-Host "  ██║ ██╔╝╚██╗ ██╔╝██╔══██╗██╔═══██╗╚██╗██╔╝" -ForegroundColor Magenta
  Write-Host "  █████╔╝  ╚████╔╝ ██████╔╝██║   ██║ ╚███╔╝ " -ForegroundColor Magenta
  Write-Host "  ██╔═██╗   ╚██╔╝  ██╔══██╗██║   ██║ ██╔██╗ " -ForegroundColor Magenta
  Write-Host "  ██║  ██╗   ██║   ██║  ██║╚██████╔╝██╔╝ ██╗" -ForegroundColor Magenta
  Write-Host "  ╚═╝  ╚═╝   ╚═╝   ╚═╝  ╚═╝ ╚═════╝ ╚═╝  ╚═╝" -ForegroundColor Magenta
  Write-Host ""
  Write-Host "  AI Companion Installer v$KyroxVersion" -ForegroundColor White
  Write-Host "  $RepoUrl" -ForegroundColor DarkGray
  Write-Host ""
}

# ── Check / install Python ─────────────────────────────────────────────────
function Ensure-Python {
  Write-Step "Checking Python..."
  try {
    $ver = python --version 2>&1
    if ($ver -match "Python (\d+)\.(\d+)") {
      $major = [int]$Matches[1]; $minor = [int]$Matches[2]
      if ($major -ge 3 -and $minor -ge 10) {
        Write-Ok "Python $($Matches[1]).$($Matches[2]) found"
        return
      }
    }
  } catch {}

  Write-Step "Python 3.10+ not found. Installing via winget..."
  try {
    winget install -e --id Python.Python.3.11 --accept-source-agreements --accept-package-agreements --silent
    # Refresh PATH
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
    Write-Ok "Python installed"
  } catch {
    Write-Err "Failed to install Python automatically."
    Write-Host "  Please install Python 3.10+ from https://python.org/downloads" -ForegroundColor Yellow
    exit 1
  }
}

# ── Check Ollama ───────────────────────────────────────────────────────────
function Check-Ollama {
  Write-Step "Checking Ollama..."
  try {
    $response = Invoke-WebRequest -Uri "http://localhost:11434/api/tags" -UseBasicParsing -TimeoutSec 3
    Write-Ok "Ollama is running"
    return $true
  } catch {
    Write-Warn "Ollama not detected at localhost:11434"
    Write-Host "  Get Ollama from: https://ollama.com/download" -ForegroundColor Yellow
    Write-Host "  Then run: ollama pull llama3" -ForegroundColor Yellow
    return $false
  }
}

# ── Download project files ─────────────────────────────────────────────────
function Download-Kyrox {
  Write-Step "Setting up Kyrox in $InstallDir..."
  New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
  New-Item -ItemType Directory -Force -Path "$InstallDir\core" | Out-Null
  New-Item -ItemType Directory -Force -Path "$InstallDir\templates" | Out-Null
  New-Item -ItemType Directory -Force -Path "$InstallDir\static" | Out-Null
  New-Item -ItemType Directory -Force -Path "$InstallDir\plugins" | Out-Null

  $files = @(
    @{ remote = "core/main.py";       local = "core\main.py" },
    @{ remote = "templates/index.html"; local = "templates\index.html" },
    @{ remote = "requirements.txt";   local = "requirements.txt" }
  )

  foreach ($f in $files) {
    $url = "$RawUrl/$($f.remote)"
    $dest = "$InstallDir\$($f.local)"
    try {
      Invoke-WebRequest -Uri $url -OutFile $dest -UseBasicParsing
    } catch {
      Write-Warn "Could not download $($f.remote) — skipping (may already exist)"
    }
  }
  Write-Ok "Files downloaded"
}

# ── Install Python deps ────────────────────────────────────────────────────
function Install-Deps {
  Write-Step "Installing Python dependencies..."
  $req = "$InstallDir\requirements.txt"
  if (Test-Path $req) {
    python -m pip install -r $req --quiet --disable-pip-version-check
  } else {
    python -m pip install fastapi uvicorn httpx --quiet --disable-pip-version-check
  }
  Write-Ok "Dependencies installed"
}

# ── Create kyrox.cmd launcher ──────────────────────────────────────────────
function Create-Launcher {
  Write-Step "Creating 'kyrox' command..."
  $launcherDir = "$env:LOCALAPPDATA\Programs\Kyrox"
  New-Item -ItemType Directory -Force -Path $launcherDir | Out-Null

  $cmd = @"
@echo off
echo.
echo   ✦ Starting Kyrox...
echo   ✦ Open in browser: http://127.0.0.1:8000
echo   ✦ From your phone: http://%COMPUTERNAME%:8000
echo   ✦ Press Ctrl+C to stop
echo.
python -m uvicorn core.main:app --host 0.0.0.0 --port 8000 --reload
"@
  $cmdPath = "$launcherDir\kyrox.cmd"
  Set-Content -Path $cmdPath -Value $cmd -Encoding ASCII

  # Also create a .ps1 version
  $ps1 = @"
Set-Location "$InstallDir"
Write-Host "`n  ✦ Starting Kyrox..." -ForegroundColor Magenta
Write-Host "  ✦ Open in browser: http://127.0.0.1:8000" -ForegroundColor Cyan
Write-Host "  ✦ From your phone (same WiFi): http://`$(hostname):8000" -ForegroundColor Cyan
Write-Host "  ✦ Press Ctrl+C to stop`n" -ForegroundColor DarkGray
Set-Location "$InstallDir"
python -m uvicorn core.main:app --host 0.0.0.0 --port 8000
"@
  Set-Content -Path "$launcherDir\kyrox.ps1" -Value $ps1 -Encoding UTF8

  # Add to user PATH if not already there
  $userPath = [System.Environment]::GetEnvironmentVariable("Path","User")
  if ($userPath -notlike "*$launcherDir*") {
    [System.Environment]::SetEnvironmentVariable(
      "Path", "$userPath;$launcherDir", "User"
    )
    $env:Path += ";$launcherDir"
    Write-Ok "'kyrox' command added to PATH"
  } else {
    Write-Ok "'kyrox' already in PATH"
  }
}

# ── Shortcut on Desktop ────────────────────────────────────────────────────
function Create-Shortcut {
  Write-Step "Creating desktop shortcut..."
  try {
    $desktop = [Environment]::GetFolderPath("Desktop")
    $wsh = New-Object -ComObject WScript.Shell
    $sc = $wsh.CreateShortcut("$desktop\Kyrox.lnk")
    $sc.TargetPath = "cmd.exe"
    $sc.Arguments = "/k kyrox"
    $sc.WorkingDirectory = $InstallDir
    $sc.IconLocation = "shell32.dll,13"
    $sc.Description = "Launch Kyrox AI Companion"
    $sc.Save()
    Write-Ok "Desktop shortcut created"
  } catch {
    Write-Warn "Could not create desktop shortcut (non-critical)"
  }
}

# ── Launch ─────────────────────────────────────────────────────────────────
function Launch-Kyrox {
  Write-Host ""
  Write-Host "  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor DarkGray
  Write-Ok "Kyrox is installed!"
  Write-Host ""
  Write-Host "  Next steps:" -ForegroundColor White
  Write-Host "  1. Open a new terminal and run: kyrox" -ForegroundColor Cyan
  Write-Host "  2. Visit http://127.0.0.1:8000 in your browser" -ForegroundColor Cyan
  Write-Host "  3. On Android (same WiFi): http://$(hostname):8000" -ForegroundColor Cyan
  Write-Host ""
  Write-Host "  Make sure Ollama is running with a model:" -ForegroundColor White
  Write-Host "  ollama pull llama3 && ollama serve" -ForegroundColor DarkGray
  Write-Host "  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor DarkGray
  Write-Host ""

  $launch = Read-Host "  Launch Kyrox now? (y/n)"
  if ($launch -eq "y" -or $launch -eq "Y") {
    Set-Location $InstallDir
    Start-Process "http://127.0.0.1:8000" -ErrorAction SilentlyContinue
    python -m uvicorn core.main:app --host 0.0.0.0 --port 8000
  }
}

# ── Main ───────────────────────────────────────────────────────────────────
Write-Banner
Ensure-Python
Check-Ollama | Out-Null
Download-Kyrox
Install-Deps
Create-Launcher
Create-Shortcut
Launch-Kyrox
