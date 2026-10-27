#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Shuibo injector -- inject the WebGL ripple effect into any local HTML page.

Usage:
    python inject.py                     GUI: list HTML files in this folder
    python inject.py --cli <file>        CLI: inject one file
    python inject.py --cli <file> --bg builtin   force builtin background at runtime
    python inject.py --cli <file> --remove       remove the injection (restore)
    python inject.py --cli <file> --set speed=3 --set damping=0.98
    python inject.py --reset-defaults    restore factory ripple parameters

Ripple parameters (defaults = the demo page index.html):
    speed        propagation speed        (default 2)
    damping      decay retention factor   (default 0.985)
    perturbance  wave height / refraction (default 0.03)
    dropRadius   ripple size / spacing    (default 20)
    resolution   simulation fineness      (default 256)

The injected block is wrapped in  <!-- SHUIBO-INJECT:START/END -->  markers,
inserted right before </body>, and the file is backed up as <name>.bak
before the first modification. Removal verifies byte-identical restoration.

Encoding policy: BOM > <meta charset> > utf-8 strict > gbk strict.
If none decodes strictly, the file is refused -- never lossy-decoded.
The injected block is pure ASCII, so it cannot corrupt any ANSI codepage.
"""

import argparse
import codecs
import json
import os
import re
import shutil
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LIB_NAME = "webgl-ripples.js"
BG_NAME = "bg-datauri.js"
START_MARK = "<!-- SHUIBO-INJECT:START -->"
END_MARK = "<!-- SHUIBO-INJECT:END -->"
BODY_RE = re.compile(r"</body\s*>", re.I)
BLOCK_RE = re.compile(re.escape(START_MARK) + r".*?" + re.escape(END_MARK) + r"\r?\n?", re.S)

# Decode fallback chain per design doc section 4.4.
BOMS = (
    (codecs.BOM_UTF8, "utf-8-sig"),
    (codecs.BOM_UTF32_LE, "utf-32"),
    (codecs.BOM_UTF32_BE, "utf-32"),
    (codecs.BOM_UTF16_LE, "utf-16"),
    (codecs.BOM_UTF16_BE, "utf-16"),
)
GBK_ALIASES = ("gbk", "gb2312", "gb18030", "cp936")
UTF8_ALIASES = ("utf-8", "utf8", "unicode-1-1-utf-8")

# Ripple parameters. Defaults are exactly what the demo page index.html and
# the library's original hardcoded shader constants produce.
PARAMS_FILE = os.path.join(SCRIPT_DIR, "shuibo-params.json")
PARAM_DEFAULTS = {
    "speed": 2.0,       # propagation speed
    "damping": 0.985,   # decay retention factor (higher = ripples last longer)
    "perturbance": 0.03,  # wave height / refraction intensity
    "dropRadius": 20,   # ripple size / spacing in px
    "resolution": 256,  # simulation grid size
}
PARAM_RANGES = {
    "speed": (0.1, 10.0, float),
    "damping": (0.5, 0.999, float),
    "perturbance": (0.0, 0.5, float),
    "dropRadius": (1, 200, int),
    "resolution": (32, 2048, int),
}


class InjectError(Exception):
    """Fatal, user-facing error: refuse to touch the file."""


# --------------------------------------------------------------------------
# Encoding
# --------------------------------------------------------------------------

def detect_encoding(raw):
    """Return (decoded_text, write_codec) or raise InjectError."""
    for bom, codec in BOMS:
        if raw.startswith(bom):
            try:
                return raw[len(bom):].decode(codec), codec
            except UnicodeDecodeError:
                raise InjectError("BOM present but content does not decode; refusing.")

    head = raw[:2048].decode("latin-1", "ignore")
    m = re.search(r"<meta[^>]*?charset\s*=\s*[\"']?\s*([\w-]+)", head, re.I)
    if m:
        declared = m.group(1).lower()
        if declared in UTF8_ALIASES:
            try:
                return raw.decode("utf-8"), "utf-8"
            except UnicodeDecodeError:
                pass  # declared utf-8 but invalid: fall through to the chain
        elif declared in GBK_ALIASES:
            try:
                return raw.decode("gbk"), "gbk"
            except UnicodeDecodeError:
                raise InjectError(
                    "Declared charset is GBK but the file does not strictly "
                    "decode as GBK; refusing (never lossy-decode)."
                )

    # No usable declaration: utf-8 strict first (GBK bytes are almost never
    # valid UTF-8, so a strict success is trustworthy), then gbk strict.
    try:
        return raw.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        pass
    try:
        return raw.decode("gbk"), "gbk"
    except UnicodeDecodeError:
        pass
    raise InjectError(
        "Cannot determine encoding (not BOM / meta / utf-8 / gbk strict); "
        "refusing to modify the file."
    )


def read_file(path):
    with open(path, "rb") as f:
        raw = f.read()
    text, codec = detect_encoding(raw)
    return text, codec


def write_file(path, text, codec):
    with open(path, "wb") as f:
        f.write(text.encode(codec))


def is_injected(path):
    try:
        with open(path, "rb") as f:
            return START_MARK.encode("ascii") in f.read()
    except OSError:
        return False


# --------------------------------------------------------------------------
# Ripple parameters
# --------------------------------------------------------------------------

def validate_params(params):
    """Raise InjectError on unknown keys or out-of-range values."""
    for key, value in params.items():
        if key not in PARAM_DEFAULTS:
            raise InjectError(
                "Unknown parameter %r; valid keys: %s" % (key, ", ".join(PARAM_DEFAULTS))
            )
        lo, hi, cast = PARAM_RANGES[key]
        try:
            num = cast(value)
        except (TypeError, ValueError):
            raise InjectError("Parameter %s must be a number, got %r" % (key, value))
        if not (lo <= num <= hi):
            raise InjectError("Parameter %s out of range [%s, %s]: %s" % (key, lo, hi, num))


def load_params():
    """Defaults merged with the saved config file (if present and valid)."""
    params = dict(PARAM_DEFAULTS)
    if os.path.isfile(PARAMS_FILE):
        try:
            with open(PARAMS_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
            if isinstance(saved, dict):
                validate_params(saved)
                params.update(saved)
        except (OSError, ValueError, InjectError):
            pass  # a broken config silently falls back to defaults
    return params


def save_params(params):
    """Persist custom params; the file is removed when values equal defaults."""
    try:
        if params == PARAM_DEFAULTS:
            if os.path.exists(PARAMS_FILE):
                os.remove(PARAMS_FILE)
        else:
            with open(PARAMS_FILE, "w", encoding="utf-8") as f:
                json.dump(params, f, indent=2, sort_keys=True)
    except OSError as exc:
        raise InjectError("Cannot write %s: %s" % (os.path.basename(PARAMS_FILE), exc))


def parse_set_items(items):
    """--set key=value items -> validated partial overrides."""
    overrides = {}
    for item in items or []:
        if "=" not in item:
            raise InjectError("--set expects key=value, got %r" % item)
        key, value = item.split("=", 1)
        overrides[key.strip()] = value.strip()
    if overrides:
        validate_params(overrides)
    return overrides


# --------------------------------------------------------------------------
# Injected JavaScript (pure ASCII, runtime background decision chain)
# --------------------------------------------------------------------------

INJECTED_JS = r"""/* SHUIBO ripple injection. Content between the START/END markers is
   machine-managed; do not edit inside this block. */
