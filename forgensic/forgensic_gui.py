import os
import sys
import json
import shutil
import threading
import datetime
from pathlib import Path
from PIL import Image, ImageDraw
import customtkinter as ctk
from tkinter import filedialog, messagebox
import webbrowser
import webbrowser
import tkinter as tk
from PIL import Image, ImageDraw, ImageFilter, ImageEnhance
import customtkinter as ctk
from pathlib import Path

try:
    from forgensic.app.pipeline import run_pipeline, build_findings_summary
    from forgensic.app.utils import build_results_payload
except ImportError:
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    try:
        from forgensic.app.pipeline import run_pipeline, build_findings_summary
        from forgensic.app.utils import build_results_payload
    except ImportError:
        def run_pipeline(**kwargs): raise RuntimeError("Backend not available")
        def build_findings_summary(*a, **k): return {}
        def build_results_payload(**k): return {}

ctk.set_appearance_mode("Light")

# ── Colour tokens ──────────────────────────────────────────────────────────────
PRIMARY      = "#14868C"
PRIMARY_DARK = "#0E6C71"
BG           = "#EEF8F9"
CARD         = "#FFFFFF"
BORDER       = "#C8E9EB"
TEXT         = "#0F172A"
TEXT_MUTED   = "#64748B"
SUCCESS      = "#10B981"
WARN         = "#F59E0B"
DANGER       = "#EF4444"
INFO         = "#3B82F6"
STEP_IDLE    = "#CBD5E1"   # dot colour when not yet reached
DIVIDER      = "#E8F0F1"
PRIMARY      = "#14868C"
PRIMARY_DARK = "#0E6C71"
PRIMARY_PALE = "#E8F7F8"
BG           = "#EEF8F9"
CARD         = "#FFFFFF"
BORDER       = "#C8E9EB"
TEXT         = "#0F172A"
TEXT_MUTED   = "#64748B"
SUCCESS      = "#10B981"
DANGER       = "#EF4444"
STEP_IDLE    = "#CBD5E1"
TEAL_LIGHT   = "#D0F0F2"
TEAL_MID     = "#A8DEE0"

# ── Pipeline steps ─────────────────────────────────────────────────────────────
STEPS = [
    ("📄", "Loading"),
    ("🔬", "Running Forgensic Algorithm"),
    ("💾", "Saving Outputs"),
]

# ── About Us content ───────────────────────────────────────────────────────────
ABOUT_TEXT = """\
Forgensic is a document integrity analysis tool developed under the \
Digital Public Infrastructure initiative by TANUH - the AI Centre of \
Excellence in Healthcare, in collaboration with IISc Bengaluru.

The system uses pattern-recognition algorithms to detect signs of \
tampering, editing, or forgery in scanned medical documents and \
prescriptions. All processing happens entirely offline on your machine; \
no document data is transmitted to any server.

TANUH focuses on building secure, AI-driven scalable Digital Public Infrastructure. \
This infrastructure empowers healthcare providers, insurers, and patients. \
Current tools are for Clinical Document evaluation and Insurance Policy processing. \
It also includes automated Privacy Filters for data redaction and rigorous Forgery Detection. \
Through these tools, TANUH delivers an end-to-end ecosystem built on efficiency and trust. \
Ultimately, TANUH AI technology is purpose-built to provide intelligent, secure, and transformative healthcare solutions for India.
"""

CONTACT_TEXT = """\
TANUH: AI Centre of Excellence in Healthcare
Indian Institute of Science
Seventh Floor, TCS Smart-X Hub
Bengaluru, India - 560 012
Email: dpi@tanuh.ai
Telephone: (080) 2293 4106 | (080) 2293 4107
"""

TEAM_MEMBERS = [
    {
        "name": "Nikhileswara Rao\nSulake",
        "image": "nikhil.png",
        "linkedin": "https://nikhil-rao20.github.io/",
        "role": "Engineering Intern",
        "org": "TANUH",
    },
    {
        "name": "Sai Manikanta Eswar\nMachara",
        "image": "eswar.png",
        "linkedin": "http://eswarmachara.github.io/",
        "role": "Engineering Intern",
        "org": "TANUH",
    },
    {
        "name": "Sivalal\nKethavath",
        "image": "sivalal.png",
        "linkedin": "https://www.linkedin.com/in/sivalal-kethavath-9b568a235/",
        "role": "Assistant Professor",
        "org": "RGUKT Nuzvid",
    },
    {
        "name": "Dr. Ashwin\nRaajKumar",
        "image": "ashwin.png",
        "linkedin": "https://www.linkedin.com/in/ashwin-rajkumar/",
        "role": "Program Manager",
        "org": "Breast Cancer Detection, TANUH",
    },
    {
        "name": "Dr. Hema\nPriyadarshini",
        "image": "hema.png",
        "linkedin": "https://www.linkedin.com/in/s-hema-priyadarshini-ph-d-64246314/",
        "role": "Program Manager",
        "org": "Chronic Kidney Disease, TANUH",
    },
    {
        "name": "Dr. Phaneendra\nYalavarthy",
        "image": "Prof_PKY.png",
        "linkedin": "https://www.linkedin.com/in/phaneendra-yalavarthy-88033462/",
        "role": "Chief Project Manager",
        "org": "TANUH FOUNDATION",
    },
]


# ── Helpers ────────────────────────────────────────────────────────────────────
def get_asset_path(filename):
    try:
        base = os.path.join(sys._MEIPASS, "frontend", "assets")
    except Exception:
        base = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "frontend", "assets"
        )
    full = os.path.join(base, filename)
    return full if os.path.exists(full) else filename


def safe_ts():
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


def save_outputs(root_dir: Path, stem: str,
                 annotated_path, findings_text: str, payload: dict,
                 run_stamp=None):
    """
    Directory layout:
                root_dir/
                    <stem>_<timestamp>/           ← one folder per analysed document
                        annotated.png
                        findings.txt
                        report.json
        Each analysis is stored in a timestamped folder.
    """
    stamp = run_stamp or safe_ts()
    doc_dir = root_dir / f"{stem}_{stamp}"
    doc_dir.mkdir(parents=True, exist_ok=True)
    saved = []

    # 1. Annotated image
    if annotated_path and os.path.exists(annotated_path):
        ext     = Path(annotated_path).suffix or ".png"
        img_out = doc_dir / f"annotated{ext}"
        shutil.copy2(annotated_path, img_out)
        saved.append(img_out)

    # 2. Findings text
    ts  = datetime.datetime.now().strftime("%d %b %Y  %H:%M:%S")
    txt = doc_dir / "findings.txt"
    txt.write_text(
        "\n".join([
            "=" * 56,
            "  FORGENSIC — DOCUMENT INTEGRITY REPORT",
            f"  Generated : {ts}",
            f"  Document  : {stem}",
            "=" * 56,
            "",
            findings_text,
            "",
            "=" * 56,
            "  END OF REPORT  |  © 2026 TANUH. All rights reserved.",
            "=" * 56,
        ]),
        encoding="utf-8"
    )
    saved.append(txt)

    # 3. JSON payload
    jsn = doc_dir / "report.json"
    try:
        jsn.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        saved.append(jsn)
    except Exception:
        pass

    return doc_dir, saved


