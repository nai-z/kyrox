import os
import sys
import time
import threading
import queue
import math
import tkinter as tk

# Optional dependencies (best-effort)
try:
    import pyautogui  # type: ignore
except Exception:
    pyautogui = None

try:
    import speech_recognition as sr  # type: ignore
except Exception:
    sr = None

try:
    import keyboard  # type: ignore
except Exception:
    keyboard = None


# -----------------------------
# Config
# -----------------------------
APP_NAME = "Kyrox Talk Orb Agent"

# Hotkey: Ctrl+Alt+Space
HOTKEY_COMBO = ("ctrl", "alt", "space")

# Audio listening behavior
SILENCE_GAP_SEC = float(os.environ.get("KYROX_SILENCE_GAP", "1.2"))
ENERGY_THRESHOLD = int(os.environ.get("KYROX_ENERGY", "300"))

# Safety switches
ENABLE_AUTOMATION = os.environ.get("KYROX_ENABLE_AUTOMATION", "1") == "1"
ENABLE_VOICE = os.environ.get("KYROX_ENABLE_VOICE", "1") == "1"

# UI/animation
TICK_MS = 16  # ~60 FPS
DRIFT_SPEED = float(os.environ.get("KYROX_DRIFT_SPEED", "0.65"))

# Sphere visual
BASE_SIZE = int(os.environ.get("KYROX_BASE_SIZE", "120"))
GROW_SIZE = int(os.environ.get("KYROX_GROW_SIZE", "200"))

# Glassmorphism colors (can be themed later to match your existing talk orb)
GLASS_BG = "#7fd7ff"  # base tint
GLASS_OUTLINE = "#bfefff"


# -----------------------------
# Helpers
# -----------------------------

def clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


def now_ms():
    return int(time.time() * 1000)


# -----------------------------
# Automation layer (mouse/keyboard best-effort)
# -----------------------------

def ensure_automation_ready():
    if not ENABLE_AUTOMATION:
        return False, "Automation disabled by config"
    if pyautogui is None:
        return False, "pyautogui not installed"
    return True, "ok"


def open_application(command_text: str) -> bool:
    """Best-effort parser for simple intents."""
    if pyautogui is None:
        return False

    # Very small heuristic set.
    lower = command_text.lower()
    if "whatsapp" in lower:
        # Use Windows search (Win key)
        pyautogui.hotkey("win")
        time.sleep(0.4)
        pyautogui.typewrite("whatsapp")
        time.sleep(0.6)
        pyautogui.press("enter")
        return True

    if "chrome" in lower or "google" in lower:
        pyautogui.hotkey("win")
        time.sleep(0.4)
        pyautogui.typewrite("chrome")
        time.sleep(0.6)
        pyautogui.press("enter")
        return True

    return False


def type_and_send(message_text: str) -> None:
    if pyautogui is None:
        return
    # Try: focus message box with tab / ctrl+l heuristics are too risky; rely on current UI.
    pyautogui.typewrite(message_text)
    time.sleep(0.05)
    pyautogui.press("enter")


def execute_action_blocks(command_text: str) -> str:
    """Executes a command. For now: best-effort automation for WhatsApp messages.

    You can extend this to your existing OpenRouter/Ollama pipeline by replacing
    this function with real action-block execution.
    """
    ok, reason = ensure_automation_ready()
    if not ok:
        return f"NOT_EXECUTED: {reason}"

    lower = command_text.lower().strip()

    # Example supported: "open WhatsApp and message Mom hello"
    if "whatsapp" in lower and "message" in lower:
        # Extract recipient and message (very naive)
        # Pattern: "message Mom hello" -> recipient=Mom, message=hello
        try:
            after = lower.split("message", 1)[1].strip()
            # recipient is first token or first word(s) until we hit a likely message start.
            # We'll assume recipient is first word(s) capitalized in original text.
            # Fallback: first word.
            tokens = after.split()
            recipient = tokens[0] if tokens else ""
            msg = " ".join(tokens[1:]) if len(tokens) > 1 else ""
            # Use original case if possible for message
            original = command_text.strip()
            if original:
                # Attempt to split similarly on original
                o_after = original.lower().split("message", 1)[1].strip()
                # message text after recipient
                # This is still naive; keep msg from lower.
                _ = recipient
            if not msg:
                msg = "Hello"

            if open_application(command_text):
                # Give app time to open
                time.sleep(2.2)

                # Search recipient inside WhatsApp using ctrl+f if available (best-effort)
                pyautogui.hotkey("ctrl", "f")
                time.sleep(0.4)
                pyautogui.typewrite(recipient)
                time.sleep(0.6)
                pyautogui.press("enter")
                time.sleep(0.6)

                type_and_send(msg)
                return "OK"
        except Exception:
            return "ERROR"

    # Fallback: no automation rule matched
    return "UNSUPPORTED_INTENT"


