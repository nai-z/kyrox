"""
Kyrox Lens — Floating overlay (always on top)
Same black/white aesthetic as the web UI.
Launch manually via the ⊡ button in the browser, or run directly: python lens.py
"""

import tkinter as tk
from tkinter import font as tkfont, filedialog
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

KYROX_URL = "http://localhost:8000"

# ── Palette (matches index.html :root) ────────────────────────────────────────
C = {
    "bg":      "#0a0a0a",
    "bg2":     "#111111",
    "bg3":     "#161616",
    "border":  "#1a1a1a",
    "border2": "#0f0f0f",
    "accent":  "#ffffff",
    "text":    "#f0f0f0",
    "text2":   "#888888",
    "text3":   "#333333",
    "green":   "#00cc6a",
    "orange":  "#ff9500",
    "danger":  "#ff4040",
}

FONT_MONO  = ("Consolas", 9)
FONT_MONO_S= ("Consolas", 8)
FONT_MONO_L= ("Consolas", 10, "bold")
FONT_TITLE = ("Consolas", 10, "bold")

# ── Screen capture ─────────────────────────────────────────────────────────────
def get_monitors():
    if not HAS_MSS:
        return [{"id": 0, "label": "Screen 1"}]
    with mss.mss() as sct:
        out = []
        for i, m in enumerate(sct.monitors):
            if i == 0:
                lbl = f"All  ({m['width']}×{m['height']})"
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
            idx = min(idx, len(mons) - 1)
            img = sct.grab(mons[idx])
            pil = Image.frombytes("RGB", img.size, img.bgra, "raw", "BGRX")
            if pil.width > 1280:
                r = 1280 / pil.width
                pil = pil.resize((1280, int(pil.height * r)), Image.LANCZOS)
            buf = io.BytesIO()
            pil.save(buf, "PNG", optimize=True)
            return base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return None

def get_thumb(idx=1, w=240, h=135):
    if not HAS_MSS or not HAS_PIL:
        return None
    try:
        with mss.mss() as sct:
            mons = sct.monitors
            idx = min(idx, len(mons) - 1)
            img = sct.grab(mons[idx])
            pil = Image.frombytes("RGB", img.size, img.bgra, "raw", "BGRX")
            pil.thumbnail((w, h), Image.LANCZOS)
            return ImageTk.PhotoImage(pil)
    except Exception:
        return None

def load_image_b64(path: str) -> tuple[str, str]:
    """Load an image file and return (base64, mime_type)."""
    ext = os.path.splitext(path)[1].lower()
    mime = {".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".png": "image/png", ".gif": "image/gif",
            ".webp": "image/webp"}.get(ext, "image/png")
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode(), mime

# ── Vision API ─────────────────────────────────────────────────────────────────
VISION_MODELS = [
    "google/gemini-2.0-flash-001",
    "google/gemini-flash-1.5",
    "openai/gpt-4o-mini",
    "anthropic/claude-3-haiku",
    "meta-llama/llama-3.2-11b-vision-instruct:free",
]