# ── Animated pulse dot ─────────────────────────────────────────────────────────
class PulseDot(ctk.CTkCanvas):
    def __init__(self, master, size=12, color=PRIMARY, bg=CARD, **kw):
        super().__init__(master, width=size, height=size,
                         bg=bg, highlightthickness=0, **kw)
        self._size    = size
        self._color   = color
        self._radius  = 0
        self._growing = True
        self._active  = False
        self._job     = None
        self._draw()

    def _draw(self):
        self.delete("all")
        r     = self._size // 2
        inner = max(2, r - 3)
        if self._active:
            pr = int(r * (0.35 + 0.65 * self._radius / max(r, 1)))
            if pr > 0:
                self.create_oval(r - pr, r - pr, r + pr, r + pr,
                                 outline=self._color, width=1.5)
        fill = self._color if self._active else STEP_IDLE
        self.create_oval(r - inner, r - inner, r + inner, r + inner,
                         fill=fill, outline="")

    def _tick(self):
        if not self._active:
            return
        if self._growing:
            self._radius += 0.9
            if self._radius >= self._size // 2:
                self._growing = False
        else:
            self._radius -= 0.9
            if self._radius <= 0:
                self._growing = True
        self._draw()
        self._job = self.after(35, self._tick)

    def start(self):
        self._active = True
        self._tick()

    def stop(self, ok=True):
        self._active = False
        if self._job:
            self.after_cancel(self._job)
            self._job = None
        self._color  = SUCCESS if ok else DANGER
        self._radius = 0
        self._draw()

    def reset(self, bg=CARD):
        self._active  = False
        self._color   = PRIMARY
        self._radius  = 0
        self._growing = True
        self.configure(bg=bg)
        self._draw()


# ── Horizontal step chip ───────────────────────────────────────────────────────
class StepChip(ctk.CTkFrame):
    def __init__(self, master, icon, title, bg=CARD, **kw):
        super().__init__(master, fg_color="transparent", **kw)
        self._dot = PulseDot(self, size=10, color=PRIMARY, bg=bg)
        self._dot.pack(side="left", padx=(0, 5))
        self._lbl = ctk.CTkLabel(
            self, text=f"{icon} {title}",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=STEP_IDLE
        )
        self._lbl.pack(side="left")

    def set_active(self):
        self._dot.start()
        self._lbl.configure(text_color=PRIMARY)

    def set_done(self):
        self._dot.stop(ok=True)
        self._lbl.configure(text_color=SUCCESS)

    def set_error(self):
        self._dot.stop(ok=False)
        self._lbl.configure(text_color=DANGER)

    def reset(self, bg=CARD):
        self._dot.reset(bg=bg)
        self._lbl.configure(text_color=STEP_IDLE)


# ── Logo label — renders image at full fidelity ────────────────────────────────
class LogoLabel(ctk.CTkLabel):
    """Open an image at native resolution, cap at max_h px tall, preserve aspect."""
    def __init__(self, master, path, max_h=44, **kw):
        super().__init__(master, text="", **kw)
        try:
            img = Image.open(path).convert("RGBA")
            # Scale so height == max_h, width proportional
            w, h  = img.size
            scale = max_h / h
            new_w = max(1, int(w * scale))
            img   = img.resize((new_w, max_h), Image.Resampling.LANCZOS)
            ctk_img = ctk.CTkImage(light_image=img, dark_image=img,
                                   size=(new_w, max_h))
            self._ref = ctk_img          # keep reference alive
            self.configure(image=ctk_img)
        except Exception:
            self.configure(text=Path(path).stem.upper(),
                           font=ctk.CTkFont(size=10, weight="bold"),
                           text_color=TEXT_MUTED)


class ProfileCard(ctk.CTkFrame):
    def __init__(self, master, name, image_path, linkedin_url,
                 role="", org="", **kw):
        super().__init__(master, fg_color="transparent", **kw)

        avatar = self._build_circle_avatar(image_path, size=82, border=2)
        avatar_lbl = ctk.CTkLabel(self, text="", image=avatar)
        avatar_lbl.image = avatar
        avatar_lbl.pack(pady=(6, 6))

        ctk.CTkLabel(
            self, text=name,
            font=ctk.CTkFont(size=12, weight="bold"), text_color=TEXT,
            justify="center", wraplength=160
        ).pack(padx=8, pady=(0, 2))

        if role:
            ctk.CTkLabel(
                self, text=role,
                font=ctk.CTkFont(size=10), text_color=TEXT_MUTED,
                justify="center", wraplength=160
            ).pack(padx=8, pady=(0, 1))

        if org:
            ctk.CTkLabel(
                self, text=org,
                font=ctk.CTkFont(size=9), text_color="#94A3B8",
                justify="center", wraplength=160
            ).pack(padx=8, pady=(0, 4))

        ctk.CTkButton(
            self, text="Profile Link", width=90, height=22,
            font=ctk.CTkFont(size=10),
            fg_color="transparent", text_color=PRIMARY,
            hover_color="#EAF5F6",
            border_width=0,
            command=lambda url=linkedin_url: webbrowser.open(url)
        ).pack(pady=(0, 6))

    def _build_circle_avatar(self, image_path, size=84, border=2):
        try:
            img = Image.open(get_asset_path(image_path)).convert("RGBA")
            w, h = img.size
            side = min(w, h)
            left = (w - side) // 2
            top = (h - side) // 2
            img = img.crop((left, top, left + side, top + side))
            img = img.resize((size, size), Image.Resampling.LANCZOS)

            mask = Image.new("L", (size, size), 0)
            draw = ImageDraw.Draw(mask)
            draw.ellipse((0, 0, size, size), fill=255)
            img.putalpha(mask)

            border_size = size + border * 2
            canvas = Image.new("RGBA", (border_size, border_size), (0, 0, 0, 0))
            border_draw = ImageDraw.Draw(canvas)
            border_draw.ellipse(
                (0, 0, border_size - 1, border_size - 1),
                outline="#E5E7EB", width=border
            )
            canvas.paste(img, (border, border), img)
            return ctk.CTkImage(
                light_image=canvas, dark_image=canvas,
                size=(border_size, border_size)
            )
        except Exception:
            border_size = size + border * 2
            fallback = Image.new("RGBA", (border_size, border_size), (255, 255, 255, 0))
            return ctk.CTkImage(light_image=fallback, dark_image=fallback,
                                size=(border_size, border_size))


