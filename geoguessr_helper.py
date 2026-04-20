#!/usr/bin/env python3
"""
https://github.com/g70xl0l/aiguessr-cli
"""

import sys
import argparse
import io
import base64
import json
import time
import threading
import ctypes
import getpass
import socket

# ─── Dependency guard ────────────────────────────────────────────────────────

def _require(pkg, pip_name=None):
    import importlib
    try:
        return importlib.import_module(pkg)
    except ImportError:
        name = pip_name or pkg
        print(f"[ERROR] Missing dependency: {name}")
        print(f"        Install with: pip install {name}")
        sys.exit(1)

requests_mod = None  # lazy

# ═══════════════════════════════════════════════════════════════════════════════
#  SHARED: API LOGIC
# ═══════════════════════════════════════════════════════════════════════════════

MODEL_NAME = "gemini-flash-latest"
GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    f"{MODEL_NAME}:generateContent"
)

PROMPT = (
    "Ты — грандмастер игры GeoGuessr. Внимательно изучи этот скриншот со Street View. "
    "Твоя задача — определить страну, а также максимально точно угадать город, поселок или регион. "
    "Ищи меты GeoGuessr: названия на вывесках, разметку на дороге, столбы, знаки (язык), "
    "сторону движения, растительность, цвет почвы, особенности архитектуры, "
    "или даже багажник Google-мобиля. "
    "Отвечай СТРОГО в этом формате (без лишнего текста до или после):\n"
    "СТРАНА: [ответ]\n"
    "РЕГИОН: [ответ]\n"
    "УВЕРЕННОСТЬ: [число от 1 до 100]\n"
    "УЛИКИ: [краткое перечисление 2-3 главных улик через точку с запятой]"
)


