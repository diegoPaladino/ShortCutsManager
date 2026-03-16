import os
import sys
import json
import shutil
import time
import subprocess
import webbrowser
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import tkinter as tk
from tkinter import ttk, filedialog, simpledialog, messagebox

# matplotlib (já está no seu ambiente pelo pip list)
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

# Pillow para lidar com ícones (já está no seu pip list)
from PIL import Image, ImageTk

# =============== CONFIG ===============
APP_TITLE = "ShortCutsManager"
DATA_FILE = "usage_data.json"
REPORTS_DIR = "reports"
BACKUPS_DIR = "backups"

BACKUP_KEEP_LAST = 30  # mantém os 30 backups mais recentes
GRID_COLS = 4

# Ordem automática: "weekly" prioriza semana atual; "total" prioriza total
DEFAULT_SORT_MODE = "weekly"  # "weekly" | "total" | "alpha"
# =====================================


# ----------------- WINDOWS ICON EXTRACTION -----------------
# Extrai ícone de executáveis/atalhos em Windows usando ctypes (sem libs extras).
# Se falhar, cai para um ícone padrão.
IS_WINDOWS = os.name == "nt"
if IS_WINDOWS:
    import ctypes
    from ctypes import wintypes

    class ICONINFO(ctypes.Structure):
        _fields_ = [("fIcon", wintypes.BOOL),
                    ("xHotspot", wintypes.DWORD),
                    ("yHotspot", wintypes.DWORD),
                    ("hbmMask", wintypes.HBITMAP),
                    ("hbmColor", wintypes.HBITMAP)]

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

    ExtractIconExW = shell32.ExtractIconExW
    ExtractIconExW.argtypes = [wintypes.LPCWSTR, ctypes.c_int,
                               ctypes.POINTER(wintypes.HICON), ctypes.POINTER(wintypes.HICON),
                               ctypes.c_uint]
    ExtractIconExW.restype = ctypes.c_uint

    DestroyIcon = user32.DestroyIcon
    DestroyIcon.argtypes = [wintypes.HICON]
    DestroyIcon.restype = wintypes.BOOL

    GetIconInfo = user32.GetIconInfo
    GetIconInfo.argtypes = [wintypes.HICON, ctypes.POINTER(ICONINFO)]
    GetIconInfo.restype = wintypes.BOOL

    GetObjectW = gdi32.GetObjectW
    GetObjectW.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID]
    GetObjectW.restype = ctypes.c_int

    DeleteObject = gdi32.DeleteObject
    DeleteObject.argtypes = [wintypes.HGDIOBJ]
    DeleteObject.restype = wintypes.BOOL

    class BITMAP(ctypes.Structure):
        _fields_ = [("bmType", wintypes.LONG),
                    ("bmWidth", wintypes.LONG),
                    ("bmHeight", wintypes.LONG),
                    ("bmWidthBytes", wintypes.LONG),
                    ("bmPlanes", wintypes.WORD),
                    ("bmBitsPixel", wintypes.WORD),
                    ("bmBits", wintypes.LPVOID)]

    GetDIBits = gdi32.GetDIBits
    GetDIBits.argtypes = [
        wintypes.HDC, wintypes.HBITMAP,
        wintypes.UINT, wintypes.UINT,
        wintypes.LPVOID, wintypes.LPVOID,
        wintypes.UINT
    ]
    GetDIBits.restype = wintypes.INT

    CreateCompatibleDC = gdi32.CreateCompatibleDC
    CreateCompatibleDC.argtypes = [wintypes.HDC]
    CreateCompatibleDC.restype = wintypes.HDC

    DeleteDC = gdi32.DeleteDC
    DeleteDC.argtypes = [wintypes.HDC]
    DeleteDC.restype = wintypes.BOOL

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ("biSize", wintypes.DWORD),
            ("biWidth", wintypes.LONG),
            ("biHeight", wintypes.LONG),
            ("biPlanes", wintypes.WORD),
            ("biBitCount", wintypes.WORD),
            ("biCompression", wintypes.DWORD),
            ("biSizeImage", wintypes.DWORD),
            ("biXPelsPerMeter", wintypes.LONG),
            ("biYPelsPerMeter", wintypes.LONG),
            ("biClrUsed", wintypes.DWORD),
            ("biClrImportant", wintypes.DWORD),
        ]

    class BITMAPINFO(ctypes.Structure):
        _fields_ = [("bmiHeader", BITMAPINFOHEADER),
                    ("bmiColors", wintypes.DWORD * 3)]

    BI_RGB = 0