# -----------------------------
# Voice / text input
# -----------------------------

def start_hotkey_listener(on_activate):
    if keyboard is None:
        return

    # keyboard.on_press_key supports single key only; use hooks
    # We'll approximate: when ctrl+alt pressed and space pressed.
    state = {"ctrl": False, "alt": False}

    def on_press(e):
        name = e.name
        if name == "ctrl":
            state["ctrl"] = True
        elif name == "alt":
            state["alt"] = True
        elif name == "space":
            if state["ctrl"] and state["alt"]:
                on_activate()

    def on_release(e):
        name = e.name
        if name == "ctrl":
            state["ctrl"] = False
        elif name == "alt":
            state["alt"] = False

    keyboard.on_press(on_press)
    keyboard.on_release(on_release)


class VoiceListenerThread(threading.Thread):
    def __init__(self, out_q: queue.Queue, stop_evt: threading.Event):
        super().__init__(daemon=True)
        self.out_q = out_q
        self.stop_evt = stop_evt

    def run(self):
        if sr is None:
            return
        recognizer = sr.Recognizer()
        recognizer.energy_threshold = ENERGY_THRESHOLD
        recognizer.dynamic_energy_threshold = False

        mic = sr.Microphone()
        with mic as source:
            recognizer.adjust_for_ambient_noise(source, duration=0.8)

        # Continuous listening loop
        with mic as source:
            while not self.stop_evt.is_set():
                try:
                    audio = recognizer.listen(source, timeout=1, phrase_time_limit=8)
                    text = recognizer.recognize_google(audio)  # best-effort; replace with your wakeword pipeline
                    if text:
                        self.out_q.put(text)
                except sr.WaitTimeoutError:
                    continue
                except Exception:
                    continue


# -----------------------------
# Main Orb UI
# -----------------------------

class OrbApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(APP_NAME)
        self.root.attributes("-topmost", True)
        self.root.attributes("-transparentcolor", "white")
        self.root.configure(bg="white")

        # Use whole-screen geometry but draw only the orb in a canvas at (0,0)
        self.screen_w = root.winfo_screenwidth()
        self.screen_h = root.winfo_screenheight()
        self.root.geometry(f"{self.screen_w}x{self.screen_h}+0+0")

        self.canvas = tk.Canvas(root, width=self.screen_w, height=self.screen_h, bg="white", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)

        self.stop_evt = threading.Event()
        self.input_q: queue.Queue[str] = queue.Queue()
        self.action_q: queue.Queue[str] = queue.Queue()

        # Orb state
        self.orb_x = self.screen_w * 0.5
        self.orb_y = self.screen_h * 0.5
        self.target_x = self.orb_x
        self.target_y = self.orb_y

        self.orb_r = BASE_SIZE / 2
        self.size_target = self.orb_r
        self.active = False

        # Drift phase
        self.phase = 0.0
        self.vx = DRIFT_SPEED
        self.vy = DRIFT_SPEED * 0.65

        # Animation feedback
        self.pulse_t0 = now_ms()
        self.status_text = ""

        # Draw initial orb
        self.glass_grad_id = None
        self.shell_id = None
        self.spark_id = None
        self.status_id = None
        self._draw_orb(init=True)

        # Text prompt on click
        self.canvas.bind("<Button-1>", self.on_click)

        # Start input threads
        if ENABLE_VOICE:
            self.voice_thread = VoiceListenerThread(self.input_q, self.stop_evt)
            self.voice_thread.start()

        start_hotkey_listener(self.activate_from_hotkey)

        # Main loop
        self.root.after(TICK_MS, self.tick)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def on_close(self):
        self.stop_evt.set()
        self.root.destroy()

    def activate_from_hotkey(self):
        # Thread-safe activation: schedule on UI
        self.root.after(0, self.activate)

    def activate(self):
        if self.active:
            return
        self.active = True
        self.size_target = GROW_SIZE / 2

        # Snap to center of main monitor (in this simplified single-window setup)
        self.target_x = self.screen_w * 0.5
        self.target_y = self.screen_h * 0.5

        self.status_text = "Listening…"
        self.pulse_t0 = now_ms()

    def deactivate_and_resume_drift(self):
        self.active = False
        self.size_target = BASE_SIZE / 2
        self.status_text = ""

    def on_click(self, _event):
        # Click-to-type prompt (no talking required)
        if not self.active:
            self.activate()

        # Create an entry overlay for prompt
        self._prompt_window()

    def _prompt_window(self):
        win = tk.Toplevel(self.root)
        win.title("Kyrox Command")
        win.attributes("-topmost", True)
        win.geometry("520x150")

        label = tk.Label(win, text="Enter command:", font=("Segoe UI", 11))
        label.pack(pady=10)

        entry = tk.Entry(win, font=("Segoe UI", 12))
        entry.pack(fill="x", padx=20)
        entry.focus_set()

        def submit():
            txt = entry.get().strip()
            win.destroy()
            if txt:
                self.input_q.put(txt)

        btn = tk.Button(win, text="Send", command=submit, font=("Segoe UI", 11))
        btn.pack(pady=12)

        win.transient(self.root)

    def _update_status(self, text: str):
        self.status_text = text

    def _draw_orb(self, init=False):
        # Clear orb shapes (simple approach)
        self.canvas.delete("orb")

        r = self.orb_r
        x, y = self.orb_x, self.orb_y
        bbox = (x - r, y - r, x + r, y + r)

        # Glass look: layered ovals
        # Outer shell
        self.shell_id = self.canvas.create_oval(
            bbox, outline=GLASS_OUTLINE, width=2, fill=""
        , tags=("orb",))

        # Inner tinted fill with alpha-like effect (tkinter has no alpha)
        # We'll approximate via stipple pattern.
        fill_color = GLASS_BG
        self.canvas.create_oval(
            bbox, outline="", fill=fill_color, stipple="gray25", tags=("orb",)
        )

        # Specular highlight
        hx1 = x - r * 0.5
        hy1 = y - r * 0.6
        hx2 = x + r * 0.15
        hy2 = y - r * 0.25
        self.canvas.create_oval(
            (hx1, hy1, hx2, hy2), fill="white", outline="", stipple="gray50", tags=("orb",)
        )

        # Processing pulse (ring)
        if self.active:
            t = (now_ms() - self.pulse_t0) / 1000.0
            pulse = 0.5 + 0.5 * math.sin(t * 6.0)
            ring_r = r * (1.05 + 0.08 * pulse)
            ring_bbox = (x - ring_r, y - ring_r, x + ring_r, y + ring_r)
            self.canvas.create_oval(
                ring_bbox, outline="#ffffff", width=2, stipple="gray25", tags=("orb",)
            )

        # Status text
        if self.status_text:
            self.status_id = self.canvas.create_text(
                x, y + r + 18,
                text=self.status_text,
                fill="white",
                font=("Segoe UI", 12, "bold"),
                tags=("orb",)
            )

    def _prompt_to_action(self, command_text: str):
        # Convert natural language to action blocks (hook point)
        self._update_status("Processing…")

        def worker():
            # In your final version, replace this with your OpenRouter/Ollama pipeline
            result = execute_action_blocks(command_text)
            self.root.after(0, lambda: self._on_action_done(result))

        threading.Thread(target=worker, daemon=True).start()

    def _on_action_done(self, result: str):
        # Visual feedback then resume
        if result == "OK":
            self.status_text = "Done"
        else:
            self.status_text = f"{result}"

        # Shrink back after short delay
        self.root.after(900, self.deactivate_and_resume_drift)

    def tick(self):
        # Consume inputs
        try:
            while True:
                cmd = self.input_q.get_nowait()
                # If voice returns text, activate if needed
                if not self.active:
                    self.activate()
                self._prompt_to_action(cmd)
                # Only handle one command at a time
                break
        except queue.Empty:
            pass

        # Animate size
        if abs(self.orb_r - self.size_target) > 0.2:
            self.orb_r += (self.size_target - self.orb_r) * 0.18
        else:
            self.orb_r = self.size_target

        # Smooth movement
        # Drift updates target when not active
        if not self.active:
            self.phase += 0.02
            # For multi-monitor: tk is single virtual screen. We'll keep within bounds.
            mx = self.screen_w * 0.5 + math.cos(self.phase) * (self.screen_w * 0.35)
            my = self.screen_h * 0.5 + math.sin(self.phase * 0.9) * (self.screen_h * 0.25)
            self.target_x = mx
            self.target_y = my

        # Smooth step
        self.orb_x += (self.target_x - self.orb_x) * (0.08 if self.active else 0.03)
        self.orb_y += (self.target_y - self.orb_y) * (0.08 if self.active else 0.03)

        # Clamp within visible area
        r = max(20, self.orb_r)
        self.orb_x = clamp(self.orb_x, r, self.screen_w - r)
        self.orb_y = clamp(self.orb_y, r, self.screen_h - r)

        self._draw_orb()
        self.root.after(TICK_MS, self.tick)


def main():
    root = tk.Tk()

    # Remove window decorations (orb only)
    root.overrideredirect(True)
    app = OrbApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()

