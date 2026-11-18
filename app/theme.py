"""Modern dark theme for ttk widgets."""

from tkinter import ttk

BG = "#0f172a"        # window background
PANEL = "#1e293b"     # cards / panels
FIELD = "#0b1222"     # entry background
BORDER = "#334155"
TEXT = "#e2e8f0"
MUTED = "#94a3b8"
ACCENT = "#22c55e"    # green
ACCENT_DARK = "#16a34a"
DANGER = "#ef4444"
DANGER_DARK = "#dc2626"
WARNING = "#f59e0b"
INFO = "#38bdf8"

FONT = ("Segoe UI", 10)
FONT_BOLD = ("Segoe UI", 10, "bold")
FONT_TITLE = ("Segoe UI", 18, "bold")
FONT_BIG = ("Segoe UI", 15, "bold")
FONT_SMALL = ("Segoe UI", 9)
FONT_MONO = ("Consolas", 9)


def apply_theme(root) -> ttk.Style:
    root.configure(bg=BG)
    style = ttk.Style(root)
    style.theme_use("clam")

    style.configure(".", background=BG, foreground=TEXT, font=FONT, bordercolor=BORDER)
    style.configure("TFrame", background=BG)
    style.configure("Card.TFrame", background=PANEL)
    style.configure("TLabel", background=BG, foreground=TEXT)
    style.configure("Card.TLabel", background=PANEL, foreground=TEXT)
    style.configure("Muted.TLabel", background=BG, foreground=MUTED, font=FONT_SMALL)
    style.configure("CardMuted.TLabel", background=PANEL, foreground=MUTED, font=FONT_SMALL)
    style.configure("Title.TLabel", background=BG, foreground=TEXT, font=FONT_TITLE)
    style.configure("CardTitle.TLabel", background=PANEL, foreground=TEXT, font=FONT_BOLD)
    style.configure("Stat.TLabel", background=PANEL, foreground=TEXT, font=FONT_BIG)
    style.configure("StatGreen.TLabel", background=PANEL, foreground=ACCENT, font=FONT_BIG)
    style.configure("StatRed.TLabel", background=PANEL, foreground=DANGER, font=FONT_BIG)

    style.configure("TEntry", fieldbackground=FIELD, foreground=TEXT, insertcolor=TEXT,
                    bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER, padding=6)
    style.map("TEntry", bordercolor=[("focus", ACCENT)], lightcolor=[("focus", ACCENT)])
    style.configure("TSpinbox", fieldbackground=FIELD, foreground=TEXT, arrowcolor=TEXT,
                    background=PANEL, bordercolor=BORDER, padding=4)
    style.configure("TCombobox", fieldbackground=FIELD, foreground=TEXT, arrowcolor=TEXT,
                    background=PANEL, bordercolor=BORDER, padding=4)
    style.map("TCombobox", fieldbackground=[("readonly", FIELD)],
              foreground=[("readonly", TEXT)], selectbackground=[("readonly", FIELD)])
    root.option_add("*TCombobox*Listbox.background", FIELD)
    root.option_add("*TCombobox*Listbox.foreground", TEXT)
    root.option_add("*TCombobox*Listbox.selectBackground", ACCENT_DARK)

    style.configure("Card.TCheckbutton", background=PANEL, foreground=MUTED,
                    indicatorbackground=FIELD, indicatorforeground=ACCENT, indicatorcolor=FIELD,
                    focuscolor=PANEL, bordercolor=BORDER)
    style.map("Card.TCheckbutton", background=[("active", PANEL)],
              foreground=[("active", TEXT)],
              indicatorcolor=[("selected", ACCENT), ("!selected", FIELD)])

    for name, color, dark in (("Accent", ACCENT, ACCENT_DARK), ("Danger", DANGER, DANGER_DARK)):
        style.configure(f"{name}.TButton", background=color, foreground="white", font=FONT_BOLD,
                        borderwidth=0, padding=(14, 8), focuscolor=color)
        style.map(f"{name}.TButton", background=[("disabled", BORDER), ("active", dark)],
                  foreground=[("disabled", MUTED)])
    style.configure("Ghost.TButton", background=PANEL, foreground=TEXT, borderwidth=1,
                    bordercolor=BORDER, padding=(12, 7), focuscolor=PANEL)
    style.map("Ghost.TButton", background=[("active", BORDER)])

    style.configure("Treeview", background=FIELD, fieldbackground=FIELD, foreground=TEXT,
                    rowheight=26, bordercolor=BORDER, borderwidth=0)
    style.map("Treeview", background=[("selected", "#14532d")], foreground=[("selected", "white")])
    style.configure("Treeview.Heading", background=PANEL, foreground=MUTED, font=FONT_BOLD,
                    borderwidth=0, padding=6)
    style.map("Treeview.Heading", background=[("active", BORDER)])
    style.configure("Vertical.TScrollbar", background=PANEL, troughcolor=BG, arrowcolor=MUTED,
                    bordercolor=BG)
    return style
