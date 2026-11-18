"""Tkinter desktop interface: login screen + trading dashboard."""

from __future__ import annotations

import queue
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

from . import __app_name__, __version__
from . import theme as T
from .bot import BotConfig, GridBot
from .mt5_client import MT5Client, MT5Error
from .settings import load_settings, resource_path, save_settings
from .simulator import SimulatedMT5

SYMBOLS = ["EURUSD", "GBPUSD", "AUDUSD", "USDJPY"]


class App(tk.Tk):
    def __init__(self, demo: bool = False) -> None:
        super().__init__()
        self.title(f"{__app_name__} v{__version__}")
        self.geometry("1200x820")
        self.minsize(1080, 760)
        T.apply_theme(self)
        self._set_icon()

        self.client: MT5Client | None = None
        self.demo_mode = tk.BooleanVar(value=demo)
        self.bots: dict[int, GridBot] = {}
        self.events: "queue.Queue[tuple]" = queue.Queue()
        self.settings = load_settings()
        self._session = 0  # bumps on every login so old refresh loops stop

        self.container = ttk.Frame(self)
        self.container.pack(fill="both", expand=True)
        self.show_login()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(150, self._drain_events)

    # ----------------------------------------------------------------- utility
    def _set_icon(self) -> None:
        try:
            self._logo_img = tk.PhotoImage(file=resource_path("assets/logo.png"))
            self.iconphoto(True, self._logo_img)
            self._logo_small = self._logo_img.subsample(2, 2)
        except tk.TclError:
            self._logo_img = self._logo_small = None
        try:
            self.iconbitmap(resource_path("assets/logo.ico"))
        except tk.TclError:
            pass

    def _clear(self) -> None:
        for child in self.container.winfo_children():
            child.destroy()

    @staticmethod
    def _card(parent, **pack) -> ttk.Frame:
        frame = ttk.Frame(parent, style="Card.TFrame", padding=16)
        if pack:
            frame.pack(**pack)
        return frame

    # =================================================================== LOGIN
    def show_login(self) -> None:
        self._clear()
        wrap = ttk.Frame(self.container)
        wrap.place(relx=0.5, rely=0.5, anchor="center")

        if self._logo_img is not None:
            ttk.Label(wrap, image=self._logo_img).pack(pady=(0, 6))
        ttk.Label(wrap, text=__app_name__, style="Title.TLabel").pack()
        ttk.Label(wrap, text="MetaTrader 5 Forex Grid Trading Bot",
                  style="Muted.TLabel").pack(pady=(0, 14))

        card = self._card(wrap, fill="x")
        card.columnconfigure(0, weight=1)
        self.login_var = tk.StringVar(value=self.settings.get("login", ""))
        self.password_var = tk.StringVar()
        self.server_var = tk.StringVar(value=self.settings.get("server", ""))
        self.path_var = tk.StringVar(value=self.settings.get("path", ""))
        self.remember_var = tk.BooleanVar(value=bool(self.settings))

        rows = [("Login (account number)", self.login_var, ""),
                ("Password", self.password_var, "•"),
                ("Server", self.server_var, ""),
                ("Terminal path (optional)", self.path_var, "")]
        r = 0
        for label, var, show in rows:
            ttk.Label(card, text=label, style="CardMuted.TLabel").grid(row=r, column=0, sticky="w")
            entry = ttk.Entry(card, textvariable=var, show=show, width=40)
            entry.grid(row=r + 1, column=0, sticky="ew", pady=(2, 10))
            if r == 0:
                self._first_entry = entry
            r += 2

        ttk.Checkbutton(card, text="Demo mode (built-in simulator, no MT5 needed)",
                        variable=self.demo_mode, style="Card.TCheckbutton",
                        command=self._toggle_demo).grid(row=r, column=0, sticky="w")
        ttk.Checkbutton(card, text="Remember login & server (password is never saved)",
                        variable=self.remember_var, style="Card.TCheckbutton").grid(row=r + 1, column=0, sticky="w", pady=(2, 12))
        self.login_btn = ttk.Button(card, text="Connect", style="Accent.TButton", command=self.do_login)
        self.login_btn.grid(row=r + 2, column=0, sticky="ew")
        self.login_status = ttk.Label(card, text="", style="CardMuted.TLabel", wraplength=330)
        self.login_status.grid(row=r + 3, column=0, sticky="w", pady=(8, 0))

        ttk.Label(wrap, text="Advanced Python Certification - Final Project  |  SLIPD Academy",
                  style="Muted.TLabel").pack(pady=(12, 0))
        self.bind("<Return>", lambda _e: self.do_login())
        self._toggle_demo()
        self._first_entry.focus_set()

    def _toggle_demo(self) -> None:
        if self.demo_mode.get():
            self.login_status.config(text="Demo mode: any login and password will work.",
                                     foreground=T.MUTED)
            if not self.login_var.get():
                self.login_var.set("12345678")
            if not self.server_var.get():
                self.server_var.set("SNova-Demo")
        else:
            self.login_status.config(
                text="Open MetaTrader 5 and turn on 'Algo Trading'. Leave login, password and "
                     "server empty to use the account already logged in there.",
                foreground=T.MUTED)

    def do_login(self) -> None:
        if self.client is not None and self.client.connected:
            return
        login, password = self.login_var.get().strip(), self.password_var.get()
        server, path = self.server_var.get().strip(), self.path_var.get().strip()
        demo = self.demo_mode.get()
        if demo and not password:
            password = "demo"
        if demo and not login:
            login = "12345678"
        if login and not login.isdigit():
            self.login_status.config(text="Login must be your account number (digits only).",
                                     foreground=T.DANGER)
            return
        if login and (not password or not server):
            self.login_status.config(text="Enter the password and server, or leave all three "
                                          "empty to use the account open in MetaTrader 5.",
                                     foreground=T.DANGER)
            return
        self.login_btn.state(["disabled"])
        self.login_status.config(text="Connecting...", foreground=T.MUTED)
        client = MT5Client(SimulatedMT5() if self.demo_mode.get() else None)

        def worker():  # keep the window responsive while the terminal starts
            try:
                account = client.connect(int(login) if login else None, password, server, path or None)
                self.after(0, lambda: self._login_ok(client, account, login, server, path))
            except (MT5Error, ValueError) as exc:
                msg = str(exc)
                self.after(0, lambda: self._login_failed(msg))

        threading.Thread(target=worker, daemon=True).start()

    def _login_failed(self, message: str) -> None:
        self.login_btn.state(["!disabled"])
        self.login_status.config(text=message, foreground=T.DANGER)

    def _login_ok(self, client, account, login, server, path) -> None:
        self.client = client
        if self.remember_var.get():
            save_settings({"login": login, "server": server, "path": path})
        else:
            save_settings({})
        self.unbind("<Return>")
        self.show_dashboard(account)

    # =============================================================== DASHBOARD
    def show_dashboard(self, account: dict) -> None:
        self._clear()
        root = ttk.Frame(self.container, padding=16)
        root.pack(fill="both", expand=True)

        # header
        header = ttk.Frame(root)
        header.pack(fill="x")
        if self._logo_small is not None:
            ttk.Label(header, image=self._logo_small).pack(side="left", padx=(0, 10))
        titles = ttk.Frame(header)
        titles.pack(side="left")
        ttk.Label(titles, text=__app_name__, style="Title.TLabel").pack(anchor="w")
        kinds = {0: "DEMO account", 1: "CONTEST account", 2: "REAL account"}
        mode = ("Simulator (Demo mode)" if self.demo_mode.get()
                else f"MetaTrader 5 · {kinds.get(account.get('trade_mode'), 'account')}")
        ttk.Label(titles, style="Muted.TLabel",
                  text=f"{account.get('name', '')}  #{account.get('login')}  |  "
                       f"{account.get('server')}  |  1:{account.get('leverage')}  |  {mode}"
                  ).pack(anchor="w")
        ttk.Button(header, text="Disconnect", style="Ghost.TButton",
                   command=self.disconnect).pack(side="right")

        # account stat cards
        stats = ttk.Frame(root)
        stats.pack(fill="x", pady=14)
        self.stat_vars = {}
        self.stat_labels = {}
        for i, (key, label) in enumerate([("balance", "Balance"), ("equity", "Equity"),
                                          ("margin", "Margin"), ("margin_free", "Free margin"),
                                          ("profit", "Floating P/L")]):
            stats.columnconfigure(i, weight=1, uniform="stats")
            card = self._card(stats)
            card.grid(row=0, column=i, sticky="ew", padx=(0 if i == 0 else 10, 0))
            ttk.Label(card, text=label.upper(), style="CardMuted.TLabel").pack(anchor="w")
            var = tk.StringVar(value="-")
            lbl = ttk.Label(card, textvariable=var, style="Stat.TLabel")
            lbl.pack(anchor="w", pady=(4, 0))
            self.stat_vars[key], self.stat_labels[key] = var, lbl
        self.currency = account.get("currency", "USD")

        # activity log at the bottom (packed first so it always stays visible)
        self._build_log(root)

        # body: form (left) + bots table (right)
        body = ttk.Frame(root)
        body.pack(fill="both", expand=True)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)
        self._build_form(body)
        self._build_bots_table(body)

        self.log(f"Connected to {account.get('server')} as #{account.get('login')}.", "success")
        if not self.demo_mode.get() and account.get("trade_mode") == 2:
            self.log("This is a REAL money account. Test on a demo account first!", "warning")
        if not self.demo_mode.get() and not self.client.algo_trading_enabled():
            self.log("'Algo Trading' is OFF in MetaTrader 5. Turn it on or orders will fail.",
                     "warning")
        self._session += 1
        self._refresh_account(self._session)
        self._refresh_bots(self._session)

    def _build_form(self, parent) -> None:
        card = self._card(parent)
        card.grid(row=0, column=0, sticky="nsw", padx=(0, 12))
        ttk.Label(card, text="New grid bot", style="CardTitle.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))

        self.f_symbol = tk.StringVar(value="EURUSD")
        self.f_volume = tk.StringVar(value="0.01")
        self.f_step = tk.StringVar(value="1")
        self.f_levels = tk.StringVar(value="5")
        self.f_tp = tk.StringVar(value="0.2")
        self.f_sl = tk.StringVar(value="0")
        self.f_cycles = tk.StringVar(value="1")

        ttk.Label(card, text="Symbol", style="CardMuted.TLabel").grid(row=1, column=0,
                                                                     columnspan=2, sticky="w")
        ttk.Combobox(card, textvariable=self.f_symbol, values=SYMBOLS, width=26).grid(
            row=2, column=0, columnspan=2, sticky="ew", pady=(2, 10))

        pairs = [(("Lot size", self.f_volume), ("Grid step (pips)", self.f_step)),
                 (("Levels each side", self.f_levels), ("Cycles", self.f_cycles)),
                 (("Take profit %", self.f_tp), ("Stop loss % (0 = off)", self.f_sl))]
        for i, pair in enumerate(pairs):
            for col, (label, var) in enumerate(pair):
                pad = (0, 6) if col == 0 else (6, 0)
                ttk.Label(card, text=label, style="CardMuted.TLabel").grid(
                    row=3 + i * 2, column=col, sticky="w", padx=pad)
                ttk.Entry(card, textvariable=var, width=11).grid(
                    row=4 + i * 2, column=col, sticky="ew", padx=pad, pady=(2, 10))
        ttk.Label(card, text="Take profit / stop loss are measured as\n"
                             "profit of open trades ÷ their margin × 100.",
                  style="CardMuted.TLabel").grid(row=10, column=0, columnspan=2, sticky="w")

        ttk.Button(card, text="▶  Start bot", style="Accent.TButton",
                   command=self.start_bot).grid(row=11, column=0, columnspan=2, sticky="ew",
                                                pady=(12, 0))

    def _build_bots_table(self, parent) -> None:
        card = self._card(parent)
        card.grid(row=0, column=1, sticky="nsew")
        top = ttk.Frame(card, style="Card.TFrame")
        top.pack(fill="x", pady=(0, 10))
        ttk.Label(top, text="Running bots", style="CardTitle.TLabel").pack(side="left")
        ttk.Button(top, text="Stop all", style="Danger.TButton",
                   command=self.stop_all).pack(side="right")
        ttk.Button(top, text="Stop selected", style="Ghost.TButton",
                   command=self.stop_selected).pack(side="right", padx=8)
        ttk.Button(top, text="Remove finished", style="Ghost.TButton",
                   command=self.remove_finished).pack(side="right")

        cols = ("bot", "symbol", "status", "cycle", "lot", "step", "positions", "pending",
                "floating", "realized")
        heads = ("Bot", "Symbol", "Status", "Cycle", "Lot", "Step", "Open", "Pending",
                 "Floating", "Realized")
        widths = (60, 80, 90, 60, 55, 55, 55, 65, 85, 85)
        frame = ttk.Frame(card, style="Card.TFrame")
        frame.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(frame, columns=cols, show="headings", selectmode="extended")
        for c, h, w in zip(cols, heads, widths):
            self.tree.heading(c, text=h)
            self.tree.column(c, width=w, anchor="center", stretch=True)
        scroll = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.tree.tag_configure("profit", foreground=T.ACCENT)
        self.tree.tag_configure("loss", foreground=T.DANGER)
        self.tree.tag_configure("error", foreground=T.WARNING)

    def _build_log(self, parent) -> None:
        card = self._card(parent, side="bottom", fill="x", pady=(12, 0))
        top = ttk.Frame(card, style="Card.TFrame")
        top.pack(fill="x")
        ttk.Label(top, text="Activity log", style="CardTitle.TLabel").pack(side="left")
        ttk.Button(top, text="Clear", style="Ghost.TButton",
                   command=lambda: self.log_text.delete("1.0", "end")).pack(side="right")
        self.log_text = tk.Text(card, height=7, bg=T.FIELD, fg=T.TEXT, insertbackground=T.TEXT,
                                relief="flat", font=T.FONT_MONO, wrap="word", padx=8, pady=6)
        self.log_text.pack(fill="x", pady=(8, 0))
        for level, color in (("info", T.TEXT), ("success", T.ACCENT), ("warning", T.WARNING),
                             ("error", T.DANGER), ("time", T.MUTED)):
            self.log_text.tag_configure(level, foreground=color)

    # ----------------------------------------------------------------- actions
    def _read_form(self) -> BotConfig:
        try:
            cfg = BotConfig(
                symbol=self.f_symbol.get().strip().upper(),
                volume=float(self.f_volume.get()),
                step_pips=float(self.f_step.get()),
                levels=int(self.f_levels.get()),
                take_profit_pct=float(self.f_tp.get()),
                stop_loss_pct=float(self.f_sl.get() or 0),
                cycles=int(self.f_cycles.get()),
            )
        except ValueError:
            raise ValueError("Please enter valid numbers in every field.") from None
        cfg.validate()
        return cfg

    def start_bot(self) -> None:
        try:
            cfg = self._read_form()
        except ValueError as exc:
            messagebox.showerror("Invalid settings", str(exc), parent=self)
            return
        bot = GridBot(self.client, cfg, on_event=self._on_bot_event)
        self.bots[bot.id] = bot
        self.tree.insert("", "end", iid=str(bot.id), values=self._row(bot))
        bot.start()

    def _selected_bots(self) -> list:
        return [self.bots[int(i)] for i in self.tree.selection() if int(i) in self.bots]

    def stop_selected(self) -> None:
        bots = self._selected_bots()
        if not bots:
            messagebox.showinfo("Stop bot", "Select a bot in the table first.", parent=self)
            return
        for bot in bots:
            bot.stop()

    def stop_all(self) -> None:
        running = [b for b in self.bots.values() if b.running]
        if running and messagebox.askyesno(
                "Stop all", f"Stop {len(running)} running bot(s)?\n"
                            "Their open trades will be closed and pending orders deleted.",
                parent=self):
            for bot in running:
                bot.stop()

    def remove_finished(self) -> None:
        for bot_id, bot in list(self.bots.items()):
            if not bot.running:
                del self.bots[bot_id]
                if self.tree.exists(str(bot_id)):
                    self.tree.delete(str(bot_id))

    def disconnect(self) -> None:
        if any(b.running for b in self.bots.values()):
            if not messagebox.askyesno("Disconnect", "Bots are still running. Stop them all and "
                                                     "disconnect?", parent=self):
                return
        self._shutdown_bots()
        if self.client:
            self.client.shutdown()
        self.client = None
        self._session += 1
        self.bots.clear()
        self.show_login()

    def _shutdown_bots(self) -> None:
        for bot in self.bots.values():
            bot.stop()
        deadline = time.time() + 8
        for bot in self.bots.values():
            bot.join(max(0.1, deadline - time.time()))

    def on_close(self) -> None:
        if any(b.running for b in self.bots.values()):
            if not messagebox.askyesno("Exit", "Bots are still running. Stop them all and exit?",
                                       parent=self):
                return
        self._shutdown_bots()
        if self.client:
            self.client.shutdown()
        self.destroy()

    # ------------------------------------------------------- events & refresh
    def _on_bot_event(self, bot: GridBot, message: str, level: str) -> None:
        # Called from bot threads: hand over to the Tk thread through a queue.
        self.events.put((bot.id, message, level))

    def _drain_events(self) -> None:
        try:
            while True:
                bot_id, message, level = self.events.get_nowait()
                bot = self.bots.get(bot_id)
                if bot is not None and hasattr(self, "tree") and self.tree.winfo_exists() \
                        and self.tree.exists(str(bot_id)):
                    self._update_row(bot)
                if message and level != "debug" and hasattr(self, "log_text") \
                        and self.log_text.winfo_exists():
                    self.log(f"[Bot {bot_id}] {message}", level)
        except queue.Empty:
            pass
        self.after(150, self._drain_events)

    def log(self, message: str, level: str = "info") -> None:
        stamp = time.strftime("%H:%M:%S")
        self.log_text.insert("end", f"{stamp}  ", "time")
        self.log_text.insert("end", message + "\n", level if level in
                             ("info", "success", "warning", "error") else "info")
        self.log_text.see("end")
        lines = int(self.log_text.index("end-1c").split(".")[0])
        if lines > 600:
            self.log_text.delete("1.0", f"{lines - 500}.0")

    @staticmethod
    def _row(bot: GridBot) -> tuple:
        c = bot.config
        return (bot.name, c.symbol, bot.status, f"{bot.cycle}/{c.cycles}", c.volume,
                f"{c.step_pips:g}", bot.open_positions, bot.pending_orders,
                f"{bot.floating:+.2f}", f"{bot.realized:+.2f}")

    def _update_row(self, bot: GridBot) -> None:
        if bot.status == GridBot.ERROR:
            tag = "error"
        elif bot.floating + bot.realized > 0:
            tag = "profit"
        elif bot.floating + bot.realized < 0:
            tag = "loss"
        else:
            tag = ""
        self.tree.item(str(bot.id), values=self._row(bot), tags=(tag,) if tag else ())

    def _refresh_bots(self, session: int) -> None:
        if session != self._session or not self.tree.winfo_exists():
            return
        for bot in self.bots.values():
            if self.tree.exists(str(bot.id)):
                self._update_row(bot)
        self.after(1000, self._refresh_bots, session)

    def _refresh_account(self, session: int) -> None:
        if session != self._session or self.client is None or not self.client.connected:
            return
        try:
            info = self.client.account_info()
        except Exception:  # noqa: BLE001 - keep refreshing even after a hiccup
            info = None
        if info and self.stat_labels["balance"].winfo_exists():
            for key, var in self.stat_vars.items():
                var.set(f"{info.get(key, 0):,.2f} {self.currency}")
            p = info.get("profit", 0)
            style = "StatGreen.TLabel" if p > 0 else "StatRed.TLabel" if p < 0 else "Stat.TLabel"
            self.stat_labels["profit"].configure(style=style)
        self.after(1000, self._refresh_account, session)