def screenshot_to_b64(bbox=None):
    """Grab screen (or bbox) and return base64 PNG string."""
    PIL = _require("PIL", "Pillow")
    from PIL import ImageGrab
    img = ImageGrab.grab(bbox=bbox)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def ask_gemini(api_key: str, img_b64: str) -> dict:
    """Call Gemini API. Returns parsed dict or raises an error."""
    global requests_mod
    if requests_mod is None:
        requests_mod = _require("requests")

    payload = {
        "contents": [{
            "parts": [
                {"text": PROMPT},
                {"inline_data": {"mime_type": "image/png", "data": img_b64}},
            ],
        }]
    }
    resp = requests_mod.post(
        GEMINI_URL,
        headers={
            "x-goog-api-key": api_key,
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=30
    )
    if not resp.ok:
        try:
            err_json = resp.json()
        except Exception:
            err_json = {"error": {"message": resp.text.strip() or f"HTTP {resp.status_code}"}}
        err_msg = err_json.get("error", {}).get("message", f"HTTP {resp.status_code}")
        raise RuntimeError(f"Gemini API error {resp.status_code}: {err_msg}")
    raw = resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
    return _parse_response(raw), raw


def _parse_response(raw: str) -> dict:
    result = {"country": "?", "region": "?", "confidence": "?", "clues": "?", "raw": raw}
    for line in raw.splitlines():
        if line.startswith("СТРАНА:"):
            result["country"] = line.split(":", 1)[1].strip()
        elif line.startswith("РЕГИОН:"):
            result["region"] = line.split(":", 1)[1].strip()
        elif line.startswith("УВЕРЕННОСТЬ:"):
            val = line.split(":", 1)[1].strip().replace("%", "")
            result["confidence"] = val
        elif line.startswith("УЛИКИ:"):
            result["clues"] = line.split(":", 1)[1].strip()
    return result


# ═══════════════════════════════════════════════════════════════════════════════
#  true cli
# ═══════════════════════════════════════════════════════════════════════════════

ANSI = {
    "reset":  "\033[0m",
    "bold":   "\033[1m",
    "dim":    "\033[2m",
    "green":  "\033[92m",
    "amber":  "\033[93m",
    "red":    "\033[91m",
    "cyan":   "\033[96m",
    "white":  "\033[97m",
    "gray":   "\033[90m",
}

def _c(color, text):
    return f"{ANSI[color]}{text}{ANSI['reset']}"

def _banner():
    print()
    print(_c("green",  "  ██████╗ ███████╗ ██████╗  ██████╗ ██╗   ██╗███████╗███████╗███████╗"))
    print(_c("green",  " ██╔════╝ ██╔════╝██╔═══██╗██╔════╝ ██║   ██║██╔════╝██╔════╝██╔════╝"))
    print(_c("green",  " ██║  ███╗█████╗  ██║   ██║██║  ███╗██║   ██║█████╗  ███████╗███████╗"))
    print(_c("green",  " ██║   ██║██╔══╝  ██║   ██║██║   ██║██║   ██║██╔══╝  ╚════██║╚════██║"))
    print(_c("green",  " ╚██████╔╝███████╗╚██████╔╝╚██████╔╝╚██████╔╝███████╗███████║███████║"))
    print(_c("green",  "  ╚═════╝ ╚══════╝ ╚═════╝  ╚═════╝  ╚═════╝ ╚══════╝╚══════╝╚══════╝"))
    print()
    print(_c("gray", "  GeoGuessr AI Helper  ") + _c("dim", "─") * 40)
    print(_c("gray",   f"  Model: {MODEL_NAME}") + _c("dim", "  Vision: ON"))
    print(_c("dim",    "  " + "─" * 50))
    print()

def _prompt_line(cmd, result_text):
    print(_c("green", "  geo@ai:~$ ") + _c("white", cmd))
    if result_text:
        for line in result_text.splitlines():
            print(_c("gray", "  ") + line)

def _spinner(stop_event, label="Sending to Gemini Vision"):
    frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
    i = 0
    while not stop_event.is_set():
        frame = frames[i % len(frames)]
        print(f"\r  {_c('cyan', frame)} {_c('gray', label)}...", end="", flush=True)
        i += 1
        time.sleep(0.08)
    print("\r" + " " * 60 + "\r", end="", flush=True)

def _print_result(parsed: dict):
    conf_raw = parsed.get("confidence", "0")
    try:
        conf_int = int(conf_raw)
    except ValueError:
        conf_int = 0

    conf_color = "green" if conf_int >= 70 else ("amber" if conf_int >= 40 else "red")
    bar_filled = int(conf_int / 5)
    bar = "█" * bar_filled + "░" * (20 - bar_filled)

    print()
    print(_c("dim", "  " + "─" * 50))
    print()
    print(_c("green",  "  СТРАНА:      ") + _c("white", parsed["country"]))
    print(_c("green",  "  РЕГИОН:      ") + _c("white", parsed["region"]))
    print(
        _c("green",  "  УВЕРЕННОСТЬ: ")
        + _c(conf_color, f"{conf_raw}%  ")
        + _c(conf_color, bar)
    )
    print()
    print(_c("amber",  "  УЛИКИ:"))
    for clue in parsed["clues"].split(";"):
        clue = clue.strip()
        if clue:
            print(_c("gray", "    → ") + clue)
    print()
    print(_c("dim", "  " + "─" * 50))
    print()


def run_cli(args):
    """True CLI mode — pure stdin/stdout, no Tkinter."""
    _banner()

    # ── api key ──────────────────────────────────────────────────────────────
    api_key = args.key or ""
    if not api_key:
        _prompt_line("set-api-key [key]", "")
        try:
            import getpass
            api_key = getpass.getpass(
                _c("green", "  geo@ai:~$ ") + _c("amber", "API_KEY")
            ).strip()
        except (KeyboardInterrupt, EOFError):
            print("\n" + _c("red", "  Aborted."))
            sys.exit(0)
    else:
        _prompt_line(f"set-api-key {'*' * 12}", _c("green", "✓ Key loaded from --key flag"))

    print()

    # ── capture ──────────────────────────────────────────────────────────────
    _prompt_line("capture --region full", "")

    if args.bbox:
        try:
            parts = [int(x) for x in args.bbox.split(",")]
            bbox = tuple(parts)
            _prompt_line("", _c("green", f"✓ Using bbox: {bbox}"))
        except Exception:
            print(_c("red", "  [ERROR] --bbox must be x1,y1,x2,y2"))
            sys.exit(1)
    elif args.capture:
        print(_c("amber", "\n  Capturing full screen in 3 seconds. Switch to your game window!"))
        for i in range(3, 0, -1):
            print(_c("amber", f"  {i}..."), end="\r", flush=True)
            time.sleep(1)
        print()
        bbox = None
    else:
        # interactive: ask user to press enter after switching window
        print(_c("amber", "  Press ENTER to capture the full screen (switch to game first):"))
        try:
            input()
        except (KeyboardInterrupt, EOFError):
            print(_c("red", "\n  Aborted."))
            sys.exit(0)
        bbox = None

    try:
        print(_c("gray", "  Taking screenshot..."))
        img_b64 = screenshot_to_b64(bbox)
        _prompt_line("", _c("green", "✓ Screenshot captured"))
    except Exception as e:
        print(_c("red", f"  [ERROR] Screenshot failed: {e}"))
        sys.exit(1)

    print()

    # ── analyze ──────────────────────────────────────────────────────────────
    _prompt_line("analyze --model flash", "")

    stop_ev = threading.Event()
    spin_t = threading.Thread(target=_spinner, args=(stop_ev,), daemon=True)
    spin_t.start()

    try:
        parsed, _ = ask_gemini(api_key, img_b64)
        stop_ev.set()
        spin_t.join()
        _print_result(parsed)
    except Exception as e:
        stop_ev.set()
        spin_t.join()
        print(_c("red", f"\n  [ERROR] API call failed: {e}\n"))
        sys.exit(1)

    # ── loop ─────────────────────────────────────────────────────────────────
    while True:
        try:
            print(_c("green", "  geo@ai:~$ "), end="", flush=True)
            cmd = input().strip().lower()
        except (EOFError, KeyboardInterrupt):
            print(_c("dim", "\n  exit"))
            break

        if cmd in ("exit", "quit", "q"):
            print(_c("dim", "  Goodbye.\n"))
            break
        elif cmd in ("analyze", "a", "capture", "c"):
            print(_c("gray", "  Capturing and analyzing..."))
            try:
                img_b64 = screenshot_to_b64(bbox)
            except Exception as e:
                print(_c("red", f"  [ERROR] {e}"))
                continue
            stop_ev2 = threading.Event()
            spin_t2 = threading.Thread(target=_spinner, args=(stop_ev2,), daemon=True)
            spin_t2.start()
            try:
                parsed, _ = ask_gemini(api_key, img_b64)
                stop_ev2.set()
                spin_t2.join()
                _print_result(parsed)
            except Exception as e:
                stop_ev2.set()
                spin_t2.join()
                print(_c("red", f"  [ERROR] {e}"))
        elif cmd == "help":
            print(_c("amber", "  Commands:"))
            print(_c("gray",  "    analyze / a  — re-capture and analyze"))
            print(_c("gray",  "    exit / q      — quit"))
        else:
            print(_c("red",  f"  Unknown command: '{cmd}'"))
            print(_c("gray",  "  Type 'help' for available commands."))


# ═══════════════════════════════════════════════════════════════════════════════
#  gui
# ═══════════════════════════════════════════════════════════════════════════════

COLORS = {
    "bg":        "#0d0d0d",
    "bg2":       "#111111",
    "bg3":       "#1a1a1a",
    "border":    "#2a2a2a",
    "green":     "#00ff88",
    "green_dim": "#00994d",
    "amber":     "#febc2e",
    "red":       "#ff5f57",
    "cyan":      "#5af",
    "white":     "#e8e8e8",
    "gray":      "#555555",
    "gray2":     "#888888",
}

FONT_MONO = ("Courier New", 10)
FONT_MONO_BOLD = ("Courier New", 10, "bold")
FONT_MONO_SMALL = ("Courier New", 9)
FONT_TITLE = ("Courier New", 13, "bold")


def run_gui(initial_key=""):
    tk = _require("tkinter")
    import tkinter as tkmod
    from tkinter import scrolledtext as st_mod

    root = tkmod.Tk()
    root.title("GeoGuessr AI — Terminal")
    root.geometry("690x720")
    root.configure(bg=COLORS["bg"])
    root.attributes("-topmost", True)
    root.resizable(True, True)

    username = (getpass.getuser() or "user").strip() or "user"
    pcname = (socket.gethostname() or "pc").strip() or "pc"
    shell_title = f"{username}@{pcname}: aiguessr"

    def _get_top_hwnd():
        """Return top-level native window handle for Tk root."""
        hwnd = root.winfo_id()
        if sys.platform.startswith("win"):
            top_hwnd = ctypes.windll.user32.GetParent(hwnd)
            if top_hwnd:
                hwnd = top_hwnd
        return hwnd

    style_state = {"busy": False}

    def _apply_windows_borderless_style():
        """Hide native title bar but keep normal taskbar/minimize behavior."""
        if not sys.platform.startswith("win"):
            return
        if style_state["busy"]:
            return
        style_state["busy"] = True
        try:
            root.update_idletasks()
            hwnd = _get_top_hwnd()
            GWL_STYLE = -16
            GWL_EXSTYLE = -20
            WS_CAPTION = 0x00C00000
            WS_THICKFRAME = 0x00040000
            WS_MINIMIZEBOX = 0x00020000
            WS_MAXIMIZEBOX = 0x00010000
            WS_SYSMENU = 0x00080000
            WS_EX_TOOLWINDOW = 0x00000080
            WS_EX_APPWINDOW = 0x00040000
            SWP_NOMOVE = 0x0002
            SWP_NOSIZE = 0x0001
            SWP_NOZORDER = 0x0004
            SWP_FRAMECHANGED = 0x0020
            SWP_SHOWWINDOW = 0x0040

            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_STYLE)
            # Remove title bar + thick border, keep min/max/sysmenu behavior.
            style = style & ~(WS_CAPTION | WS_THICKFRAME)
            style = style | WS_MINIMIZEBOX | WS_MAXIMIZEBOX | WS_SYSMENU
            ctypes.windll.user32.SetWindowLongW(hwnd, GWL_STYLE, style)

            ex_style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            ex_style = (ex_style & ~WS_EX_TOOLWINDOW) | WS_EX_APPWINDOW
            ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex_style)
            ctypes.windll.user32.SetWindowPos(
                hwnd, 0, 0, 0, 0, 0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_FRAMECHANGED | SWP_SHOWWINDOW
            )
        finally:
            style_state["busy"] = False

    capture_area = [None]   # mutable ref
    api_key_var = tkmod.StringVar(value=initial_key)
    console_input_var = tkmod.StringVar(value="")

    # ── title ────────────────────────────────────────
    chrome = tkmod.Frame(root, bg=COLORS["bg3"], height=34)
    chrome.pack(fill="x")
    chrome.pack_propagate(False)

    # dragging
    drag = {"x": 0, "y": 0}
    window_state = {"maximized": False, "restore_geometry": "690x720+120+120"}

    def close_window():
        root.destroy()

    def minimize_window():
        root.iconify()

    def toggle_maximize():
        if window_state["maximized"]:
            root.geometry(window_state["restore_geometry"])
            window_state["maximized"] = False
            return

        window_state["restore_geometry"] = root.geometry()
        screen_w = root.winfo_screenwidth()
        screen_h = root.winfo_screenheight()
        root.geometry(f"{screen_w}x{screen_h}+0+0")
        window_state["maximized"] = True

    def on_window_map(_e):
        # keep style so it doesnt break when restoring from taskbar
        _apply_windows_borderless_style()

    def start_drag(e):
        if window_state["maximized"]:
            return
        if sys.platform.startswith("win"):
            # moving the window like a real title bar
            WM_NCLBUTTONDOWN = 0x00A1
            HTCAPTION = 2
            ctypes.windll.user32.ReleaseCapture()
            ctypes.windll.user32.SendMessageW(_get_top_hwnd(), WM_NCLBUTTONDOWN, HTCAPTION, 0)
            return
        drag["x"] = e.x_root - root.winfo_x()
        drag["y"] = e.y_root - root.winfo_y()

    def do_drag(e):
        if window_state["maximized"]:
            return
        x = e.x_root - drag["x"]
        y = e.y_root - drag["y"]
        root.geometry(f"+{x}+{y}")

    chrome.bind("<ButtonPress-1>", start_drag)
    if not sys.platform.startswith("win"):
        chrome.bind("<B1-Motion>", do_drag)
    root.bind("<Map>", on_window_map)
    _apply_windows_borderless_style()
    root.after(0, _apply_windows_borderless_style)
    root.after(100, _apply_windows_borderless_style)

    btn_close = tkmod.Button(
        chrome, bg="#ff5f57", activebackground="#e0443e",
        relief="flat", bd=0, highlightthickness=0, command=close_window, cursor="hand2"
    )
    btn_close.place(x=14, y=10, width=14, height=14)

    btn_min = tkmod.Button(
        chrome, bg="#febc2e", activebackground="#dfa027",
        relief="flat", bd=0, highlightthickness=0, command=minimize_window, cursor="hand2"
    )
    btn_min.place(x=34, y=10, width=14, height=14)

    btn_max = tkmod.Button(
        chrome, bg="#28c840", activebackground="#1fab35",
        relief="flat", bd=0, highlightthickness=0, command=toggle_maximize, cursor="hand2"
    )
    btn_max.place(x=54, y=10, width=14, height=14)

    tkmod.Label(
        chrome, text=shell_title,
        bg=COLORS["bg3"], fg=COLORS["gray2"],
        font=FONT_MONO_SMALL
    ).place(relx=0.5, rely=0.5, anchor="center")

    # ── scrollable terminal ─────────────────────────────────────────────
    body = tkmod.Frame(root, bg=COLORS["bg"])
    body.pack(fill="both", expand=True)

    term = st_mod.ScrolledText(
        body, wrap="word",
        bg=COLORS["bg"], fg=COLORS["white"],
        font=FONT_MONO,
        insertbackground=COLORS["green"],
        relief="flat", bd=0,
        padx=20, pady=16,
        state="disabled",
        cursor="xterm",
    )
    term.pack(fill="both", expand=True)

    # tag styles
    term.tag_config("ps1",    foreground=COLORS["green"], font=FONT_MONO_BOLD)
    term.tag_config("cmd",    foreground=COLORS["white"], font=FONT_MONO_BOLD)
    term.tag_config("out",    foreground=COLORS["gray2"])
    term.tag_config("green",  foreground=COLORS["green"])
    term.tag_config("amber",  foreground=COLORS["amber"])
    term.tag_config("red",    foreground=COLORS["red"])
    term.tag_config("cyan",   foreground=COLORS["cyan"])
    term.tag_config("dim",    foreground=COLORS["gray"])
    term.tag_config("white",  foreground=COLORS["white"])

    def write(*segments):
        """Write colored segments to terminal. segments = (tag, text) pairs or plain str."""
        term.config(state="normal")
        for seg in segments:
            if isinstance(seg, str):
                term.insert("end", seg)
            else:
                tag, text = seg
                term.insert("end", text, tag)
        term.config(state="disabled")
        term.see("end")
        root.update()

    def write_line(*segments):
        write(*segments, "\n")

    def write_prompt(cmd, *output_lines):
        write(("ps1", "geo@ai:~$ "), ("cmd", cmd), "\n")
        for line in output_lines:
            if isinstance(line, list):
                write(*line, "\n")
            else:
                write(("out", "  " + line), "\n")

    def separator():
        write(("dim", "  " + "─" * 54 + "\n"))

    # ── bottom control strip ─────────────────────────────────────────────────
    ctrl = tkmod.Frame(root, bg=COLORS["bg3"], pady=10)
    ctrl.pack(fill="x", side="bottom")

    # api key row
    api_row = tkmod.Frame(ctrl, bg=COLORS["bg3"])
    api_row.pack(fill="x", padx=20, pady=(0, 8))

    tkmod.Label(api_row, text="API KEY", bg=COLORS["bg3"], fg=COLORS["green"],
                font=FONT_MONO_BOLD).pack(side="left")

    api_entry = tkmod.Entry(
        api_row, textvariable=api_key_var, show="*",
        bg=COLORS["bg2"], fg=COLORS["white"], insertbackground=COLORS["green"],
        font=FONT_MONO, relief="flat", bd=0,
        highlightthickness=1,
        highlightbackground=COLORS["border"],
        highlightcolor=COLORS["green"],
    )
    api_entry.pack(side="left", fill="x", expand=True, ipady=4, padx=(4, 0))

    show_var = tkmod.BooleanVar(value=False)
    def toggle_show():
        api_entry.config(show="" if show_var.get() else "*")
    tkmod.Checkbutton(
        api_row, text="show", variable=show_var, command=toggle_show,
        bg=COLORS["bg3"], fg=COLORS["gray2"], selectcolor=COLORS["bg3"],
        activebackground=COLORS["bg3"], font=FONT_MONO_SMALL, bd=0,
    ).pack(side="left", padx=(8, 0))

    # button row
    btn_row = tkmod.Frame(ctrl, bg=COLORS["bg3"])
    btn_row.pack(fill="x", padx=20)

    btn_style = dict(
        bg=COLORS["bg2"], fg=COLORS["gray2"],
        activebackground=COLORS["bg3"], activeforeground=COLORS["green"],
        font=FONT_MONO_BOLD, relief="flat", bd=0,
        padx=14, pady=8,
        cursor="hand2",
        highlightthickness=1,
        highlightbackground=COLORS["border"],
    )

    btn_capture = tkmod.Button(btn_row, text="[ capture ]", **btn_style)
    btn_capture.pack(side="left", padx=(0, 8))

    btn_analyze = tkmod.Button(btn_row, text="[ analyze ]", **btn_style,
                               state="disabled")
    btn_analyze.pack(side="left", padx=(0, 8))

    btn_clear = tkmod.Button(btn_row, text="[ clear ]", **btn_style)
    btn_clear.pack(side="left")

    tkmod.Label(
        btn_row, text=f"model: {MODEL_NAME}",
        bg=COLORS["bg3"], fg=COLORS["gray"],
        font=FONT_MONO_SMALL
    ).pack(side="right", padx=4)

    # console input row
    input_row = tkmod.Frame(ctrl, bg=COLORS["bg3"])
    input_row.pack(fill="x", padx=20, pady=(8, 0))
    tkmod.Label(
        input_row, text="geo@ai:~$",
        bg=COLORS["bg3"], fg=COLORS["green"],
        font=FONT_MONO_BOLD
    ).pack(side="left")
    console_entry = tkmod.Entry(
        input_row, textvariable=console_input_var,
        bg=COLORS["bg2"], fg=COLORS["white"], insertbackground=COLORS["green"],
        font=FONT_MONO, relief="flat", bd=0,
        highlightthickness=1,
        highlightbackground=COLORS["border"],
        highlightcolor=COLORS["green"],
    )
    console_entry.pack(side="left", fill="x", expand=True, ipady=4, padx=(8, 8))

    # ── boot sequence ────────────────────────────────────────────────────────
    def boot():
        time.sleep(0.1)
        write(("dim", "\n"))
        lines = [
            ("dim",   "  aiguessr-gui / Learn more at https://github.com/g70xl0l/aiguessr-cli"),
            ("dim",   "  " + "─" * 40),
        ]
        for tag, text in lines:
            write_line((tag, text))
        time.sleep(0.15)
        write_prompt(
            "init --model flash-latest",
            [("green", "  ✓ "), ("out", f"Gemini {MODEL_NAME} loaded")],
            [("green", "  ✓ "), ("out", "Successfully?: "), ("green", "YES")],
        )
        separator()
        write_prompt(
            "help",
            [("amber", "  Commands available:")],
            [("dim", "    [ capture ]  "), ("out", "— выделить область Street View")],
            [("dim", "    [ analyze ]  "), ("out", "— отправить на анализ в Gemini")],
            [("dim", "    [ clear ]    "), ("out", "— очистить терминал")],
        )
        separator()
        write(("ps1", "geo@ai:~$ "), ("dim", "▌\n"))

    threading.Thread(target=boot, daemon=True).start()

    # ── capture logic ────────────────────────────────────────────────────────
    def start_capture():
        write(("ps1", "geo@ai:~$ "), ("cmd", "capture --region\n"))
        root.withdraw()
        time.sleep(0.05)

        sel = tkmod.Toplevel()
        sel.attributes("-fullscreen", True)
        sel.attributes("-alpha", 0.25)
        sel.configure(bg="#000")
        sel.config(cursor="crosshair")

        canvas = tkmod.Canvas(sel, cursor="crosshair", bg="#000000", highlightthickness=0)
        canvas.pack(fill="both", expand=True)

        state = {"x": None, "y": None, "rect": None}

        def on_press(e):
            state["x"], state["y"] = e.x, e.y
            state["rect"] = canvas.create_rectangle(
                e.x, e.y, e.x, e.y,
                outline=COLORS["red"], width=2,
                dash=(4, 4),
            )

        def on_drag(e):
            canvas.coords(state["rect"], state["x"], state["y"], e.x, e.y)
            # draw dimensions label
            canvas.delete("dim_label")
            canvas.create_text(
                e.x + 8, e.y + 14,
                text=f"{abs(e.x - state['x'])}×{abs(e.y - state['y'])}",
                fill=COLORS["amber"], font=("Courier New", 11, "bold"),
                anchor="nw", tags="dim_label"
            )

        def on_release(e):
            x1 = min(state["x"], e.x)
            y1 = min(state["y"], e.y)
            x2 = max(state["x"], e.x)
            y2 = max(state["y"], e.y)
            sel.destroy()
            root.deiconify()

            if (x2 - x1) > 50 and (y2 - y1) > 50:
                capture_area[0] = (x1, y1, x2, y2)
                btn_analyze.config(
                    state="normal",
                    fg=COLORS["green"],
                    highlightbackground=COLORS["green_dim"],
                )
                write_prompt(
                    "",
                    [("green", f"  ✓ Region captured: "),
                     ("white",  f"{x2-x1}×{y2-y1}px at ({x1},{y1})")],
                )
            else:
                write_prompt("", [("red", "  ✗ Region too small, try again")])

            separator()
            write(("ps1", "geo@ai:~$ "), ("dim", "▌\n"))

        def on_escape(e):
            sel.destroy()
            root.deiconify()
            write_prompt("", [("amber", "  ⚠ Capture cancelled")])
            separator()
            write(("ps1", "geo@ai:~$ "), ("dim", "▌\n"))

        canvas.bind("<ButtonPress-1>", on_press)
        canvas.bind("<B1-Motion>",     on_drag)
        canvas.bind("<ButtonRelease-1>", on_release)
        sel.bind("<Escape>", on_escape)

    btn_capture.config(command=start_capture)

    # ── analyze logic (screenshot and send to Gemini) ────────────────────────────────────────────────────────
    def do_analyze():
        key = api_key_var.get().strip()
        if not key:
            write_prompt("analyze --model flash",
                         [("red", "  ✗ API key is empty. Set API KEY below.")])
            separator()
            write(("ps1", "geo@ai:~$ "), ("dim", "▌\n"))
            return

        btn_analyze.config(state="disabled", fg=COLORS["gray"])
        btn_capture.config(state="disabled")

        def _run():
            write_prompt("analyze --model flash", "")

            # Screenshot
            try:
                write(("cyan", "  ▶ "), ("out", "Taking screenshot...\n"))
                img_b64 = screenshot_to_b64(capture_area[0])
                write(("green", "  ✓ "), ("out", "Screenshot captured\n"))
            except Exception as e:
                write(("red", f"  ✗ Screenshot failed: {e}\n"))
                separator()
                write(("ps1", "geo@ai:~$ "), ("dim", "▌\n"))
                btn_analyze.config(state="normal", fg=COLORS["green"])
                btn_capture.config(state="normal")
                return

            # cool animation in terminal
            frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
            stop_flag = [False]

            def spin():
                i = 0
                while not stop_flag[0]:
                    frame = frames[i % len(frames)]
                    term.config(state="normal")
                    # overwrite the cool animation
                    term.delete("spinner_start", "end")
                    term.insert("end", f"  {frame} Sending to Gemini...\n", "cyan")
                    term.mark_set("spinner_start", "end-2l")
                    term.config(state="disabled")
                    term.see("end")
                    root.update()
                    i += 1
                    time.sleep(0.08)

            term.config(state="normal")
            term.mark_set("spinner_start", "end")
            term.config(state="disabled")

            spin_t = threading.Thread(target=spin, daemon=True)
            spin_t.start()

            try:
                parsed, _ = ask_gemini(key, img_b64)
                stop_flag[0] = True
                spin_t.join()

                # clear spinner line
                term.config(state="normal")
                term.delete("spinner_start", "end")
                term.config(state="disabled")

                conf_raw = parsed.get("confidence", "0")
                try:
                    conf_int = int(conf_raw)
                except ValueError:
                    conf_int = 0

                conf_tag = "green" if conf_int >= 70 else ("amber" if conf_int >= 40 else "red")
                bar_filled = int(conf_int / 5)
                bar = "█" * bar_filled + "░" * (20 - bar_filled)

                separator()
                write(
                    ("green", "  СТРАНА:       "), ("white", parsed["country"]), "\n",
                    ("green", "  РЕГИОН:       "), ("white", parsed["region"]), "\n",
                    (conf_tag, f"  УВЕРЕННОСТЬ:  {conf_raw}%  {bar}"), "\n",
                )
                write("\n", ("amber", "  УЛИКИ:\n"))
                for clue in parsed["clues"].split(";"):
                    clue = clue.strip()
                    if clue:
                        write(("dim", "    → "), ("out", clue), "\n")
                separator()

            except Exception as e:
                stop_flag[0] = True
                spin_t.join()
                term.config(state="normal")
                term.delete("spinner_start", "end")
                term.config(state="disabled")
                write(("red", f"  ✗ API error: {e}\n"))
                separator()

            write(("ps1", "geo@ai:~$ "), ("dim", "▌\n"))
            btn_analyze.config(state="normal", fg=COLORS["green"])
            btn_capture.config(state="normal")

        threading.Thread(target=_run, daemon=True).start()

    btn_analyze.config(command=do_analyze)

    # ── clear ────────────────────────────────────────────────────────────────
    def do_clear():
        term.config(state="normal")
        term.delete("1.0", "end")
        term.config(state="disabled")
        write(("dim", "  [terminal cleared]\n\n"))
        write(("ps1", "geo@ai:~$ "), ("dim", "▌\n"))

    btn_clear.config(command=do_clear)

    def execute_console_command():
        cmd_raw = console_input_var.get().strip()
        if not cmd_raw:
            return
        console_input_var.set("")
        cmd = cmd_raw.lower()

        if cmd in ("capture", "c", "capture --region"):
            start_capture()
        elif cmd in ("analyze", "a", "analyze --model flash"):
            do_analyze()
        elif cmd == "clear":
            write(("ps1", "geo@ai:~$ "), ("cmd", cmd_raw), "\n")
            do_clear()
        elif cmd == "help":
            write(("ps1", "geo@ai:~$ "), ("cmd", cmd_raw), "\n")
            write_line(("amber", "  Commands:"))
            write_line(("dim", "    capture / c"), ("out", "  — выделить область Street View"))
            write_line(("dim", "    analyze / a"), ("out", "  — сделать скрин и отправить в Gemini"))
            write_line(("dim", "    clear"), ("out", "         — очистить терминал"))
            write_line(("dim", "    exit / quit"), ("out", "   — закрыть окно"))
            separator()
            write(("ps1", "geo@ai:~$ "), ("dim", "▌\n"))
        elif cmd in ("exit", "quit", "q"):
            write(("ps1", "geo@ai:~$ "), ("cmd", cmd_raw), "\n")
            write(("dim", "  exit\n"))
            root.after(50, root.destroy)
        else:
            write(("ps1", "geo@ai:~$ "), ("cmd", cmd_raw), "\n")
            write(("red", f"  Unknown command: '{cmd_raw}'\n"))
            write(("out", "  Type 'help' for available commands.\n"))
            separator()
            write(("ps1", "geo@ai:~$ "), ("dim", "▌\n"))

    btn_run = tkmod.Button(btn_row, text="[ run ]", **btn_style, command=execute_console_command)
    btn_run.pack(side="left", padx=(8, 0))

    # ── enter ────────────────────────
    console_entry.bind("<Return>", lambda e: execute_console_command())
    console_entry.focus_set()

    root.mainloop()