def _make_circle_avatar(image_path, size=88):
    """Crop to square, resize, apply circular mask. No border/ring."""
    try:
        img = Image.open(get_asset_path(image_path)).convert("RGBA")
        w, h = img.size
        side = min(w, h)
        img = img.crop(((w - side) // 2, (h - side) // 2,
                         (w + side) // 2, (h + side) // 2))
        img = img.resize((size, size), Image.Resampling.LANCZOS)
        mask = Image.new("L", (size, size), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, size, size), fill=255)
        img.putalpha(mask)
    except Exception:
        img = Image.new("RGBA", (size, size), (220, 220, 220, 255))
        mask = Image.new("L", (size, size), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, size, size), fill=255)
        img.putalpha(mask)
    return ctk.CTkImage(light_image=img, dark_image=img, size=(size, size))
 
 
class TeamCard(ctk.CTkFrame):
    """Single team member card with hover lift effect."""
 
    W, H = 200, 265
 
    def __init__(self, master, name, image_path, linkedin_url,
                 role="", org="", **kw):
        super().__init__(
            master,
            width=self.W, height=self.H,
            fg_color=CARD,
            border_color=BORDER, border_width=1,
            corner_radius=18,
            **kw
        )
        self.pack_propagate(False)
        self._url = linkedin_url
        self._hovered = False
 
        # ── Avatar ────────────────────────────────────────────────────────
        avatar = _make_circle_avatar(image_path, size=90)
        av_lbl = ctk.CTkLabel(self, text="", image=avatar)
        av_lbl.image = avatar
        av_lbl.pack(pady=(22, 10))
 
        # ── Name ──────────────────────────────────────────────────────────
        ctk.CTkLabel(
            self, text=name,
            font=ctk.CTkFont(family="Georgia", size=13, weight="bold"),
            text_color=TEXT,
            justify="center", wraplength=self.W - 24
        ).pack(padx=12, pady=(0, 3))
 
        # ── Role ──────────────────────────────────────────────────────────
        if role:
            ctk.CTkLabel(
                self, text=role,
                font=ctk.CTkFont(size=11),
                text_color=PRIMARY,
                justify="center", wraplength=self.W - 24
            ).pack(padx=12, pady=(0, 2))
 
        # ── Org ───────────────────────────────────────────────────────────
        if org:
            ctk.CTkLabel(
                self, text=org,
                font=ctk.CTkFont(size=10),
                text_color=TEXT_MUTED,
                justify="center", wraplength=self.W - 24
            ).pack(padx=12, pady=(0, 8))
 
        # ── Divider ───────────────────────────────────────────────────────
        ctk.CTkFrame(self, fg_color=DIVIDER, height=1).pack(
            fill="x", padx=20, pady=(4, 0))
 
        # ── Profile button ────────────────────────────────────────────────
        self._btn = ctk.CTkButton(
            self,
            text="View Profile  →",
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color="transparent",
            text_color=PRIMARY,
            hover_color=PRIMARY_PALE,
            border_width=0,
            corner_radius=0,
            height=36,
            command=lambda: webbrowser.open(linkedin_url)
        )
        self._btn.pack(fill="x", padx=0, pady=(0, 0))
 
        # ── Hover bindings ────────────────────────────────────────────────
        self._bind_hover(self)
 
    def _bind_hover(self, w):
        w.bind("<Enter>", self._enter, add="+")
        w.bind("<Leave>", self._leave, add="+")
        for c in w.winfo_children():
            self._bind_hover(c)
 
    def _enter(self, _=None):
        if not self._hovered:
            self._hovered = True
            self.configure(border_color=PRIMARY, border_width=2,
                           fg_color="#F7FEFF")
            self._btn.configure(text_color=PRIMARY_DARK,
                                fg_color=PRIMARY_PALE)
 
    def _leave(self, _=None):
        try:
            x = self.winfo_pointerx() - self.winfo_rootx()
            y = self.winfo_pointery() - self.winfo_rooty()
            if 0 <= x <= self.winfo_width() and 0 <= y <= self.winfo_height():
                return
        except Exception:
            pass
        self._hovered = False
        self.configure(border_color=BORDER, border_width=1, fg_color=CARD)
        self._btn.configure(text_color=PRIMARY, fg_color="transparent")
 
 