def _safe_int_week(now: datetime) -> str:
    # ISO week (mais estável para "semanal")
    iso_year, iso_week, _ = now.isocalendar()
    return f"{iso_year}-W{iso_week:02d}"

def _now_ts() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")

def _normalize_path(p: str) -> str:
    return os.path.normpath(p).strip()

def _is_url(s: str) -> bool:
    s = s.strip().lower()
    return s.startswith("http://") or s.startswith("https://")

def _ensure_dirs():
    os.makedirs(REPORTS_DIR, exist_ok=True)
    os.makedirs(BACKUPS_DIR, exist_ok=True)

def _load_json(path: str) -> Dict[str, Any]:
    if not os.path.exists(path):
        return {
            "version": 2,
            "settings": {
                "theme": "dark",
                "sort_mode": DEFAULT_SORT_MODE,
                "last_report_week": None
            },
            "shortcuts": {}
        }
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    # migração simples
    if "version" not in data:
        data = {
            "version": 2,
            "settings": {"theme": "dark", "sort_mode": DEFAULT_SORT_MODE, "last_report_week": None},
            "shortcuts": data.get("shortcuts", {})
        }
    if "settings" not in data:
        data["settings"] = {"theme": "dark", "sort_mode": DEFAULT_SORT_MODE, "last_report_week": None}
    if "sort_mode" not in data["settings"]:
        data["settings"]["sort_mode"] = DEFAULT_SORT_MODE
    if "theme" not in data["settings"]:
        data["settings"]["theme"] = "dark"
    if "last_report_week" not in data["settings"]:
        data["settings"]["last_report_week"] = None
    if "shortcuts" not in data:
        data["shortcuts"] = {}
    return data

def _backup_file(src: str):
    if not os.path.exists(src):
        return
    _ensure_dirs()
    dst = os.path.join(BACKUPS_DIR, f"{os.path.splitext(os.path.basename(src))[0]}_{_now_ts()}.json")
    shutil.copy2(src, dst)

    # mantém só os últimos N backups
    backups = [os.path.join(BACKUPS_DIR, f) for f in os.listdir(BACKUPS_DIR) if f.lower().endswith(".json")]
    backups.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    for old in backups[BACKUP_KEEP_LAST:]:
        try:
            os.remove(old)
        except Exception:
            pass

def _save_json_atomic(path: str, data: Dict[str, Any]):
    _ensure_dirs()
    if os.path.exists(path):
        _backup_file(path)

    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)
    os.replace(tmp, path)

def _week_key() -> str:
    return _safe_int_week(datetime.now())

def _get_weekly_count(sc: Dict[str, Any], week: str) -> int:
    wc = sc.get("weekly_clicks", {})
    return int(wc.get(week, 0))

def _increment_usage(sc: Dict[str, Any], week: str):
    sc["total_clicks"] = int(sc.get("total_clicks", 0)) + 1
    sc.setdefault("weekly_clicks", {})
    sc["weekly_clicks"][week] = int(sc["weekly_clicks"].get(week, 0)) + 1
    sc["last_used_at"] = datetime.now().isoformat(timespec="seconds")

def _open_target(target: str):
    target = target.strip()
    if _is_url(target):
        webbrowser.open(target)
        return

    # Se for script python
    if target.lower().endswith(".py") and os.path.exists(target):
        subprocess.Popen([sys.executable, target], shell=False)
        return

    # Arquivo/atalho/programa
    subprocess.Popen(target, shell=True)