# ═══════════════════════════════════════════════════════════════════════════════
#  entry point
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        prog="geoguessr-helper",
        description="ai geoguessr helper that uses Gemini for responses.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python geoguessr_helper.py                        # GUI mode (default)
  python geoguessr_helper.py --cli                  # Interactive CLI
  python geoguessr_helper.py --cli --capture        # CLI with 3s countdown capture instead of waiting for Enter
  python geoguessr_helper.py --cli --key AIzaSy...  # CLI with key pre-filled
  python geoguessr_helper.py --cli --key AIzaSy... --capture --bbox 0,0,1280,720 # CLI with capture region and key pre-filled
        """,
    )
    parser.add_argument(
        "--cli", action="store_true",
        help="Run in true CLI mode",
    )
    parser.add_argument(
        "--key", type=str, default="",
        help="Gemini API key (skips interactive prompt)",
    )
    parser.add_argument(
        "--capture", action="store_true",
        help="CLI mode: auto-capture with 3s countdown instead of waiting for Enter",
    )
    parser.add_argument(
        "--bbox", type=str, default="",
        help="CLI mode: capture region x1,y1,x2,y2 (e.g. 0,0,1280,720)",
    )

    args = parser.parse_args()

    if args.cli:
        run_cli(args)
    else:
        if args.bbox or args.capture:
            print("[WARN] --bbox and --capture only apply in --cli mode. Launching GUI...")
        run_gui(initial_key=args.key)


if __name__ == "__main__":
    main()