def call_vision(img_b64: str, mime: str, prompt: str, on_done, on_status):
    def _run():
        try:
            on_status("Connecting…", C["orange"])
            try:
                req = urllib.request.Request(f"{KYROX_URL}/api/settings")
                with urllib.request.urlopen(req, timeout=5) as r:
                    settings = json.loads(r.read())
                api_key = settings.get("openrouter_key", "").strip()
            except Exception:
                on_done("⚠ Cannot reach Kyrox backend.\nMake sure Kyrox is running at localhost:8000,\nor open Kyrox in your browser first.")
                return

            if not api_key:
                on_done("⚠ No API key — add your OpenRouter key in Kyrox settings.")
                return

            last_err = ""
            for model in VISION_MODELS:
                on_status(f"Asking {model.split('/')[-1]}…", C["text2"])
                payload = json.dumps({
                    "model": model,
                    "messages": [{"role": "user", "content": [
                        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{img_b64}"}},
                        {"type": "text", "text": prompt},
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
                        text = resp.get("choices", [{}])[0].get("message", {}).get("content", "")
                        if text:
                            on_done(text)
                            return
                        last_err = "Empty response from model."
                except urllib.error.HTTPError as e:
                    last_err = f"HTTP {e.code} from {model.split('/')[-1]}"
                    if e.code in (429, 404, 400, 422):
                        continue
                except Exception as e:
                    last_err = str(e)
                    continue
            on_done(f"⚠ All vision models unavailable.\n{last_err}")
        except Exception as e:
            on_done(f"⚠ Error: {e}")
    threading.Thread(target=_run, daemon=True).start()

def call_text(prompt: str, on_done, on_status):
    """Send a plain text question to Kyrox backend (no image)."""
    def _run():
        try:
            on_status("Connecting…", C["orange"])
            try:
                req = urllib.request.Request(f"{KYROX_URL}/api/settings")
                with urllib.request.urlopen(req, timeout=5) as r:
                    settings = json.loads(r.read())
                api_key = settings.get("openrouter_key", "").strip()
            except Exception:
                # Backend not running — ask user to add key directly or start Kyrox
                on_done("⚠ Cannot reach Kyrox backend.\nMake sure Kyrox is running at localhost:8000,\nor open Kyrox in your browser first.")
                return

            if not api_key:
                on_done("⚠ No API key configured.\nAdd your OpenRouter key in Kyrox settings.")
                return

            models = [
                "deepseek/deepseek-v3:free",
                "meta-llama/llama-3.3-70b-instruct:free",
                "openrouter/auto",
            ]
            last_err = ""
            for model in models:
                on_status(f"Asking {model.split('/')[-1]}…", C["text2"])
                payload = json.dumps({
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
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
                        text = resp.get("choices", [{}])[0].get("message", {}).get("content", "")
                        if text:
                            on_done(text)
                            return
                        last_err = "Empty response from model."
                except urllib.error.HTTPError as e:
                    last_err = f"HTTP {e.code} from {model.split('/')[-1]}"
                    if e.code in (429, 404, 400, 422):
                        continue
                except Exception as e:
                    last_err = str(e)
                    continue
            on_done(f"⚠ Could not get a response.\n{last_err}")
        except Exception as e:
            on_done(f"⚠ Error: {e}")
    threading.Thread(target=_run, daemon=True).start()

# ── Auto-install deps ──────────────────────────────────────────────────────────
def ensure_deps():
    missing = []
    if not HAS_MSS: missing.append("mss")
    if not HAS_PIL: missing.append("pillow")
    if missing:
        import subprocess
        subprocess.run([sys.executable, "-m", "pip", "install", "--quiet"] + missing, check=False)
        os.execv(sys.executable, [sys.executable] + sys.argv)

# ── Rounded rect helper ────────────────────────────────────────────────────────
def _place(widget, x, y, w, h):
    widget.place(x=x, y=y, width=w, height=h)

# ── Main window ────────────────────────────────────────────────────────────────
class KyroxLens:
    W, H = 320, 560

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Kyrox Lens")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.configure(bg=C["bg"])
        self.root.resizable(False, False)

        # Outer 1px white border effect via frame
        self.root.configure(highlightbackground=C["text3"], highlightthickness=1)

        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x  = sw - self.W - 24
        y  = (sh - self.H) // 2
        self.root.geometry(f"{self.W}x{self.H}+{x}+{y}")

        self._dx = self._dy = 0
        self._thumb = None
        self._upload_thumb = None          # thumbnail for upload preview
        self._uploaded_img_b64 = None   # base64 of user-uploaded image
        self._uploaded_img_mime = None
        self._uploaded_img_name = ""
        self._uploaded_file_text = None # text content of uploaded file
        self.monitors = get_monitors()
        self.sel_mon  = tk.IntVar(value=min(1, len(self.monitors) - 1))
        self.mode     = tk.StringVar(value="screen")  # "screen" | "upload"

        self._build()
        self._refresh_thumb()
        self._keep_top()

    def _keep_top(self):
        self.root.attributes("-topmost", True)
        self.root.lift()
        self.root.after(1000, self._keep_top)

    # ── Build UI ───────────────────────────────────────────────────────────────
    def _build(self):
        r = self.root

        # ── Titlebar ──────────────────────────────────────────────────────────
        bar = tk.Frame(r, bg=C["bg2"], height=42)
        bar.pack(fill="x")
        bar.pack_propagate(False)

        # thin bottom border on titlebar
        tk.Frame(bar, bg=C["text3"], height=1).place(relx=0, rely=1, relwidth=1, anchor="sw")

        tk.Label(bar, text="KYROX  LENS",
                 font=("Consolas", 10, "bold"),
                 fg=C["text"], bg=C["bg2"],
                 padx=14).pack(side="left", fill="y")

        tf = tk.Frame(bar, bg=C["bg2"])
        tf.pack(side="right", padx=8, pady=8)
        self._icon_btn(tf, "—", self._minimize).pack(side="left", padx=2)
        self._icon_btn(tf, "✕", r.destroy, danger=True).pack(side="left")

        bar.bind("<ButtonPress-1>", self._ds)
        bar.bind("<B1-Motion>",     self._dm)

        # ── Mode tabs ─────────────────────────────────────────────────────────
        tab_f = tk.Frame(r, bg=C["bg"], pady=8, padx=12)
        tab_f.pack(fill="x")

        self._tab_screen = self._tab_btn(tab_f, "◉  SCREEN", lambda: self._set_mode("screen"))
        self._tab_screen.pack(side="left", padx=(0, 4))
        self._tab_upload = self._tab_btn(tab_f, "↑  UPLOAD", lambda: self._set_mode("upload"))
        self._tab_upload.pack(side="left")
        self._update_tabs()

        # ── Screen selector ───────────────────────────────────────────────────
        self.screen_frame = tk.Frame(r, bg=C["bg"])
        self.screen_frame.pack(fill="x", padx=12)

        mon_f = tk.Frame(self.screen_frame, bg=C["bg"])
        mon_f.pack(fill="x")
        for m in self.monitors:
            rb = tk.Radiobutton(
                mon_f, text=m["label"],
                variable=self.sel_mon, value=m["id"],
                font=("Consolas", 8),
                fg=C["text2"], bg=C["bg"],
                selectcolor=C["bg3"],
                activebackground=C["bg"],
                activeforeground=C["text"],
                indicatoron=True, cursor="hand2",
                command=self._refresh_thumb,
            )
            rb.pack(side="left", padx=(0, 10))

        # Preview
        prev_outer = tk.Frame(self.screen_frame, bg=C["text3"], padx=1, pady=1)
        prev_outer.pack(fill="x", pady=(6, 0))
        prev_inner = tk.Frame(prev_outer, bg=C["bg2"])
        prev_inner.pack(fill="both")

        self.prev_lbl = tk.Label(
            prev_inner, bg=C["bg2"],
            text="Click to refresh",
            font=("Consolas", 8), fg=C["text3"],
            width=240, height=135, cursor="hand2"
        )
        self.prev_lbl.pack()
        self.prev_lbl.bind("<Button-1>", lambda e: self._refresh_thumb())

        ref_f = tk.Frame(self.screen_frame, bg=C["bg"])
        ref_f.pack(fill="x", pady=(4, 0))
        tk.Button(ref_f, text="↻  refresh",
                  font=("Consolas", 8), fg=C["text3"], bg=C["bg"],
                  relief="flat", bd=0, cursor="hand2",
                  activebackground=C["bg"], activeforeground=C["text"],
                  command=self._refresh_thumb).pack(side="right")

        # ── Upload frame ──────────────────────────────────────────────────────
        self.upload_frame = tk.Frame(r, bg=C["bg"])
        # (not packed yet — shown when mode=upload)

        self.upload_lbl = tk.Label(
            self.upload_frame,
            text="No file selected",
            font=("Consolas", 8), fg=C["text3"], bg=C["bg2"],
            anchor="w", padx=10, pady=8,
            relief="flat", cursor="hand2"
        )
        self.upload_lbl.pack(fill="x", padx=0, pady=(0, 4))
        self.upload_lbl.bind("<Button-1>", lambda e: self._pick_file())

        # Upload preview (mirrors screen preview)
        up_prev_outer = tk.Frame(self.upload_frame, bg=C["text3"], padx=1, pady=1)
        up_prev_outer.pack(fill="x", pady=(0, 4))
        up_prev_inner = tk.Frame(up_prev_outer, bg=C["bg2"])
        up_prev_inner.pack(fill="both")
        self.upload_prev_lbl = tk.Label(
            up_prev_inner, bg=C["bg2"],
            text="No image loaded",
            font=("Consolas", 8), fg=C["text3"],
            width=240, height=135,
        )
        self.upload_prev_lbl.pack()

        ub_f = tk.Frame(self.upload_frame, bg=C["bg"])
        ub_f.pack(fill="x")
        self._outline_btn(ub_f, "↑  PICK IMAGE", self._pick_image).pack(side="left", padx=(0, 4))
        self._outline_btn(ub_f, "📄  PICK FILE",  self._pick_text_file).pack(side="left")

        # ── Separator ─────────────────────────────────────────────────────────
        tk.Frame(r, bg=C["text3"], height=1).pack(fill="x", padx=12, pady=10)

        # ── Prompt ────────────────────────────────────────────────────────────
        tk.Label(r, text="PROMPT  (optional)",
                 font=("Consolas", 7, "bold"),
                 fg=C["text3"], bg=C["bg"]).pack(anchor="w", padx=12)

        prompt_f = tk.Frame(r, bg=C["text3"], padx=1, pady=1)
        prompt_f.pack(fill="x", padx=12, pady=(3, 6))
        self.prompt = tk.Entry(
            prompt_f,
            font=("Consolas", 10),
            fg=C["text"], bg=C["bg2"],
            insertbackground=C["text"],
            relief="flat",
        )
        self.prompt.pack(fill="x", ipady=6, padx=4)
        self.prompt.bind("<Return>", lambda e: self._do_analyse())

        # ── Action buttons ────────────────────────────────────────────────────
        bf = tk.Frame(r, bg=C["bg"])
        bf.pack(fill="x", padx=12)

        self._primary_btn(bf, "◉  ANALYSE", self._do_analyse).pack(fill="x", pady=(0, 4))
        self._primary_btn(bf, "⚡  SOLVE",   self._do_solve, outline=True).pack(fill="x")

        # ── Separator ─────────────────────────────────────────────────────────
        tk.Frame(r, bg=C["text3"], height=1).pack(fill="x", padx=12, pady=8)

        # ── Status ────────────────────────────────────────────────────────────
        self.status = tk.Label(r, text="Ready.",
                               font=("Consolas", 8),
                               fg=C["text3"], bg=C["bg"],
                               anchor="w", padx=12)
        self.status.pack(fill="x")

        # ── Response ──────────────────────────────────────────────────────────
        resp_outer = tk.Frame(r, bg=C["text3"], padx=1, pady=1)
        resp_outer.pack(fill="both", expand=True, padx=12, pady=(4, 12))

        resp_inner = tk.Frame(resp_outer, bg=C["bg2"])
        resp_inner.pack(fill="both", expand=True)

        self.resp = tk.Text(
            resp_inner,
            font=("Consolas", 9),
            fg=C["text"], bg=C["bg2"],
            wrap="word", relief="flat",
            state="disabled",
            selectbackground=C["bg3"],
            padx=10, pady=8,
            cursor="arrow",
        )
        sb = tk.Scrollbar(resp_inner, command=self.resp.yview,
                          bg=C["bg2"], troughcolor=C["bg2"], width=4,
                          relief="flat", bd=0)
        self.resp.config(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.resp.pack(fill="both", expand=True)

    # ── Widget factories ───────────────────────────────────────────────────────
    def _icon_btn(self, parent, text, cmd, danger=False):
        fg = C["danger"] if danger else C["text2"]
        return tk.Button(parent, text=text,
                         font=("Consolas", 9), fg=fg, bg=C["bg2"],
                         relief="flat", bd=0, padx=6, pady=2,
                         activebackground=C["bg3"], activeforeground=fg,
                         cursor="hand2", command=cmd)

    def _tab_btn(self, parent, text, cmd):
        return tk.Button(parent, text=text,
                         font=("Consolas", 8, "bold"), fg=C["text3"], bg=C["bg"],
                         relief="flat", bd=0, padx=10, pady=4,
                         activebackground=C["bg2"], activeforeground=C["text"],
                         cursor="hand2", command=cmd)

    def _outline_btn(self, parent, text, cmd):
        f = tk.Frame(parent, bg=C["text3"], padx=1, pady=1)
        tk.Button(f, text=text,
                  font=("Consolas", 8), fg=C["text2"], bg=C["bg"],
                  relief="flat", bd=0, padx=8, pady=4,
                  activebackground=C["bg2"], activeforeground=C["text"],
                  cursor="hand2", command=cmd).pack()
        return f

    def _primary_btn(self, parent, text, cmd, outline=False):
        if outline:
            fg, bg, abg = C["text2"], C["bg2"], C["bg3"]
        else:
            fg, bg, abg = C["bg"], C["text"], C["text2"]
        return tk.Button(parent, text=text,
                         font=("Consolas", 9, "bold"), fg=fg, bg=bg,
                         relief="flat", bd=0, pady=9,
                         activebackground=abg, activeforeground=fg,
                         cursor="hand2", command=cmd)

    # ── Mode ──────────────────────────────────────────────────────────────────
    def _set_mode(self, mode):
        self.mode.set(mode)
        self._update_tabs()
        if mode == "screen":
            self.upload_frame.pack_forget()
            self.screen_frame.pack(fill="x", padx=12)
        else:
            self.screen_frame.pack_forget()
            self.upload_frame.pack(fill="x", padx=12)

    def _update_tabs(self):
        m = self.mode.get()
        self._tab_screen.config(
            fg=C["text"] if m == "screen" else C["text3"],
            bg=C["bg2"] if m == "screen" else C["bg"])
        self._tab_upload.config(
            fg=C["text"] if m == "upload" else C["text3"],
            bg=C["bg2"] if m == "upload" else C["bg"])

    # ── File pickers ──────────────────────────────────────────────────────────
    def _pick_image(self):
        path = filedialog.askopenfilename(
            title="Pick an image",
            filetypes=[("Images", "*.png *.jpg *.jpeg *.gif *.webp"), ("All", "*.*")]
        )
        if not path:
            return
        try:
            b64, mime = load_image_b64(path)
            self._uploaded_img_b64  = b64
            self._uploaded_img_mime = mime
            self._uploaded_file_text = None
            name = os.path.basename(path)
            self._uploaded_img_name = name
            self.upload_lbl.config(text=f"✓  {name}", fg=C["text"])

            # show thumbnail in upload preview
            if HAS_PIL:
                img = Image.open(path)
                img.thumbnail((240, 135), Image.LANCZOS)
                ph = ImageTk.PhotoImage(img)
                self._upload_thumb = ph
                self.upload_prev_lbl.config(image=ph, text="", width=240, height=135)
        except Exception as e:
            self.upload_lbl.config(text=f"⚠ {e}", fg=C["danger"])

    def _pick_text_file(self):
        path = filedialog.askopenfilename(
            title="Pick a file",
            filetypes=[("Text / Code", "*.txt *.md *.py *.js *.ts *.html *.css *.json *.csv *.yaml *.toml *.xml"), ("All", "*.*")]
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                text = f.read(20000)  # cap at 20k chars
            self._uploaded_file_text = text
            self._uploaded_img_b64   = None
            self._uploaded_img_mime  = None
            name = os.path.basename(path)
            self._uploaded_img_name  = name
            self.upload_lbl.config(text=f"✓  {name}  ({len(text)} chars)", fg=C["text"])
            self._upload_thumb = None
            self.upload_prev_lbl.config(image="", text=f"{name}\n{len(text):,} chars", width=240, height=135)
        except Exception as e:
            self.upload_lbl.config(text=f"⚠ {e}", fg=C["danger"])

    def _pick_file(self):
        """Called when clicking the upload label — opens image picker by default.
        Use the PICK FILE button below for text/code files."""
        self._pick_image()

    # ── Drag ──────────────────────────────────────────────────────────────────
    def _ds(self, e):
        self._dx = e.x_root - self.root.winfo_x()
        self._dy = e.y_root - self.root.winfo_y()

    def _dm(self, e):
        x = max(0, min(e.x_root - self._dx, self.root.winfo_screenwidth()  - self.W))
        y = max(0, min(e.y_root - self._dy, self.root.winfo_screenheight() - self.H))
        self.root.geometry(f"+{x}+{y}")

    # ── Minimize ──────────────────────────────────────────────────────────────
    def _minimize(self):
        self.root.overrideredirect(False)
        self.root.iconify()
        def _restore(e):
            self.root.deiconify()
            self.root.overrideredirect(True)
            self.root.attributes("-topmost", True)
            self.root.unbind("<Map>")
        self.root.bind("<Map>", _restore)

    # ── Preview ───────────────────────────────────────────────────────────────
    def _refresh_thumb(self):
        def _go():
            idx   = self.sel_mon.get()
            thumb = get_thumb(idx, 240, 135)
            def _ui():
                if thumb:
                    self._thumb = thumb
                    self.prev_lbl.config(image=thumb, text="", width=240, height=135)
                else:
                    self.prev_lbl.config(text="pip install mss pillow", width=240, height=135)
            self.root.after(0, _ui)
        threading.Thread(target=_go, daemon=True).start()

    # ── Status / response ──────────────────────────────────────────────────────
    def _setstatus(self, msg, color=None):
        self.root.after(0, lambda: self.status.config(text=msg, fg=color or C["text3"]))

    def _setresp(self, text):
        def _ui():
            self.resp.config(state="normal")
            self.resp.delete("1.0", "end")
            self.resp.insert("end", text)
            self.resp.config(state="disabled")
        self.root.after(0, _ui)

    # ── Actions ───────────────────────────────────────────────────────────────
    def _do_analyse(self):
        p = self.prompt.get().strip() or "Describe everything you see in detail."
        self._run(p)

    def _do_solve(self):
        p = self.prompt.get().strip() or (
            "Look at this carefully. Identify any problem, error, task, or question. "
            "Provide a clear, direct solution or answer."
        )
        self._run(p)

    def _run(self, prompt):
        mode = self.mode.get()
        self._setresp("")

        # ── Upload mode ──────────────────────────────────────────────────────
        if mode == "upload":
            if self._uploaded_img_b64:
                # Image upload → vision
                self._setstatus("Sending image…", C["orange"])
                call_vision(
                    self._uploaded_img_b64,
                    self._uploaded_img_mime or "image/png",
                    prompt,
                    on_done=lambda t: (self._setstatus("✓ Done", C["green"]), self._setresp(t)),
                    on_status=self._setstatus,
                )
            elif self._uploaded_file_text:
                # Text file upload → text model
                combined = f"{prompt}\n\n[FILE: {self._uploaded_img_name}]\n{self._uploaded_file_text}"
                self._setstatus("Sending file…", C["orange"])
                call_text(
                    combined,
                    on_done=lambda t: (self._setstatus("✓ Done", C["green"]), self._setresp(t)),
                    on_status=self._setstatus,
                )
            else:
                self._setstatus("No file selected.", C["danger"])
            return

        # ── Screen mode ──────────────────────────────────────────────────────
        self._setstatus("Capturing screen…", C["orange"])

        def _go():
            idx     = self.sel_mon.get()
            img_b64 = take_screenshot(idx)
            if img_b64 is None:
                self._setstatus("⚠ Capture failed — pip install mss pillow", C["danger"])
                self._setresp("Could not capture screen.\nRun: pip install mss pillow")
                return
            self._setstatus("Analysing…", C["text2"])
            self._refresh_thumb()
            call_vision(
                img_b64, "image/png", prompt,
                on_done=lambda t: (self._setstatus("✓ Done", C["green"]), self._setresp(t)),
                on_status=self._setstatus,
            )
        threading.Thread(target=_go, daemon=True).start()

    def run(self):
        self.root.mainloop()

# ── Entry ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    ensure_deps()
    KyroxLens().run()