def _extract_icon_image_windows(file_path: str, size: int = 32) -> Optional[Image.Image]:
    if not IS_WINDOWS:
        return None

    fp = file_path
    if not os.path.exists(fp):
        return None

    # tenta extrair o primeiro ícone grande
    hicon_large = wintypes.HICON()
    hicon_small = wintypes.HICON()
    count = ExtractIconExW(fp, 0, ctypes.byref(hicon_large), ctypes.byref(hicon_small), 1)
    hicon = hicon_large if hicon_large else hicon_small
    if count == 0 or not hicon:
        return None

    try:
        iconinfo = ICONINFO()
        if not GetIconInfo(hicon, ctypes.byref(iconinfo)):
            return None

        hbm = iconinfo.hbmColor if iconinfo.hbmColor else iconinfo.hbmMask
        bmp = BITMAP()
        if GetObjectW(hbm, ctypes.sizeof(BITMAP), ctypes.byref(bmp)) == 0:
            return None

        width = int(bmp.bmWidth)
        height = int(abs(bmp.bmHeight)) if bmp.bmHeight else 0
        if width <= 0 or height <= 0:
            return None

        bmi = BITMAPINFO()
        bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = width
        bmi.bmiHeader.biHeight = -height  # top-down
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = BI_RGB

        buf_size = width * height * 4
        buf = (ctypes.c_ubyte * buf_size)()

        hdc = CreateCompatibleDC(0)
        try:
            res = GetDIBits(hdc, hbm, 0, height, ctypes.byref(buf), ctypes.byref(bmi), 0)
            if res == 0:
                return None
        finally:
            DeleteDC(hdc)

        img = Image.frombytes("RGBA", (width, height), bytes(buf), "raw", "BGRA")
        img = img.resize((size, size), Image.LANCZOS)
        return img
    finally:
        # limpa bitmaps associados
        try:
            if 'iconinfo' in locals():
                if iconinfo.hbmColor:
                    DeleteObject(iconinfo.hbmColor)
                if iconinfo.hbmMask:
                    DeleteObject(iconinfo.hbmMask)
        except Exception:
            pass
        try:
            DestroyIcon(hicon)
        except Exception:
            pass

def _default_icon(size: int = 32) -> Image.Image:
    # ícone simples padrão (quadrado com borda)
    img = Image.new("RGBA", (size, size), (255, 255, 255, 0))
    for x in range(size):
        img.putpixel((x, 0), (200, 200, 200, 255))
        img.putpixel((x, size - 1), (200, 200, 200, 255))
    for y in range(size):
        img.putpixel((0, y), (200, 200, 200, 255))
        img.putpixel((size - 1, y), (200, 200, 200, 255))
    # "ponto" central
    cx, cy = size // 2, size // 2
    for dx in range(-3, 4):
        for dy in range(-3, 4):
            if dx * dx + dy * dy <= 10:
                img.putpixel((cx + dx, cy + dy), (120, 160, 255, 255))
    return img


@dataclass
class Theme:
    bg: str
    panel: str
    text: str
    muted: str
    btn: str
    btn_text: str
    btn_hover: str
    accent: str

DARK = Theme(
    bg="#1e1e1e",
    panel="#121212",
    text="#ffffff",
    muted="#cfcfcf",
    btn="#2d2d2d",
    btn_text="#ffffff",
    btn_hover="#3a3a3a",
    accent="#007acc",
)
LIGHT = Theme(
    bg="#f4f4f4",
    panel="#ffffff",
    text="#111111",
    muted="#333333",
    btn="#e9e9e9",
    btn_text="#111111",
    btn_hover="#dcdcdc",
    accent="#007acc",
)


class ShortCutsManagerApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("980x680")

        _ensure_dirs()
        self.data = _load_json(DATA_FILE)

        self.theme = DARK if self.data["settings"].get("theme") == "dark" else LIGHT
        self.icon_cache: Dict[str, ImageTk.PhotoImage] = {}

        self._build_ui()
        self._apply_theme()
        self.refresh()

        # gera relatório automaticamente 1x por semana (quando muda a semana)
        self._auto_weekly_report_if_needed()

    # ---------- UI ----------
    def _build_ui(self):
        self.root.configure(bg=self.theme.bg)

        # top bar
        self.top = tk.Frame(self.root, bg=self.theme.panel)
        self.top.pack(fill="x")

        self.title_lbl = tk.Label(self.top, text=APP_TITLE, font=("Segoe UI", 16, "bold"),
                                  bg=self.theme.panel, fg=self.theme.text)
        self.title_lbl.pack(side="left", padx=14, pady=10)

        # search
        self.search_var = tk.StringVar()
        self.search_entry = tk.Entry(self.top, textvariable=self.search_var, width=30, font=("Segoe UI", 11))
        self.search_entry.pack(side="left", padx=8)
        self.search_entry.bind("<KeyRelease>", lambda e: self.refresh())

        # category filter
        self.category_var = tk.StringVar(value="(todas)")
        self.category_combo = ttk.Combobox(self.top, textvariable=self.category_var, width=18, state="readonly")
        self.category_combo.pack(side="left", padx=8)
        self.category_combo.bind("<<ComboboxSelected>>", lambda e: self.refresh())

        # sort
        self.sort_var = tk.StringVar(value=self.data["settings"].get("sort_mode", DEFAULT_SORT_MODE))
        self.sort_combo = ttk.Combobox(self.top, textvariable=self.sort_var, width=12, state="readonly",
                                       values=["weekly", "total", "alpha"])
        self.sort_combo.pack(side="left", padx=8)
        self.sort_combo.bind("<<ComboboxSelected>>", lambda e: self._set_sort_mode())

        # buttons right
        self.btn_add = tk.Button(self.top, text="Adicionar", command=self.add_shortcut, height=1)
        self.btn_add.pack(side="right", padx=10)

        self.btn_dash = tk.Button(self.top, text="Dashboard", command=self.open_dashboard, height=1)
        self.btn_dash.pack(side="right", padx=10)

        self.btn_report = tk.Button(self.top, text="Relatório", command=self.generate_report, height=1)
        self.btn_report.pack(side="right", padx=10)

        self.btn_theme = tk.Button(self.top, text="Dark/Light", command=self.toggle_theme, height=1)
        self.btn_theme.pack(side="right", padx=10)

        # main canvas (scrollable)
        self.main_wrap = tk.Frame(self.root, bg=self.theme.bg)
        self.main_wrap.pack(fill="both", expand=True)

        self.canvas = tk.Canvas(self.main_wrap, bg=self.theme.bg, highlightthickness=0)
        self.scroll = tk.Scrollbar(self.main_wrap, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.scroll.set)

        self.scroll.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)

        self.grid_frame = tk.Frame(self.canvas, bg=self.theme.bg)
        self.canvas_window = self.canvas.create_window((0, 0), window=self.grid_frame, anchor="nw")

        self.grid_frame.bind("<Configure>", self._on_frame_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)

        # mousewheel scroll (Windows)
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)

    def _apply_theme(self):
        th = self.theme
        self.root.configure(bg=th.bg)
        self.top.configure(bg=th.panel)
        self.title_lbl.configure(bg=th.panel, fg=th.text)

        for btn in [self.btn_add, self.btn_report, self.btn_dash, self.btn_theme]:
            btn.configure(bg=th.accent, fg="#ffffff", activebackground=th.btn_hover, activeforeground="#ffffff",
                          relief="flat", padx=12, pady=6)

        self.main_wrap.configure(bg=th.bg)
        self.canvas.configure(bg=th.bg)
        self.grid_frame.configure(bg=th.bg)

    def _on_frame_configure(self, _event):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        # mantém o frame com a mesma largura do canvas
        self.canvas.itemconfig(self.canvas_window, width=event.width)

    def _on_mousewheel(self, event):
        # Windows: event.delta em múltiplos de 120
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    # ---------- Data helpers ----------
    def _save(self):
        self.data["settings"]["theme"] = "dark" if self.theme == DARK else "light"
        self.data["settings"]["sort_mode"] = self.sort_var.get().strip()
        _save_json_atomic(DATA_FILE, self.data)

    def _set_sort_mode(self):
        self.data["settings"]["sort_mode"] = self.sort_var.get().strip()
        self._save()
        self.refresh()

    def _all_categories(self) -> List[str]:
        cats = set()
        for sc in self.data.get("shortcuts", {}).values():
            c = (sc.get("category") or "").strip()
            if c:
                cats.add(c)
        return sorted(cats, key=str.lower)

    def _filtered_shortcuts(self) -> List[Tuple[str, Dict[str, Any]]]:
        shortcuts = list(self.data.get("shortcuts", {}).items())

        q = self.search_var.get().strip().lower()
        cat = self.category_var.get().strip()

        week = _week_key()
        sort_mode = self.data["settings"].get("sort_mode", DEFAULT_SORT_MODE)

        def match(name: str, sc: Dict[str, Any]) -> bool:
            if cat != "(todas)":
                if (sc.get("category") or "").strip() != cat:
                    return False
            if not q:
                return True
            tags = " ".join(sc.get("tags", [])).lower()
            target = (sc.get("target") or "").lower()
            return (q in name.lower()) or (q in tags) or (q in target)

        shortcuts = [(n, sc) for (n, sc) in shortcuts if match(n, sc)]

        if sort_mode == "weekly":
            shortcuts.sort(key=lambda kv: (_get_weekly_count(kv[1], week), int(kv[1].get("total_clicks", 0))), reverse=True)
        elif sort_mode == "total":
            shortcuts.sort(key=lambda kv: int(kv[1].get("total_clicks", 0)), reverse=True)
        elif sort_mode == "alpha":
            shortcuts.sort(key=lambda kv: kv[0].lower())

        return shortcuts

    # ---------- Actions ----------
    def add_shortcut(self):
        name = simpledialog.askstring("Novo Atalho", "Nome do botão:")
        if not name:
            return
        name = name.strip()
        if not name:
            return
        if name in self.data["shortcuts"]:
            messagebox.showerror("Erro", "Já existe um atalho com esse nome.")
            return

        kind = messagebox.askquestion("Tipo", "Esse atalho é uma URL?\n(Sim = URL / Não = arquivo ou script)")
        if kind == "yes":
            target = simpledialog.askstring("URL", "Cole a URL (https://...):")
            if not target or not _is_url(target):
                messagebox.showerror("Erro", "URL inválida.")
                return
        else:
            target = filedialog.askopenfilename(title="Selecione o arquivo (.exe/.lnk/.py/.bat etc)")
            if not target:
                return
            target = _normalize_path(target)

        category = simpledialog.askstring("Categoria", "Categoria (ex: Trabalho, Dev, Pessoal) — opcional:")
        category = (category or "").strip()

        tags_raw = simpledialog.askstring("Tags", "Tags separadas por vírgula (ex: chrome, web, docs) — opcional:")
        tags = []
        if tags_raw:
            tags = [t.strip() for t in tags_raw.split(",") if t.strip()]

        self.data["shortcuts"][name] = {
            "target": target,
            "category": category,
            "tags": tags,
            "total_clicks": 0,
            "weekly_clicks": {},
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "last_used_at": None
        }
        self._save()
        self.refresh()

    def edit_shortcut(self, name: str):
        sc = self.data["shortcuts"].get(name)
        if not sc:
            return

        new_name = simpledialog.askstring("Editar", "Nome do botão:", initialvalue=name)
        if not new_name:
            return
        new_name = new_name.strip()
        if not new_name:
            return
        if new_name != name and new_name in self.data["shortcuts"]:
            messagebox.showerror("Erro", "Já existe um atalho com esse nome.")
            return

        target = sc.get("target", "")
        target_new = simpledialog.askstring("Editar", "Target (URL ou caminho do arquivo):", initialvalue=target)
        if not target_new:
            return
        target_new = target_new.strip()
        if not (_is_url(target_new) or os.path.exists(target_new)):
            # aceita caminhos que podem existir depois, mas avisa
            if messagebox.askyesno("Atenção", "O target não existe agora.\nQuer salvar mesmo assim?") is False:
                return

        category_new = simpledialog.askstring("Editar", "Categoria:", initialvalue=sc.get("category", "") or "")
        category_new = (category_new or "").strip()

        tags_init = ", ".join(sc.get("tags", []))
        tags_raw = simpledialog.askstring("Editar", "Tags (vírgula):", initialvalue=tags_init)
        tags_new = []
        if tags_raw:
            tags_new = [t.strip() for t in tags_raw.split(",") if t.strip()]

        if new_name != name:
            self.data["shortcuts"].pop(name, None)
        self.data["shortcuts"][new_name] = {
            **sc,
            "target": target_new,
            "category": category_new,
            "tags": tags_new
        }

        self._save()
        self.refresh()

    def delete_shortcut(self, name: str):
        if name not in self.data["shortcuts"]:
            return
        if messagebox.askyesno("Confirmar", f"Excluir atalho '{name}'?"):
            self.data["shortcuts"].pop(name, None)
            self._save()
            self.refresh()

    def run_shortcut(self, name: str):
        sc = self.data["shortcuts"].get(name)
        if not sc:
            return

        target = sc.get("target", "")
        try:
            _open_target(target)
            _increment_usage(sc, _week_key())
            self._save()
            self.refresh()
        except Exception as e:
            messagebox.showerror("Erro ao executar", str(e))

    def toggle_theme(self):
        self.theme = LIGHT if self.theme == DARK else DARK
        self._apply_theme()
        self._save()
        self.refresh()

    # ---------- Rendering ----------
    def refresh(self):
        # categorias no combo
        cats = ["(todas)"] + self._all_categories()
        self.category_combo.configure(values=cats)
        if self.category_var.get() not in cats:
            self.category_var.set("(todas)")

        # limpa grid
        for w in self.grid_frame.winfo_children():
            w.destroy()

        th = self.theme
        week = _week_key()
        items = self._filtered_shortcuts()

        # render cards/botões
        row = 0
        col = 0

        for name, sc in items:
            card = tk.Frame(self.grid_frame, bg=th.btn, relief="flat", bd=0, highlightthickness=1,
                            highlightbackground=th.panel)
            card.grid(row=row, column=col, padx=10, pady=10, sticky="nsew")

            # icon
            icon = self._get_icon_for_target(sc.get("target", ""), size=32)
            icon_lbl = tk.Label(card, image=icon, bg=th.btn)
            icon_lbl.image = icon
            icon_lbl.grid(row=0, column=0, padx=10, pady=10, sticky="w")

            # text
            title = tk.Label(card, text=name, font=("Segoe UI", 12, "bold"), bg=th.btn, fg=th.btn_text)
            title.grid(row=0, column=1, padx=6, pady=8, sticky="w")

            cat = (sc.get("category") or "").strip()
            tags = ", ".join(sc.get("tags", []))
            meta_txt = " | ".join([t for t in [cat if cat else None, tags if tags else None] if t])
            if not meta_txt:
                meta_txt = "—"

            meta = tk.Label(card, text=meta_txt, font=("Segoe UI", 9), bg=th.btn, fg=th.muted)
            meta.grid(row=1, column=1, padx=6, pady=(0, 8), sticky="w")

            # stats
            total = int(sc.get("total_clicks", 0))
            wcount = _get_weekly_count(sc, week)
            stats = tk.Label(card, text=f"Semana: {wcount} | Total: {total}", font=("Segoe UI", 9),
                             bg=th.btn, fg=th.muted)
            stats.grid(row=2, column=1, padx=6, pady=(0, 10), sticky="w")

            # actions
            btn_run = tk.Button(card, text="Abrir", command=lambda n=name: self.run_shortcut(n),
                                bg=th.accent, fg="#ffffff", relief="flat", padx=10, pady=6)
            btn_run.grid(row=0, column=2, padx=10, pady=10, sticky="e")

            btn_edit = tk.Button(card, text="Editar", command=lambda n=name: self.edit_shortcut(n),
                                 bg=th.btn_hover, fg=th.btn_text, relief="flat", padx=10, pady=6)
            btn_edit.grid(row=1, column=2, padx=10, pady=0, sticky="e")

            btn_del = tk.Button(card, text="Excluir", command=lambda n=name: self.delete_shortcut(n),
                                bg=th.btn_hover, fg=th.btn_text, relief="flat", padx=10, pady=6)
            btn_del.grid(row=2, column=2, padx=10, pady=(0, 10), sticky="e")

            # hover effect
            def on_enter(_e, c=card):
                c.configure(bg=th.btn_hover)
                for child in c.winfo_children():
                    if isinstance(child, tk.Label):
                        child.configure(bg=th.btn_hover)
            def on_leave(_e, c=card):
                c.configure(bg=th.btn)
                for child in c.winfo_children():
                    if isinstance(child, tk.Label):
                        child.configure(bg=th.btn)

            card.bind("<Enter>", on_enter)
            card.bind("<Leave>", on_leave)
            for child in card.winfo_children():
                child.bind("<Enter>", on_enter)
                child.bind("<Leave>", on_leave)

            col += 1
            if col >= GRID_COLS:
                col = 0
                row += 1

        # garante expansão das colunas
        for c in range(GRID_COLS):
            self.grid_frame.grid_columnconfigure(c, weight=1)

        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _get_icon_for_target(self, target: str, size: int = 32) -> ImageTk.PhotoImage:
        key = f"{target}|{size}|{self.theme.bg}"
        if key in self.icon_cache:
            return self.icon_cache[key]

        img = None
        if _is_url(target):
            img = _default_icon(size=size)
        else:
            # tenta ícone do arquivo (exe/lnk) ou usa default
            if IS_WINDOWS and os.path.exists(target) and (target.lower().endswith(".exe") or target.lower().endswith(".lnk")):
                img = _extract_icon_image_windows(target, size=size)
            if img is None:
                img = _default_icon(size=size)

        photo = ImageTk.PhotoImage(img)
        self.icon_cache[key] = photo
        return photo

    # ---------- Reports & Dashboard ----------
    def generate_report(self):
        week = _week_key()

        items = []
        for name, sc in self.data.get("shortcuts", {}).items():
            items.append((name, _get_weekly_count(sc, week), int(sc.get("total_clicks", 0))))

        items.sort(key=lambda x: x[1], reverse=True)  # por semana

        top = items[:5]
        bottom = items[-5:] if len(items) >= 5 else items

        report_lines = []
        report_lines.append(f"Relatório da semana {week}")
        report_lines.append("")
        report_lines.append("Mais utilizados (semana):")
        for n, w, t in top:
            report_lines.append(f"- {n}: {w} (total {t})")
        report_lines.append("")
        report_lines.append("Menos utilizados (semana):")
        for n, w, t in bottom:
            report_lines.append(f"- {n}: {w} (total {t})")

        report_text = "\n".join(report_lines)
        path = os.path.join(REPORTS_DIR, f"report_{week}.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(report_text)

        self.data["settings"]["last_report_week"] = week
        self._save()

        messagebox.showinfo("Relatório Gerado", report_text)

    def _auto_weekly_report_if_needed(self):
        week = _week_key()
        last = self.data["settings"].get("last_report_week")
        if last != week:
            # gera automaticamente na primeira abertura da semana
            try:
                self.generate_report()
            except Exception:
                pass

    def open_dashboard(self):
        week = _week_key()

        # agrega dados
        names = []
        weekly = []
        total = []
        for name, sc in self.data.get("shortcuts", {}).items():
            names.append(name)
            weekly.append(_get_weekly_count(sc, week))
            total.append(int(sc.get("total_clicks", 0)))

        # ordena por weekly desc para leitura
        order = sorted(range(len(names)), key=lambda i: weekly[i], reverse=True)
        names = [names[i] for i in order]
        weekly = [weekly[i] for i in order]
        total = [total[i] for i in order]

        win = tk.Toplevel(self.root)
        win.title(f"Dashboard - {week}")
        win.geometry("1000x700")
        win.configure(bg=self.theme.bg)

        fig = Figure(figsize=(9, 6), dpi=100)
        ax1 = fig.add_subplot(111)
        ax1.set_title(f"Cliques na semana ({week})")
        ax1.set_xlabel("Atalhos")
        ax1.set_ylabel("Cliques")

        # evita lotar: se tiver muitos atalhos, mostra top 20
        max_show = 20
        names_show = names[:max_show]
        weekly_show = weekly[:max_show]

        ax1.bar(range(len(names_show)), weekly_show)
        ax1.set_xticks(range(len(names_show)))
        ax1.set_xticklabels(names_show, rotation=45, ha="right")

        canvas = FigureCanvasTkAgg(fig, master=win)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="both", expand=True, padx=10, pady=10)

        # tabela simples abaixo (top 10)
        frame = tk.Frame(win, bg=self.theme.bg)
        frame.pack(fill="x", padx=10, pady=(0, 10))

        header = tk.Label(frame, text="Top 10 (semana / total)", bg=self.theme.bg, fg=self.theme.text,
                          font=("Segoe UI", 11, "bold"))
        header.pack(anchor="w")

        for i in range(min(10, len(names))):
            line = tk.Label(frame,
                            text=f"{i+1:02d}. {names[i]} — semana: {weekly[i]} | total: {total[i]}",
                            bg=self.theme.bg, fg=self.theme.muted, font=("Segoe UI", 10))
            line.pack(anchor="w")


def main():
    root = tk.Tk()
    app = ShortCutsManagerApp(root)
    root.mainloop()

if __name__ == "__main__":
    main()