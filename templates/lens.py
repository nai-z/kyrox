"""
Kyrox Lens — Floating overlay window (always on top, cross-app)
Auto-launched by Kyrox. Communicates with Kyrox backend on http://localhost:8000
"""

import tkinter as tk
from tkinter import font as tkfont
import threading, base64, io, json, sys, os
import urllib.request, urllib.error

try:
    import mss
    HAS_MSS = True
except ImportError:
    HAS_MSS = False

try:
    from PIL import Image, ImageTk
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

KYROX_URL = "http://localhost:80"

# ── Palette ────────────────────────────────────────────────────────────────
C = {
    "bg":      "#0d0b1a",
    "bg2":     "#131126",
    "bg3":     "#1a1830",
    "purple":  "#8a5bff",
    "purpled": "#3d1fa8",
    "cyan":    "#00d4ff",
    "text":    "#e2deff",
    "text2":   "#8b82b8",
    "text3":   "#3d3660",
    "orange":  "#ff9500",
    "green":   "#00ffaa",
    "danger":  "#ff4d6d",
    "border":  "#2a2545",
}

# ── Screen capture ─────────────────────────────────────────────────────────
def get_monitors():
    if not HAS_MSS:
        return [{"id": 0, "label": "Monitor 1"}]
    with mss.mss() as sct:
        out = []
        for i, m in enumerate(sct.monitors):
            if i == 0:
                lbl = f"All screens  ({m['width']}×{m['height']})"
            else:
                lbl = f"Screen {i}  {m['width']}×{m['height']}"
            out.append({"id": i, "label": lbl, "mon": dict(m)})
        return out

def take_screenshot(idx=1):
    if not HAS_MSS or not HAS_PIL:
        return None
    try:
        with mss.mss() as sct:
            mons = sct.monitors
            idx = min(idx, len(mons)-1)
            img = sct.grab(mons[idx])
            pil = Image.frombytes("RGB", img.size, img.bgra, "raw", "BGRX")
            if pil.width > 1280:
                r = 1280/pil.width
                pil = pil.resize((1280, int(pil.height*r)), Image.LANCZOS)
            buf = io.BytesIO()
            pil.save(buf, "PNG", optimize=True)
            return base64.b64encode(buf.getvalue()).decode()
    except:
        return None

def get_thumb(idx=1, w=200, h=112):
    if not HAS_MSS or not HAS_PIL:
        return None
    try:
        with mss.mss() as sct:
            mons = sct.monitors
            idx = min(idx, len(mons)-1)
            img = sct.grab(mons[idx])
            pil = Image.frombytes("RGB", img.size, img.bgra, "raw", "BGRX")
            pil.thumbnail((w, h), Image.LANCZOS)
            return ImageTk.PhotoImage(pil)
    except:
        return None

# ── Vision API ─────────────────────────────────────────────────────────────
VISION_MODELS = [
    "google/gemini-flash-1.5",
    "google/gemini-2.0-flash-001",
    "openai/gpt-4o-mini",
    "anthropic/claude-3-haiku",
    "meta-llama/llama-3.2-11b-vision-instruct:free",
]