class AboutWindow(ctk.CTkToplevel):
 
    def __init__(self, master):
        super().__init__(master)
        self.title("About  ·  Forgensic")
        self.geometry("820x700")
        self.minsize(780, 600)
        self.configure(fg_color=BG)
        self.grab_set()
        self.focus_set()
 
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)
 
        self._build_header()
        self._build_body()
 
    # ── HEADER ────────────────────────────────────────────────────────────────
    def _build_header(self):
        hdr = ctk.CTkFrame(self, height=78, corner_radius=0, fg_color=PRIMARY)
        hdr.grid(row=0, column=0, sticky="ew")
        hdr.grid_propagate(False)
 
        # Logo
        try:
            from pathlib import Path
            from PIL import Image as PILImage
            lp = get_asset_path("tanuh.png")
            img = PILImage.open(lp).convert("RGBA")
            w, h = img.size
            nw = int(w * 44 / h)
            img = img.resize((nw, 44), PILImage.Resampling.LANCZOS)
            ci = ctk.CTkImage(light_image=img, dark_image=img, size=(nw, 44))
            logo_lbl = ctk.CTkLabel(hdr, text="", image=ci)
            logo_lbl.image = ci
            logo_lbl.place(relx=0.0, rely=0.5, anchor="w", x=24)
            title_x = 24 + nw + 14
        except Exception:
            title_x = 24
 
        # Title
        title_frame = ctk.CTkFrame(hdr, fg_color="transparent")
        title_frame.place(x=title_x, rely=0.5, anchor="w")
        ctk.CTkLabel(
            title_frame, text="Forgensic",
            font=ctk.CTkFont(family="Georgia", size=22, weight="bold"),
            text_color="white"
        ).pack(anchor="w")
        ctk.CTkLabel(
            title_frame, text="Document Integrity Analysis  ·  TANUH AI, IISc Bengaluru",
            font=ctk.CTkFont(size=10),
            text_color="#B2E0E3"
        ).pack(anchor="w")
 
        # Close button
        ctk.CTkButton(
            hdr, text="✕", width=34, height=34,
            fg_color="#1A9AA0", text_color="white",
            hover_color=PRIMARY_DARK,
            border_width=0, corner_radius=8,
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self.destroy
        ).place(relx=1.0, rely=0.5, anchor="e", x=-22)
 
    # ── BODY ──────────────────────────────────────────────────────────────────
    def _build_body(self):
        scroll = ctk.CTkScrollableFrame(
            self, fg_color=BG,
            scrollbar_button_color=TEAL_MID,
            scrollbar_button_hover_color=PRIMARY
        )
        scroll.grid(row=1, column=0, sticky="nsew")
        scroll.grid_columnconfigure(0, weight=1)
 
        # ── About block ───────────────────────────────────────────────────
        about_card = ctk.CTkFrame(
            scroll, fg_color=CARD,
            border_color=BORDER, border_width=1,
            corner_radius=14
        )
        about_card.pack(fill="x", padx=26, pady=(22, 0))
        ctk.CTkLabel(
            about_card, text=ABOUT_TEXT,
            font=ctk.CTkFont(size=13),
            text_color=TEXT,
            justify="left", wraplength=700, anchor="nw"
        ).pack(padx=20, pady=16, anchor="nw")
 
        # ── Team heading ──────────────────────────────────────────────────
        hrow = ctk.CTkFrame(scroll, fg_color="transparent")
        hrow.pack(fill="x", padx=26, pady=(26, 14))
 
        ctk.CTkFrame(hrow, fg_color=PRIMARY, width=4, height=22,
                     corner_radius=2).pack(side="left", padx=(0, 10))
        ctk.CTkLabel(
            hrow, text="Core Team",
            font=ctk.CTkFont(family="Georgia", size=17, weight="bold"),
            text_color=TEXT
        ).pack(side="left")
        ctk.CTkLabel(
            hrow, text=f"  {len(TEAM_MEMBERS)} members",
            font=ctk.CTkFont(size=11),
            text_color=TEXT_MUTED
        ).pack(side="left", pady=(2, 0))
 
        # ── Team grid ─────────────────────────────────────────────────────
        grid = ctk.CTkFrame(scroll, fg_color="transparent")
        grid.pack(fill="x", padx=26, pady=(0, 20))
        COLS = 3
        for c in range(COLS):
            grid.grid_columnconfigure(c, weight=1)
 
        for idx, m in enumerate(TEAM_MEMBERS):
            r, c = divmod(idx, COLS)
            TeamCard(
                grid,
                name=m["name"],
                image_path=m["image"],
                linkedin_url=m["linkedin"],
                role=m.get("role", ""),
                org=m.get("org", ""),
            ).grid(row=r, column=c, padx=8, pady=8, sticky="nsew")
 
        # ── Contact block ─────────────────────────────────────────────────
        hrow2 = ctk.CTkFrame(scroll, fg_color="transparent")
        hrow2.pack(fill="x", padx=26, pady=(6, 10))
        ctk.CTkFrame(hrow2, fg_color=PRIMARY, width=4, height=22,
                     corner_radius=2).pack(side="left", padx=(0, 10))
        ctk.CTkLabel(
            hrow2, text="Contact",
            font=ctk.CTkFont(family="Georgia", size=17, weight="bold"),
            text_color=TEXT
        ).pack(side="left")
 
        contact_card = ctk.CTkFrame(
            scroll, fg_color=CARD,
            border_color=BORDER, border_width=1,
            corner_radius=14
        )
        contact_card.pack(fill="x", padx=26, pady=(0, 4))
        ctk.CTkLabel(
            contact_card, text=CONTACT_TEXT,
            font=ctk.CTkFont(size=13),
            text_color=TEXT,
            justify="left", wraplength=700, anchor="nw"
        ).pack(padx=20, pady=16, anchor="nw")
 
        # ── Footer ────────────────────────────────────────────────────────
        foot = ctk.CTkFrame(scroll, fg_color="transparent")
        foot.pack(fill="x", padx=26, pady=(16, 22))
        ctk.CTkLabel(
            foot,
            text="© 2026 TANUH. All rights reserved.  ·  Offline · No data transmitted.",
            font=ctk.CTkFont(size=10),
            text_color=STEP_IDLE
        ).pack(side="left")
 