if (typeof window.Ripples === "function") {
  var FORCE_BUILTIN = __FORCE_BUILTIN__;
  var CFG = __CFG_JSON__;
  var host = document.createElement("div");
  host.setAttribute("data-shuibo", "host");
  host.style.cssText =
    "position:fixed;left:0;top:0;width:100%;height:100%;" +
    "z-index:-1;pointer-events:none;";
  document.body.appendChild(host);
  /* computeTextureBoundaries() reads inline styles only. These lines are
     mandatory, otherwise parseFloat("") -> NaN and the canvas goes black. */
  host.style.backgroundSize = "cover";
  host.style.backgroundPosition = "center";

  function extractUrl(css) {
    if (!css || css === "none") return null;
    var m = css.match(/url\((['"]?)(.*?)\1\)/);
    return m && m[2] ? m[2] : null;
  }
  function isDataUri(s) { return /^data:/i.test(s || ""); }

  /* Level 1 source: whatever background the cascade actually resolved. */
  function pageBackground() {
    var body = getComputedStyle(document.body).backgroundImage;
    var html = getComputedStyle(document.documentElement).backgroundImage;
    return extractUrl(body) || extractUrl(html);
  }
  /* Level 2 source: builtin data-URI background (same-origin under file://). */
  function builtinBackground() {
    var bg = window.__RIPPLE_BG__;
    if (!bg) return null;
    return window.innerWidth < 768 && bg.mobile ? bg.mobile : (bg.desktop || bg.mobile || null);
  }
  /* Level 3 fallback: noise texture tinted with the page background color. */
  function noiseBackground() {
    var c = document.createElement("canvas");
    c.width = 512; c.height = 512;
    var ctx = c.getContext("2d");
    ctx.fillStyle = getComputedStyle(document.body).backgroundColor || "#ffffff";
    ctx.fillRect(0, 0, 512, 512);
    var img = ctx.getImageData(0, 0, 512, 512), d = img.data;
    for (var i = 0; i < d.length; i += 4) {
      var n = (Math.random() * 24 - 12) | 0;
      d[i] += n; d[i + 1] += n; d[i + 2] += n;
    }
    ctx.putImageData(img, 0, 0);
    return c.toDataURL("image/png");
  }
  /* Preload before init: the library fails silently to a transparent
     texture on image errors, which would look like "ripples broken". */
  function tryLoad(url, cb) {
    if (!url) { cb(null); return; }
    var img = new Image();
    img.onload = function () { cb(url); };
    img.onerror = function () { cb(null); };
    img.src = url;
  }

  var attempts = [];
  var pageBg = pageBackground();
  /* Under file:// a local relative image is always rejected by WebGL. */
  var pageUsable = pageBg && (location.protocol !== "file:" || isDataUri(pageBg));
  if (!FORCE_BUILTIN && pageUsable) {
    attempts.push(function (cb) { tryLoad(pageBg, cb); });
  }
  attempts.push(function (cb) { tryLoad(builtinBackground(), cb); });
  attempts.push(function (cb) { tryLoad(noiseBackground(), cb); });

  var step = 0;
  (function next() {
    if (step >= attempts.length) return;
    attempts[step++](function (src) { src ? start(src) : next(); });
  })();

  function start(bg) {
    /* Static background first: graceful fallback if WebGL is unavailable. */
    host.style.backgroundImage = 'url("' + String(bg).replace(/"/g, "%22") + '")';
    var ripple;
    try {
      ripple = new Ripples(host, {
        imageUrl: bg,
        resolution: CFG.resolution,
        dropRadius: CFG.dropRadius,
        perturbance: CFG.perturbance,
        speed: CFG.speed,
        damping: CFG.damping,
        interactive: false
      });
    } catch (err) {
      return; /* keep the static background, never break the host page */
    }
    /* The ripple layer cannot receive pointer events (pointer-events:none),
       so listen on window and reuse the library's own dropAtPointer(),
       with the same strengths as its native interaction. */
    window.addEventListener("mousemove", function (e) {
      ripple.dropAtPointer(e, 20, 0.01);
    }, { passive: true });
    window.addEventListener("mousedown", function (e) {
      ripple.dropAtPointer(e, 30, 0.14);
    }, { passive: true });
    window.addEventListener("touchmove", function (e) {
      for (var k = 0; k < e.changedTouches.length; k++) {
        ripple.dropAtPointer(e.changedTouches[k], 20, 0.01);
      }
    }, { passive: true });
    window.addEventListener("touchstart", function (e) {
      for (var k = 0; k < e.changedTouches.length; k++) {
        ripple.dropAtPointer(e.changedTouches[k], 30, 0.14);
      }
    }, { passive: true });
    /* Ambient drops, same rhythm as the demo page. */
    setInterval(function () {
      var rect = host.getBoundingClientRect();
      ripple.drop(Math.random() * rect.width, Math.random() * rect.height, 24, 0.06);
    }, 3000);
  }
}"""


def build_block(newline, force_builtin, include_bg, params):
    js = INJECTED_JS.replace("__FORCE_BUILTIN__", "true" if force_builtin else "false")
    js = js.replace("__CFG_JSON__", json.dumps(params, sort_keys=True))
    lines = []
    if include_bg:
        lines.append('<script src="./' + BG_NAME + '"></script>')
    lines.append('<script src="./' + LIB_NAME + '"></script>')
    lines.append("<script>")
    lines.append(js)
    lines.append("</script>")
    inner = newline.join(lines)
    return START_MARK + newline + inner + newline + END_MARK + newline


# --------------------------------------------------------------------------
# Core operations
# --------------------------------------------------------------------------

def strip_block(text):
    return BLOCK_RE.sub("", text)


def inject_file(path, force_builtin=False, param_overrides=None):
    path = os.path.abspath(path)
    if not os.path.isfile(path):
        raise InjectError("File not found: %s" % path)
    target_dir = os.path.dirname(path)
    if not os.path.isfile(os.path.join(target_dir, LIB_NAME)):
        raise InjectError(
            "%s not found next to the target file. Copy it into the same "
            "folder first (no dead links are ever written)." % LIB_NAME
        )
    include_bg = os.path.isfile(os.path.join(target_dir, BG_NAME))

    params = load_params()
    if param_overrides:
        params.update({k: PARAM_RANGES[k][2](v) for k, v in param_overrides.items()})
        validate_params(params)
        save_params(params)

    text, codec = read_file(path)
    newline = "\r\n" if "\r\n" in text else "\n"
    stripped = strip_block(text)

    m = BODY_RE.search(stripped)
    block = build_block(newline, force_builtin, include_bg, params)
    if m:
        new_text = stripped[: m.start()] + block + stripped[m.start():]
    else:
        new_text = stripped + block  # no </body>: append at end of file

    backup = path + ".bak"
    if not os.path.exists(backup):
        shutil.copy2(path, backup)

    write_file(path, new_text, codec)
    return "Injected -> %s (codec=%s, backup=%s)" % (
        os.path.basename(path), codec, os.path.basename(backup)
    )


def remove_file(path):
    path = os.path.abspath(path)
    if not os.path.isfile(path):
        raise InjectError("File not found: %s" % path)

    text, codec = read_file(path)
    stripped = strip_block(text)
    if stripped == text:
        return "No injection block in %s; nothing to do." % os.path.basename(path)

    backup = path + ".bak"
    verified = False
    if os.path.exists(backup):
        with open(backup, "rb") as f:
            original = f.read()
        try:
            encoded = stripped.encode(codec)
        except UnicodeEncodeError:
            encoded = None
        verified = encoded is not None and encoded == original

    write_file(path, stripped, codec)
    if verified:
        return "Removed from %s; byte-identical to the .bak original. Verified." % (
            os.path.basename(path))
    return "Removed from %s (no .bak to compare against, or codec note)." % (
        os.path.basename(path))


# --------------------------------------------------------------------------
# CLI / GUI
# --------------------------------------------------------------------------

def list_html_files():
    try:
        names = sorted(os.listdir(SCRIPT_DIR))
    except OSError:
        return []
    return [n for n in names if n.lower().endswith((".html", ".htm"))
            and os.path.isfile(os.path.join(SCRIPT_DIR, n))]


def run_cli(args):
    try:
        overrides = parse_set_items(args.set)
        if args.remove:
            print(remove_file(args.cli))
        else:
            print(inject_file(args.cli, force_builtin=(args.bg == "builtin"),
                              param_overrides=overrides))
    except InjectError as exc:
        print("[REFUSED] %s" % exc)
        sys.exit(1)


def run_gui():
    try:
        import tkinter as tk
        from tkinter import ttk, messagebox
    except ImportError:
        print("tkinter unavailable; use the CLI: python inject.py --cli <file>")
        sys.exit(1)

    root = tk.Tk()
    root.title("Shuibo injector")
    root.geometry("620x560")
    root.minsize(540, 480)

    ttk.Label(root, text="HTML files in this folder (checked = will be processed):",
              padding=(10, 8)).pack(anchor="w")

    vars_by_name = {}

    def refresh():
        for w in frame.winfo_children():
            w.destroy()
        vars_by_name.clear()
        for name in list_html_files():
            var = tk.BooleanVar(value=False)
            vars_by_name[name] = var
            status = "injected" if is_injected(os.path.join(SCRIPT_DIR, name)) else "clean"
            row = ttk.Frame(frame)
            row.pack(fill="x", padx=14, pady=1)
            ttk.Checkbutton(row, text=name, variable=var).pack(side="left")
            ttk.Label(row, text=status, foreground="#777").pack(side="right", padx=6)

    outer = ttk.Frame(root)
    outer.pack(fill="both", expand=True, padx=6)
    canvas = tk.Canvas(outer, highlightthickness=0)
    sb = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
    frame = ttk.Frame(canvas, padding=(4, 2, 4, 8))
    frame.bind("<Configure>",
               lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.create_window((0, 0), window=frame, anchor="nw", width=520)
    canvas.configure(yscrollcommand=sb.set)
    canvas.pack(side="left", fill="both", expand=True)
    sb.pack(side="right", fill="y")

    def selected():
        return [n for n, v in vars_by_name.items() if v.get()]

    # Ripple parameter panel (defaults = the demo page index.html).
    PARAM_LABELS = (
        ("speed", "speed"),
        ("damping", "damping"),
        ("perturbance", "wave height"),
        ("dropRadius", "ripple size"),
        ("resolution", "fineness"),
    )
    params_frame = ttk.LabelFrame(root, text=" Ripple parameters (defaults = index.html) ",
                                  padding=8)
    params_frame.pack(fill="x", padx=10, pady=(6, 0))
    entries = {}
    for i, (key, label) in enumerate(PARAM_LABELS):
        ttk.Label(params_frame, text=key + " (" + label + ")").grid(
            row=i // 3, column=(i % 3) * 2, sticky="e", padx=(0, 3), pady=2)
        ent = ttk.Entry(params_frame, width=8)
        ent.insert(0, str(load_params()[key]))
        ent.grid(row=i // 3, column=(i % 3) * 2 + 1, sticky="w", padx=(0, 12), pady=2)
        entries[key] = ent

    def collect_params():
        values = {k: e.get().strip() for k, e in entries.items()}
        validate_params(values)
        return {k: PARAM_RANGES[k][2](v) for k, v in values.items()}

    def reset_params():
        for key, e in entries.items():
            e.delete(0, "end")
            e.insert(0, str(PARAM_DEFAULTS[key]))
        try:
            save_params(dict(PARAM_DEFAULTS))
        except InjectError as exc:
            messagebox.showerror("Shuibo", str(exc))
            return
        messagebox.showinfo("Shuibo", "Parameters restored to defaults.")

    def do_inject():
        names = selected()
        if not names:
            messagebox.showinfo("Shuibo", "Select at least one file first.")
            return
        try:
            params = collect_params()
            save_params(params)
        except InjectError as exc:
            messagebox.showerror("Shuibo", str(exc))
            return
        ok, bad = [], []
        for name in names:
            try:
                inject_file(os.path.join(SCRIPT_DIR, name), param_overrides=params)
                ok.append(name)
            except InjectError as exc:
                bad.append("%s: %s" % (name, exc))
        refresh()
        msg = "Injected:\n  " + "\n  ".join(ok) if ok else "Nothing injected."
        if bad:
            msg += "\n\nRefused:\n  " + "\n  ".join(bad)
        messagebox.showinfo("Shuibo", msg)

    def do_remove():
        names = selected()
        if not names:
            messagebox.showinfo("Shuibo", "Select at least one file first.")
            return
        ok, bad = [], []
        for name in names:
            try:
                remove_file(os.path.join(SCRIPT_DIR, name))
                ok.append(name)
            except InjectError as exc:
                bad.append("%s: %s" % (name, exc))
        refresh()
        msg = "Removed:\n  " + "\n  ".join(ok) if ok else "Nothing removed."
        if bad:
            msg += "\n\nRefused:\n  " + "\n  ".join(bad)
        messagebox.showinfo("Shuibo", msg)

    buttons = ttk.Frame(root, padding=10)
    buttons.pack(fill="x")
    ttk.Button(buttons, text="Start injection", command=do_inject).pack(side="left", padx=(0, 8))
    ttk.Button(buttons, text="Remove injection", command=do_remove).pack(side="left")
    ttk.Button(buttons, text="Restore defaults", command=reset_params).pack(side="right")
    ttk.Button(buttons, text="Refresh", command=refresh).pack(side="right", padx=(0, 8))

    refresh()
    root.mainloop()


def main():
    parser = argparse.ArgumentParser(description="Inject the shuibo ripple effect into HTML pages.")
    parser.add_argument("--cli", metavar="FILE", help="process one HTML file from the command line")
    parser.add_argument("--bg", choices=("builtin",), help="force the builtin background at runtime")
    parser.add_argument("--set", action="append", metavar="KEY=VALUE",
                        help="override a ripple parameter, e.g. --set speed=3 (repeatable)")
    parser.add_argument("--reset-defaults", action="store_true",
                        help="restore factory ripple parameters and exit")
    parser.add_argument("--remove", action="store_true", help="remove the injection instead")
    args = parser.parse_args()

    if args.reset_defaults:
        try:
            save_params(dict(PARAM_DEFAULTS))
            print("Ripple parameters restored to defaults.")
        except InjectError as exc:
            print("[REFUSED] %s" % exc)
            sys.exit(1)
        return

    if args.cli:
        run_cli(args)
        return

    if args.set:
        # No file given: persist the parameters for future injections.
        try:
            params = load_params()
            params.update({k: PARAM_RANGES[k][2](v)
                           for k, v in parse_set_items(args.set).items()})
            validate_params(params)
            save_params(params)
            print("Parameters saved: %s" % json.dumps(params, sort_keys=True))
        except InjectError as exc:
            print("[REFUSED] %s" % exc)
            sys.exit(1)
        return

    run_gui()


if __name__ == "__main__":
    main()