def call_vision(img_b64, prompt, on_done, on_status):
    def _run():
        try:
            on_status("Connecting to Kyrox…", C["orange"])
            req = urllib.request.Request(f"{KYROX_URL}/api/settings")
            with urllib.request.urlopen(req, timeout=5) as r:
                settings = json.loads(r.read())
            api_key = settings.get("openrouter_key","").strip()
            if not api_key:
                on_done("⚠ No API key — configure OpenRouter in Kyrox settings.")
                return

            for model in VISION_MODELS:
                on_status(f"Asking {model.split('/')[-1]}…", C["cyan"])
                payload = json.dumps({
                    "model": model,
                    "messages": [{"role":"user","content":[
                        {"type":"image_url","image_url":{"url":f"data:image/png;base64,{img_b64}"}},
                        {"type":"text","text":prompt}
                    ]}],
                    "max_tokens": 1024,
                }).encode()
                req2 = urllib.request.Request(
                    "https://openrouter.ai/api/v1/chat/completions",
                    data=payload,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                        "HTTP-Referer": "https://kyrox.nemea.uk",
                        "X-Title": "Kyrox Lens",
                    }, method="POST"
                )
                try:
                    with urllib.request.urlopen(req2, timeout=30) as r:
                        resp = json.loads(r.read())
                        text = resp.get("choices",[{}])[0].get("message",{}).get("content","")
                        if text:
                            on_done(text)
                            return
                except urllib.error.HTTPError as e:
                    if e.code in (429, 404, 400, 422):
                        continue
                except:
                    continue
            on_done("⚠ All vision models unavailable. Try again.")
        except Exception as e:
            on_done(f"⚠ Error: {e}")
    threading.Thread(target=_run, daemon=True).start()

# ── Auto-install deps ──────────────────────────────────────────────────────
def ensure_deps():
    missing = []
    if not HAS_MSS: missing.append("mss")
    if not HAS_PIL: missing.append("pillow")
    if missing:
        import subprocess
        subprocess.run([sys.executable,"-m","pip","install","--quiet"]+missing, check=False)
        os.execv(sys.executable, [sys.executable]+sys.argv)