# ── Main application ───────────────────────────────────────────────────────────
class ForgensicApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Forgensic – Document Forgery Detection")
        self.geometry("1440x920")
        self.minsize(1200, 780)
        self.configure(fg_color=BG)

        try:
            from PIL import ImageTk, Image
            icon_img = ImageTk.PhotoImage(Image.open(get_asset_path("tanuh.png")))
            self.iconphoto(False, icon_img)
            if sys.platform.startswith("win"):
                self.iconbitmap(get_asset_path("tanuh.ico"))
        except Exception:
            pass

        self.file_path              = None
        self.output_dir             = Path.home() / "Forgensic_Outputs"
        self.current_annotated_path = None
        self.current_original_path  = None
        self.current_display_image  = None
        self._step_chips            = []
        self._current_step          = -1
        self._last_payload          = {}
        self._current_run_stamp     = None
        self._pre_dim_image         = None
        self._pulse_job             = None
        self._pulse_base            = None
        self._pulse_alpha           = 0.0
        self._pulse_dir             = 1

        self.grid_rowconfigure(1, weight=1)
        self.grid_rowconfigure(2, weight=0)
        self.grid_columnconfigure(0, weight=1)

        self._build_header()
        self._build_content()
        self._build_footer()

    # ── HEADER ────────────────────────────────────────────────────────────────
    def _build_header(self):
        hdr = ctk.CTkFrame(self, height=72, corner_radius=0,
                           fg_color=CARD, border_color=BORDER, border_width=1)
        hdr.grid(row=0, column=0, sticky="ew")
        hdr.grid_propagate(False)
        hdr.grid_columnconfigure(1, weight=1)

        # ── Left: TANUH logo + brand text ──────────────────────────────────
        left = ctk.CTkFrame(hdr, fg_color="transparent")
        left.grid(row=0, column=0, padx=22, pady=10, sticky="w")

        tanuh_logo = LogoLabel(left, get_asset_path("tanuh.png"), max_h=40)
        tanuh_logo.pack(side="left", padx=(0, 12))

        brand = ctk.CTkFrame(left, fg_color="transparent")
        brand.pack(side="left")
        ctk.CTkLabel(
            brand, text="Digital Public Infrastructure",
            font=ctk.CTkFont(family="Georgia", size=20, weight="bold"),
            text_color=PRIMARY
        ).pack(anchor="w")
        ctk.CTkLabel(
            brand, text="TANUH: AI Center of Excellence in Healthcare",
            font=ctk.CTkFont(size=11), text_color=TEXT_MUTED
        ).pack(anchor="w")

        # ── Right: About + MoE + IISc logos ───────────────────────────────
        right = ctk.CTkFrame(hdr, fg_color="transparent")
        right.grid(row=0, column=2, padx=22, pady=10, sticky="e")

        ctk.CTkButton(
            right, text="ℹ  About",
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="transparent", text_color="black",
            hover_color=BG, border_color=BORDER, border_width=1,
            width=80, height=30,
            command=self._open_about
        ).pack(side="left", padx=(0, 16))

        # MoE and IISc logos — rendered at full quality
        for fname, h in [("tanuh.png", 50), ("MoE_LOGO_p.png", 50), ("IISc_Logo.png", 50)]:
            LogoLabel(right, get_asset_path(fname), max_h=h).pack(
                side="left", padx=8
            )

    # ── FOOTER ────────────────────────────────────────────────────────────────
    def _build_footer(self):
        ft = ctk.CTkFrame(self, height=28, corner_radius=0,
                          fg_color=CARD, border_color=BORDER, border_width=1)
        ft.grid(row=2, column=0, sticky="ew")
        ft.grid_propagate(False)
        ctk.CTkLabel(
            ft, text="© 2026 TANUH AI. All rights reserved. Should be © 2026 TANUH. All rights reserved.",
            font=ctk.CTkFont(size=11, weight="bold"), text_color=TEXT_MUTED
        ).place(relx=0.5, rely=0.5, anchor="center")
        ctk.CTkLabel(
            ft, text="Offline · No data transmitted",
            font=ctk.CTkFont(size=11), text_color=STEP_IDLE
        ).pack(side="right", padx=24, pady=8)

    # ── CONTENT ───────────────────────────────────────────────────────────────
    def _build_content(self):
        card = ctk.CTkFrame(self, fg_color=CARD, corner_radius=16,
                            border_color=BORDER, border_width=1)
        card.grid(row=1, column=0, padx=28, pady=(20, 12), sticky="nsew")
        card.grid_columnconfigure(0, weight=1)
        card.grid_rowconfigure(2, weight=1)

        # ── Controls bar ────────────────────────────────────────────────────
        ctrl = ctk.CTkFrame(card, fg_color="transparent")
        ctrl.grid(row=0, column=0, padx=24, pady=(18, 6), sticky="ew")
        ctrl.grid_columnconfigure(1, weight=1)

        left_btns = ctk.CTkFrame(ctrl, fg_color="transparent")
        left_btns.grid(row=0, column=0, sticky="w")

        self.upload_btn = ctk.CTkButton(
            left_btns, text="📂  Select Document",
            font=ctk.CTkFont(weight="bold", size=13),
            fg_color="#F1F5F9", text_color=TEXT,
            border_color=BORDER, border_width=1,
            hover_color="#E2EEF0", width=190, height=42,
            command=self.select_file
        )
        self.upload_btn.pack(side="left", padx=(0, 10))

        self.outdir_btn = ctk.CTkButton(
            left_btns, text="📁  Output Folder",
            font=ctk.CTkFont(size=13),
            fg_color="#F1F5F9", text_color=TEXT_MUTED,
            border_color=BORDER, border_width=1,
            hover_color="#E2EEF0", width=155, height=42,
            command=self.choose_output_dir
        )
        self.outdir_btn.pack(side="left", padx=(0, 8))

        self.outdir_label = ctk.CTkLabel(
            left_btns,
            text=f"→ {self._short(self.output_dir)}",
            font=ctk.CTkFont(size=11), text_color=TEXT_MUTED
        )
        self.outdir_label.pack(side="left")

        self.analyze_btn = ctk.CTkButton(
            ctrl, text="Analyse Document  🚀",
            font=ctk.CTkFont(weight="bold", size=14),
            fg_color=PRIMARY, text_color="white", hover_color=PRIMARY_DARK,
            width=210, height=42, state="disabled",
            command=self.start_analysis
        )
        self.analyze_btn.grid(row=0, column=2, sticky="e")

        # ── Status + stepper row ─────────────────────────────────────────────
        sr = ctk.CTkFrame(card, fg_color="transparent")
        sr.grid(row=1, column=0, padx=24, pady=(0, 4), sticky="ew")
        sr.grid_columnconfigure(0, weight=1)

        self.status_lbl = ctk.CTkLabel(
            sr,
            text="Upload a medical document or image to begin.",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=TEXT_MUTED, anchor="w"
        )
        self.status_lbl.grid(row=0, column=0, sticky="w")

        # Horizontal stepper — hidden until analysis starts
        self.stepper_frame = ctk.CTkFrame(sr, fg_color=BG, corner_radius=8)
        self.stepper_frame.grid(row=0, column=1, padx=(14, 0), sticky="e")
        self.stepper_frame.grid_remove()

        self._step_chips = []
        for i, (icon, title) in enumerate(STEPS):
            chip = StepChip(self.stepper_frame, icon, title, bg=BG)
            chip.pack(side="left", padx=10, pady=6)
            self._step_chips.append(chip)
            if i < len(STEPS) - 1:
                ctk.CTkLabel(
                    self.stepper_frame, text="›",
                    font=ctk.CTkFont(size=16, weight="bold"),
                    text_color="#C8E9EB"
                ).pack(side="left")

        self.progress_bar = ctk.CTkProgressBar(
            sr, mode="indeterminate",
            progress_color=PRIMARY, height=3, width=110
        )
        self.progress_bar.grid(row=0, column=2, padx=(10, 0), sticky="e")
        self.progress_bar.grid_remove()

        # ── Split pane ───────────────────────────────────────────────────────
        pane = ctk.CTkFrame(card, fg_color="transparent")
        pane.grid(row=2, column=0, padx=24, pady=(0, 20), sticky="nsew")
        pane.grid_columnconfigure(0, weight=37)
        pane.grid_columnconfigure(1, weight=63)
        pane.grid_rowconfigure(0, weight=1)

        self._build_left(pane)
        self._build_right(pane)

    # ── LEFT PANEL ────────────────────────────────────────────────────────────
    def _build_left(self, parent):
        lf = ctk.CTkFrame(parent, fg_color="#F8FAFC", corner_radius=12,
                          border_color=BORDER, border_width=1)
        lf.grid(row=0, column=0, padx=(0, 12), sticky="nsew")
        lf.grid_rowconfigure(1, weight=1)
        lf.grid_columnconfigure(0, weight=1)

        lh = ctk.CTkFrame(lf, fg_color="transparent")
        lh.grid(row=0, column=0, padx=16, pady=(16, 6), sticky="ew")

        ctk.CTkLabel(
            lh, text="Forensic Findings",
            font=ctk.CTkFont(size=16, weight="bold"), text_color=PRIMARY
        ).pack(side="left")

        self.copy_btn = ctk.CTkButton(
            lh, text="📋 Copy", width=72, height=28,
            fg_color="#E2E8F0", text_color=TEXT,
            hover_color="#CBD5E1", command=self.copy_text
        )
        self.copy_btn.pack(side="right")

        self.save_btn = ctk.CTkButton(
            lh, text="💾 Save", width=72, height=28,
            fg_color=PRIMARY, text_color="white",
            hover_color=PRIMARY_DARK, command=self.save_results
        )
        self.save_btn.pack(side="right", padx=(0, 6))

        self.findings_box = ctk.CTkScrollableFrame(lf, fg_color="transparent")
        self.findings_box.grid(row=1, column=0, padx=8, pady=(0, 12), sticky="nsew")
        self.hidden_copy_text = ""

    # ── RIGHT PANEL ───────────────────────────────────────────────────────────
    def _build_right(self, parent):
        rf = ctk.CTkFrame(parent, fg_color="#F8FAFC", corner_radius=12,
                          border_color=BORDER, border_width=1)
        rf.grid(row=0, column=1, sticky="nsew")
        rf.grid_rowconfigure(1, weight=1)
        rf.grid_columnconfigure(0, weight=1)

        rh = ctk.CTkFrame(rf, fg_color="transparent")
        rh.grid(row=0, column=0, padx=16, pady=(16, 4), sticky="ew")

        self.img_title = ctk.CTkLabel(
            rh, text="Document Preview",
            font=ctk.CTkFont(size=16, weight="bold"), text_color=PRIMARY
        )
        self.img_title.pack(side="left")

        vb = ctk.CTkFrame(rh, fg_color="transparent")
        vb.pack(side="right")
        for txt, cmd in [("↩ Reset", self.reset_view),
                         ("📄 Original", self.open_original),
                         ("🔎 Annotated", self.open_annotated)]:
            ctk.CTkButton(
                vb, text=txt, width=100, height=28,
                fg_color="#E2E8F0", text_color=TEXT,
                hover_color="#CBD5E1", command=cmd
            ).pack(side="left", padx=3)

        self.img_canvas = ctk.CTkFrame(rf, fg_color="transparent")
        self.img_canvas.grid(row=1, column=0, padx=12, pady=(0, 12), sticky="nsew")
        self.img_canvas.grid_rowconfigure(0, weight=1)
        self.img_canvas.grid_columnconfigure(0, weight=1)

        self.img_label = ctk.CTkLabel(
            self.img_canvas,
            text="Preview will appear here after analysis.",
            text_color=STEP_IDLE, font=ctk.CTkFont(size=16, weight="bold")
        )
        self.img_label.grid(row=0, column=0)
        self.img_canvas.bind("<Configure>", self._on_resize)

    # ── ACTIONS ───────────────────────────────────────────────────────────────
    def _open_about(self):
        AboutWindow(self)

    def select_file(self):
        path = filedialog.askopenfilename(title="Select Medical Document")
        if not path:
            return
        self.file_path = Path(path)
        self.current_original_path = self.file_path
        self.current_annotated_path = None
        self.status_lbl.configure(
            text=f"✅  Ready: {self.file_path.name}", text_color=SUCCESS
        )
        self.analyze_btn.configure(state="normal")
        self._stop_processing_pulse()
        try:
            self.current_display_image = Image.open(self.file_path)
            self.img_title.configure(text="Original Document")
            self._render()
        except Exception:
            self.current_display_image = None
            self.img_title.configure(text="Document Preview")
            self.img_label.configure(image=None, text="Preview not available.")
        for w in self.findings_box.winfo_children():
            w.destroy()

    def choose_output_dir(self):
        d = filedialog.askdirectory(title="Choose Output Root Directory",
                                    initialdir=str(self.output_dir))
        if d:
            self.output_dir = Path(d)
            self.outdir_label.configure(text=f"→ {self._short(self.output_dir)}")

    @staticmethod
    def _short(p: Path, n=40):
        s = str(p)
        return s if len(s) <= n else "…" + s[-(n - 1):]

    # ── ANALYSIS ─────────────────────────────────────────────────────────────
    def start_analysis(self):
        if not self.file_path:
            return
        self._current_run_stamp = safe_ts()
        self._pre_dim_image = self.current_display_image
        if self.current_display_image:
            self.img_title.configure(text="Processing…")
            self._start_processing_pulse()
        else:
            self.img_label.configure(text="Processing…", image=None)
        self.analyze_btn.configure(state="disabled", text="Processing…")
        self.upload_btn.configure(state="disabled")
        self.outdir_btn.configure(state="disabled")
        self.status_lbl.configure(
            text="⚙️  Analysing document — please wait…", text_color=PRIMARY
        )
        self.stepper_frame.grid()
        self.progress_bar.grid()
        self.progress_bar.start()
        self._current_step = -1
        for c in self._step_chips:
            c.reset(bg=BG)
        threading.Thread(target=self._pipeline_thread, daemon=True).start()

    def _step(self, idx):
        if 0 <= self._current_step < len(self._step_chips):
            self._step_chips[self._current_step].set_done()
        self._current_step = idx
        if idx < len(self._step_chips):
            self._step_chips[idx].set_active()

    def _pipeline_thread(self):
        try:
            self.after(0, self._step, 0)          # Loading
            work_dir = self.file_path.parent / f"forgensic_work_{self.file_path.stem}"
            run_output = run_pipeline(
                input_path=self.file_path, work_dir=work_dir,
                preset="super_loose", enable_ocr=True
            )
            pages       = run_output["pages"]
            results     = run_output["results"]
            export_info = run_output["export_info"]

            self.after(0, self._step, 1)           # Running Forgensic Algorithm
            findings_summary = build_findings_summary(
                pages, results, max_per_page=10, min_area_ratio=0.0
            )
            payload = build_results_payload(
                job_id="local", file_name=self.file_path.name,
                pages=pages, results=results, export_info=export_info,
                findings_summary=findings_summary,
                file_url_map={}, preview_url_map={},
                pipeline_version="desktop-1.0",
                inference_seconds=0.0, avg_inference_seconds=0.0,
                created_at="local", updated_at="local"
            )

            self.after(0, self._step, 2)           # Saving Outputs
            self.after(0, self.on_complete, payload, pages)

        except Exception as e:
            self.after(0, self.on_error, str(e))

    # ── RESULTS ──────────────────────────────────────────────────────────────
    def on_complete(self, payload, pages):
        self._stop_processing_pulse()
        self.progress_bar.stop()
        self.progress_bar.grid_remove()
        if 0 <= self._current_step < len(self._step_chips):
            self._step_chips[self._current_step].set_done()

        self.analyze_btn.configure(state="normal", text="Analyse Document  🚀")
        self.upload_btn.configure(state="normal")
        self.outdir_btn.configure(state="normal")
        self.status_lbl.configure(text="✅  Analysis complete!", text_color=SUCCESS)

        for w in self.findings_box.winfo_children():
            w.destroy()

        findings_list = payload.get("findings_summary", {}).get("findings", [])
        self.hidden_copy_text = ""
        self._last_payload = payload

        if not findings_list:
            ctk.CTkLabel(
                self.findings_box,
                text="✅  No discrepancy found.\nDocument appears authentic.",
                font=ctk.CTkFont(size=14, weight="bold"), text_color=SUCCESS
            ).pack(pady=20, padx=10, anchor="w")
            self.hidden_copy_text = "No discrepancy found. Document appears authentic."
        else:
            self.hidden_copy_text = f"FORGERY FINDINGS — {len(findings_list)} issue(s) detected\n\n"
            rows = []
            for i, f in enumerate(findings_list):
                label = f.get("category_label", "Detected Discrepancy")
                text  = f.get("snippet", "")
                loc   = f.get("location", "")
                page  = f.get("page", 1)
                box   = f.get("box", {})

                row = ctk.CTkFrame(
                    self.findings_box, fg_color=CARD,
                    border_color="#E2E8F0", border_width=1, corner_radius=10
                )
                row.grid_columnconfigure(0, weight=1)

                pill_col = DANGER if "remov" in label.lower() else WARN
                pill = ctk.CTkFrame(row, fg_color=pill_col, height=3, corner_radius=0)
                pill.grid(row=0, column=0, columnspan=2, sticky="ew")

                tc = ctk.CTkFrame(row, fg_color="transparent")
                tc.grid(row=1, column=0, sticky="nsew", padx=13, pady=9)
                ctk.CTkLabel(
                    tc, text=f"#{i+1}  {label}",
                    font=ctk.CTkFont(size=13, weight="bold"),
                    text_color=TEXT, anchor="w"
                ).pack(anchor="w")
                if text:
                    ctk.CTkLabel(
                        tc, text=f'"{text}"',
                        font=ctk.CTkFont(size=12), text_color=TEXT_MUTED,
                        wraplength=300, justify="left", anchor="w"
                    ).pack(anchor="w", pady=(2, 0))
                ctk.CTkLabel(
                    tc, text=f"Page {page}  ·  {loc}",
                    font=ctk.CTkFont(size=11), text_color="#94A3B8", anchor="w"
                ).pack(anchor="w", pady=(3, 0))

                if box:
                    bf = ctk.CTkFrame(row, fg_color="transparent")
                    bf.grid(row=1, column=1, sticky="e", padx=12, pady=9)
                    ctk.CTkButton(
                        bf, text="🔎 View", width=85, height=30,
                        font=ctk.CTkFont(weight="bold"),
                        fg_color="#EFF6FF", text_color=INFO,
                        hover_color="#DBEAFE",
                        command=lambda b=box: self.highlight_area(b)
                    ).pack()

                rows.append(row)

                self.hidden_copy_text += f"[{i+1}] {label}  (Page {page})\n"
                if text:
                    self.hidden_copy_text += f'    "{text}"\n'
                self.hidden_copy_text += f"    Area: {loc}\n\n"

            self._animate_findings(rows)

        # Image
        self.current_original_path  = None
        self.current_annotated_path = None
        if pages and hasattr(pages[0], "preview_path") and pages[0].preview_path:
            self.current_annotated_path = pages[0].preview_path
            self.current_original_path  = (
                getattr(pages[0], "original_path", None)
                or getattr(pages[0], "image_path", None)
            )
            try:
                self.current_display_image = Image.open(self.current_annotated_path)
                self.img_title.configure(text="Annotated Document")
                self.after(60, self._render)
            except Exception:
                pass
        else:
            self.img_label.configure(text="No preview available.", image=None)

        # Auto-save
        self._do_save(silent=True)

    def on_error(self, err):
        self._stop_processing_pulse()
        self.progress_bar.stop()
        self.progress_bar.grid_remove()
        if 0 <= self._current_step < len(self._step_chips):
            self._step_chips[self._current_step].set_error()
        self.analyze_btn.configure(state="normal", text="Analyse Document  🚀")
        self.upload_btn.configure(state="normal")
        self.outdir_btn.configure(state="normal")
        self.status_lbl.configure(text=f"❌  Error: {err}", text_color=DANGER)
        if self._pre_dim_image is not None:
            self.current_display_image = self._pre_dim_image
            self.img_title.configure(text="Document Preview")
            self._render()
        messagebox.showerror("Pipeline Error", err)

    # ── IMAGE RENDERING ───────────────────────────────────────────────────────
    def _on_resize(self, event):
        if self.current_display_image:
            self._render()

    def _render(self):
        if not self.current_display_image:
            return
        self.img_canvas.update_idletasks()
        fw = self.img_canvas.winfo_width()
        fh = self.img_canvas.winfo_height()
        if fw < 50 or fh < 50:
            wh = self.winfo_height()
            fh = max(520, wh - 160)
            fw = max(640, int(fh * 0.78))
        img = self.current_display_image.copy()
        img.thumbnail((fw - 6, fh - 6), Image.Resampling.LANCZOS)
        ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=img.size)
        self.img_label.configure(image=ctk_img, text="")
        self.img_label.grid(row=0, column=0, sticky="nsew")

    def highlight_area(self, box):
        if not self.current_original_path:
            return
        try:
            img  = Image.open(self.current_original_path).convert("RGB")
            draw = ImageDraw.Draw(img)
            draw.rectangle(
                [box["x"], box["y"], box["x"] + box["w"], box["y"] + box["h"]],
                outline=DANGER, width=6
            )
            self.current_display_image = img
            self.img_title.configure(text="Isolated Forgery Region")
            self._render()
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def reset_view(self):
        if self.current_annotated_path:
            try:
                self.current_display_image = Image.open(self.current_annotated_path)
                self.img_title.configure(text="Annotated Document")
                self._render()
            except Exception:
                pass

    def _apply_dim(self, image, alpha=0.35):
        try:
            base = image.convert("RGB")
            overlay = Image.new("RGB", base.size, "white")
            return Image.blend(base, overlay, alpha)
        except Exception:
            return image

    def _start_processing_pulse(self):
        self._stop_processing_pulse()
        if not self.current_display_image:
            return
        self._pulse_base = self.current_display_image.copy()
        self._pulse_alpha = 0.18
        self._pulse_dir = 1
        self._pulse_tick()

    def _pulse_tick(self):
        if self._pulse_base is None:
            return
        self._pulse_alpha += 0.035 * self._pulse_dir
        if self._pulse_alpha >= 0.45:
            self._pulse_alpha = 0.45
            self._pulse_dir = -1
        elif self._pulse_alpha <= 0.12:
            self._pulse_alpha = 0.12
            self._pulse_dir = 1
        self.current_display_image = self._apply_dim(self._pulse_base, self._pulse_alpha)
        self._render()
        self._pulse_job = self.after(70, self._pulse_tick)

    def _stop_processing_pulse(self):
        if self._pulse_job:
            self.after_cancel(self._pulse_job)
        self._pulse_job = None
        self._pulse_base = None

    def _animate_findings(self, rows, start_pad=60, end_pad=4, delay=110):
        for i, row in enumerate(rows):
            self.after(i * delay, lambda r=row: self._slide_in_row(r, start_pad, end_pad))

    def _slide_in_row(self, row, start_pad, end_pad):
        if not row.winfo_exists():
            return
        row.pack(fill="x", pady=5, padx=(start_pad, 4))
        row._slide_pad = start_pad
        self._slide_step(row, end_pad)

    def _slide_step(self, row, end_pad):
        if not row.winfo_exists():
            return
        pad = max(end_pad, getattr(row, "_slide_pad", end_pad) - 6)
        row._slide_pad = pad
        row.pack_configure(padx=(pad, 4))
        if pad > end_pad:
            self.after(14, lambda: self._slide_step(row, end_pad))

    # ── SAVE / COPY ──────────────────────────────────────────────────────────
    def copy_text(self):
        self.clipboard_clear()
        self.clipboard_append(self.hidden_copy_text)
        self.copy_btn.configure(text="✅ Copied!")
        self.after(2000, lambda: self.copy_btn.configure(text="📋 Copy"))

    def save_results(self):
        self._do_save(silent=False)

    def _do_save(self, silent=False):
        if not self.file_path:
            return
        try:
            doc_dir, saved = save_outputs(
                root_dir=self.output_dir,
                stem=self.file_path.stem,
                annotated_path=self.current_annotated_path,
                findings_text=self.hidden_copy_text,
                payload=self._last_payload,
                run_stamp=self._current_run_stamp
            )
            if not silent:
                messagebox.showinfo(
                    "Saved",
                    f"Files saved to:\n{doc_dir}\n\n"
                    + "\n".join(f.name for f in saved)
                )
            self.status_lbl.configure(
                text=f"✅  Saved → {self._short(doc_dir)}",
                text_color=SUCCESS
            )
        except Exception as e:
            if not silent:
                messagebox.showerror("Save Error", str(e))

    def open_original(self):
        if self.current_original_path and os.path.exists(self.current_original_path):
            webbrowser.open(self.current_original_path)
        else:
            messagebox.showinfo("Not Found", "Original document not available.")

    def open_annotated(self):
        if self.current_annotated_path and os.path.exists(self.current_annotated_path):
            webbrowser.open(self.current_annotated_path)
        else:
            messagebox.showinfo("Not Found", "Annotated document not available.")


if __name__ == "__main__":
    import argparse
    import datetime
    
    # If arguments are passed, run in CLI mode
    if len(sys.argv) > 1:
        parser = argparse.ArgumentParser(description="Forgensic - Offline Document Forgery Detection")
        parser.add_argument("--input", "-i", required=True, help="Path to input document")
        parser.add_argument("--output", "-o", default=None, help="Output folder to save results")
        args = parser.parse_args()
        
        in_path = Path(args.input)
        if not in_path.exists():
            print(f"Error: Input file '{args.input}' not found.")
            sys.exit(1)
            
        out_dir = Path(args.output) if args.output else Path.cwd() / "Forgensic_Outputs"
        out_dir.mkdir(parents=True, exist_ok=True)
        
        print(f"[*] Starting Forgensic Analysis: {in_path.name}")
        work_dir = in_path.parent / f"forgensic_work_{in_path.stem}"
        try:
            run_output = run_pipeline(input_path=in_path, work_dir=work_dir, preset="super_loose", enable_ocr=True)
            pages = run_output["pages"]
            results = run_output["results"]
            findings_summary = build_findings_summary(pages, results, max_per_page=10, min_area_ratio=0.0)
            
            f_list = findings_summary.get("findings", [])
            print(f"\n[*] Analysis Complete! Found {len(f_list)} discrepancies.")
            for idx, f in enumerate(f_list):
                print(f"  {idx+1}. [{f.get('category_label', 'Issue')}] Page {f.get('page', 1)} - {f.get('snippet', '')}")
                
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            doc_dir = out_dir / f"{in_path.stem}_{ts}"
            doc_dir.mkdir(parents=True, exist_ok=True)
            if pages and getattr(pages[0], 'preview_path', None):
                import shutil
                shutil.copy2(pages[0].preview_path, doc_dir / f"annotated_{in_path.name}")
            
            txt_path = doc_dir / "findings.txt"
            txt_content = f"Forgensic Report: {in_path.name}\nTotal findings: {len(f_list)}\n\n"
            for f in f_list:
                txt_content += f"- {f.get('category_label')} (Page {f.get('page')}): {f.get('snippet', '')}\n"
            txt_path.write_text(txt_content, encoding="utf-8")
            
            print(f"[*] Results successfully saved to: {doc_dir}")
        except Exception as e:
            print(f"[!] Error during analysis: {e}")
            sys.exit(1)
            
    # Otherwise, run the beautiful Graphical Interface
    else:
        app = ForgensicApp()
        app.mainloop()