# ── App ────────────────────────────────────────────────────────────────────
class KyroxLens:
    W, H = 300, 500

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Kyrox Lens")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.configure(bg=C["bg"])

        # Center on screen
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x  = sw - self.W - 30
        y  = (sh - self.H) // 2
        self.root.geometry(f"{self.W}x{self.H}+{x}+{y}")

        self._dx = self._dy = 0
        self._thumb = None
        self.monitors = get_monitors()
        self.sel_mon  = tk.IntVar(value=min(1, len(self.monitors)-1))

        self._build()
        self._refresh_thumb()
        self._keep_top()

    def _keep_top(self):
        self.root.attributes("-topmost", True)
        self.root.lift()
        self.root.after(800, self._keep_top)

    # ── Build UI ───────────────────────────────────────────────────────────
    def _build(self):
        root = self.root

        # ── Outer border effect ──────────────────────────────────────────
        root.configure(highlightbackground=C["purple"],
                       highlightthickness=1)

        # ── Titlebar ─────────────────────────────────────────────────────
        bar = tk.Frame(root, bg=C["purpled"], height=40)
        bar.pack(fill="x")
        bar.pack_propagate(False)

        tk.Label(bar, text="⬡  KYROX LENS",
                 font=("Consolas",11,"bold"),
                 fg="#ffffff", bg=C["purpled"],
                 padx=10).pack(side="left", fill="y")

        tf = tk.Frame(bar, bg=C["purpled"])
        tf.pack(side="right", padx=6, pady=6)

        self._btn(tf, "–", C["text2"], C["purpled"], self._minimize, w=2).pack(side="left",padx=2)
        self._btn(tf, "✕", C["danger"], C["purpled"], root.destroy, w=2).pack(side="left")

        bar.bind("<ButtonPress-1>",   self._ds)
        bar.bind("<B1-Motion>",       self._dm)
        for c in bar.winfo_children():
            if isinstance(c, tk.Label):
                c.bind("<ButtonPress-1>", self._ds)
                c.bind("<B1-Motion>",     self._dm)

        # ── Screen selector ───────────────────────────────────────────────
        sf = tk.Frame(root, bg=C["bg"], pady=6, padx=10)
        sf.pack(fill="x")

        tk.Label(sf, text="SELECT SCREEN",
                 font=("Consolas",7,"bold"),
                 fg=C["text3"], bg=C["bg"]).pack(anchor="w", pady=(0,4))

        rb_frame = tk.Frame(sf, bg=C["bg"])
        rb_frame.pack(fill="x")
        for m in self.monitors:
            rb = tk.Radiobutton(
                rb_frame, text=m["label"],
                variable=self.sel_mon, value=m["id"],
                font=("Consolas", 8),
                fg=C["text2"], bg=C["bg"],
                selectcolor=C["bg2"],
                activebackground=C["bg"],
                activeforeground=C["purple"],
                indicatoron=True, cursor="hand2",
                command=self._refresh_thumb,
            )
            rb.pack(anchor="w")

        # ── Preview ───────────────────────────────────────────────────────
        prev_wrap = tk.Frame(root, bg=C["border"], padx=1, pady=1)
        prev_wrap.pack(padx=10, pady=(0,8))

        self.prev_lbl = tk.Label(
            prev_wrap, bg=C["bg2"],
            text="Click ↻ to preview",
            font=("Consolas",8), fg=C["text3"],
            width=200, height=112,
            cursor="hand2"
        )
        self.prev_lbl.pack()
        self.prev_lbl.bind("<Button-1>", lambda e: self._refresh_thumb())

        # Refresh button
        rf = tk.Frame(root, bg=C["bg"])
        rf.pack(fill="x", padx=10)
        self._btn(rf, "↻  Refresh preview", C["text3"], C["bg"],
                  self._refresh_thumb, font_size=8).pack(side="right")

        # ── Separator ─────────────────────────────────────────────────────
        tk.Frame(root, bg=C["border"], height=1).pack(fill="x", padx=10, pady=8)

        # ── Prompt ───────────────────────────────────────────────────────
        tk.Label(root, text="CUSTOM PROMPT (optional)",
                 font=("Consolas",7,"bold"),
                 fg=C["text3"], bg=C["bg"]).pack(anchor="w", padx=12)

        self.prompt = tk.Entry(root,
                               font=("Consolas",10),
                               fg=C["text"], bg=C["bg2"],
                               insertbackground=C["purple"],
                               relief="flat",
                               highlightthickness=1,
                               highlightbackground=C["border"],
                               highlightcolor=C["purple"])
        self.prompt.pack(fill="x", padx=10, pady=4)
        self.prompt.bind("<Return>", lambda e: self._do_analyse())

        # ── Action buttons ────────────────────────────────────────────────
        bf = tk.Frame(root, bg=C["bg"], pady=2)
        bf.pack(fill="x", padx=10)

        self._big_btn(bf, "👁  ANALYSE MY SCREEN",
                      C["purple"], self._do_analyse).pack(fill="x", pady=(0,4))
        self._big_btn(bf, "⚡  SOLVE",
                      C["cyan"], self._do_solve).pack(fill="x")

        # ── Status ────────────────────────────────────────────────────────
        tk.Frame(root, bg=C["border"], height=1).pack(fill="x", padx=10, pady=6)

        self.status = tk.Label(root, text="Ready.",
                               font=("Consolas",8),
                               fg=C["text3"], bg=C["bg"],
                               anchor="w", padx=12)
        self.status.pack(fill="x")

        # ── Response box ──────────────────────────────────────────────────
        resp_f = tk.Frame(root, bg=C["bg2"],
                          highlightthickness=1,
                          highlightbackground=C["border"])
        resp_f.pack(fill="both", expand=True, padx=10, pady=(4,10))

        self.resp = tk.Text(resp_f,
                            font=("Consolas",9),
                            fg=C["text"], bg=C["bg2"],
                            wrap="word", relief="flat",
                            state="disabled",
                            selectbackground=C["purpled"],
                            padx=8, pady=6,
                            cursor="arrow")
        sb = tk.Scrollbar(resp_f, command=self.resp.yview,
                          bg=C["bg2"], troughcolor=C["bg2"], width=5,
                          relief="flat")
        self.resp.config(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.resp.pack(fill="both", expand=True)

    # ── Helpers ────────────────────────────────────────────────────────────
    def _btn(self, parent, text, fg, bg, cmd, w=None, font_size=9):
        kw = dict(text=text, font=("Consolas",font_size,"bold"),
                  fg=fg, bg=bg, relief="flat", bd=0,
                  activebackground=bg, activeforeground=C["purple"],
                  cursor="hand2", command=cmd)
        if w: kw["width"] = w
        return tk.Button(parent, **kw)

    def _big_btn(self, parent, text, color, cmd):
        return tk.Button(parent, text=text,
                         font=("Consolas",9,"bold"),
                         fg=color, bg=C["bg3"],
                         relief="flat", bd=0, pady=8,
                         activebackground=C["bg2"],
                         activeforeground=color,
                         cursor="hand2",
                         highlightthickness=1,
                         highlightbackground=color,
                         command=cmd)

    # ── Drag ──────────────────────────────────────────────────────────────
    def _ds(self, e):
        self._dx = e.x_root - self.root.winfo_x()
        self._dy = e.y_root - self.root.winfo_y()

    def _dm(self, e):
        x = max(0, min(e.x_root - self._dx, self.root.winfo_screenwidth()  - self.W))
        y = max(0, min(e.y_root - self._dy, self.root.winfo_screenheight() - self.H))
        self.root.geometry(f"+{x}+{y}")

    # ── Minimize ──────────────────────────────────────────────────────────
    def _minimize(self):
        self.root.overrideredirect(False)
        self.root.iconify()
        def _restore(e):
            self.root.deiconify()
            self.root.overrideredirect(True)
            self.root.attributes("-topmost", True)
            self.root.unbind("<Map>")
        self.root.bind("<Map>", _restore)

    # ── Preview ───────────────────────────────────────────────────────────
    def _refresh_thumb(self):
        def _go():
            idx   = self.sel_mon.get()
            thumb = get_thumb(idx, 200, 112)
            def _ui():
                if thumb:
                    self._thumb = thumb
                    self.prev_lbl.config(image=thumb, text="", width=200, height=112)
                else:
                    self.prev_lbl.config(text="pip install mss pillow",
                                         width=200, height=112)
            self.root.after(0, _ui)
        threading.Thread(target=_go, daemon=True).start()

    # ── Set status / response ─────────────────────────────────────────────
    def _setstatus(self, msg, color=None):
        self.root.after(0, lambda: self.status.config(
            text=msg, fg=color or C["text3"]))

    def _setresp(self, text):
        def _ui():
            self.resp.config(state="normal")
            self.resp.delete("1.0","end")
            self.resp.insert("end", text)
            self.resp.config(state="disabled")
        self.root.after(0, _ui)

    # ── Actions ───────────────────────────────────────────────────────────
    def _do_analyse(self):
        p = self.prompt.get().strip() or \
            "Describe everything you see on this screen in detail."
        self._capture_and_ask(p)

    def _do_solve(self):
        p = self.prompt.get().strip() or \
            ("Look at this screen carefully. "
             "Identify any visible problem, error, task, question, or code. "
             "Then provide a clear, direct solution or answer.")
        self._capture_and_ask(p)

    def _capture_and_ask(self, prompt):
        self._setstatus("📸 Capturing screen…", C["orange"])
        self._setresp("")

        def _go():
            idx    = self.sel_mon.get()
            img_b64 = take_screenshot(idx)
            if img_b64 is None:
                self._setstatus("⚠ Capture failed", C["danger"])
                self._setresp("Could not capture screen.\nRun: pip install mss pillow")
                return
            self._setstatus("🔍 Screen analysed — asking Kyrox…", C["cyan"])
            call_vision(
                img_b64, prompt,
                on_done   = lambda t: (self._setstatus("✓ Done", C["green"]),
                                       self._setresp(t),
                                       self._refresh_thumb()),
                on_status = lambda m, c: self._setstatus(m, c),
            )
        threading.Thread(target=_go, daemon=True).start()

    def run(self):
        self.root.mainloop()

# ── Entry ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    ensure_deps()
    KyroxLens().run()
