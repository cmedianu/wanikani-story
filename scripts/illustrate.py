#!/usr/bin/env python3
"""Render one chapter illustration from a prompt file plus reference images.

Stdlib only. Three backends, resolved free-first unless --backend is given:

  codex       the user's logged-in Codex CLI and its built-in image tool
              (no key, no per-image charge; refs attach via `codex exec -i`)
  grok        the user's logged-in Grok CLI headless mode (`grok -p`); refs
              are read by path via its image_edit tool
  openrouter  paid API; key file path in config `image.openrouter_key_path`

Backend invocation mechanics (exec flags, artifact-first recovery from the
CLI's generated-image cache) adapted from Trevin Chow's illo-skill engine
(https://github.com/tmchow/illo-skill, MIT).

Usage:
  scripts/illustrate.py --prompt-file p.txt --out panel.png \
      [--ref cast.png --ref anchor.png] [--backend auto] [--dry-run]

Prints a JSON line {"path": ..., "backend": ...} on success; exits 1 on
failure, 2 on usage error. The written path may get a corrected extension
if the backend returned JPEG bytes for a requested .png.
"""

import argparse
import base64
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

CLI_TIMEOUT = 480
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_OR_MODEL = "google/gemini-2.5-flash-image"


def die(msg, code=1):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(code)


def sniff_ext(data):
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if data[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    return None


def valid_image(path):
    try:
        p = Path(path)
        return p.is_file() and p.stat().st_size > 0 and \
            sniff_ext(p.read_bytes()[:16]) is not None
    except OSError:
        return False


def place(src, out):
    """Copy/rename a produced file to out, fixing the extension to match the
    actual encoding. Returns the final path."""
    src = Path(src)
    data = src.read_bytes()
    ext = sniff_ext(data) or src.suffix
    final = Path(out).with_suffix(ext)
    if src.resolve() != final.resolve():
        final.write_bytes(data)
    return final


# ---------------------------------------------------------------- codex

def codex_available():
    if not shutil.which("codex"):
        return False
    try:
        rc = subprocess.run(["codex", "login", "status"], capture_output=True,
                            timeout=30).returncode
    except (OSError, subprocess.SubprocessError):
        return False
    return rc == 0


def codex_generate(prompt, refs, out):
    out = Path(out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    stdin_prompt = (f"{prompt}\n\nUse your built-in image generation tool to "
                    f"render this, then save the resulting image to {out} "
                    f"(overwrite if it exists). Do not ask for confirmation.")
    cmd = ["codex", "exec", "--json", "--cd", str(out.parent),
           "--sandbox", "workspace-write", "--skip-git-repo-check"]
    for r in refs:
        cmd += ["-i", str(Path(r).resolve())]
    cmd.append("-")
    out.unlink(missing_ok=True)
    gen_dir = Path(os.environ.get("CODEX_HOME")
                   or os.path.expanduser("~/.codex")) / "generated_images"
    pre = set(gen_dir.glob("*/*")) if gen_dir.is_dir() else set()
    started = time.time()
    try:
        subprocess.run(cmd, input=stdin_prompt, capture_output=True,
                       text=True, timeout=CLI_TIMEOUT)
    except subprocess.TimeoutExpired:
        pass  # artifact-first: a valid file is authoritative even after timeout
    except (OSError, subprocess.SubprocessError) as e:
        raise RuntimeError(f"codex exec could not run: {e}")
    if valid_image(out):
        return out
    # fallback: freshest image the tool dropped in codex's shared cache
    fresh = [(f.stat().st_mtime, f) for f in gen_dir.glob("*/*")
             if f not in pre and f.stat().st_mtime >= started - 5
             and valid_image(f)] if gen_dir.is_dir() else []
    if fresh:
        return max(fresh)[1]
    raise RuntimeError("codex produced no retrievable image")


# ----------------------------------------------------------------- grok

def grok_available():
    home = Path(os.environ.get("GROK_HOME") or os.path.expanduser("~/.grok"))
    return bool(shutil.which("grok")) and (home / "auth.json").is_file()


def grok_generate(prompt, refs, out):
    out = Path(out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    if refs:
        ref_list = ", ".join(str(Path(r).resolve()) for r in refs)
        tool = (f"Use your image_edit tool with the reference image(s) at "
                f"{ref_list} to keep the characters on-model, then render")
    else:
        tool = "Use your image_gen tool to render"
    full = (f"{prompt}\n\n{tool} this illustration and save the resulting "
            f"image to {out} (overwrite if it exists). Do not construct the "
            f"image with code (HTML/SVG/Python) — use the image generation "
            f"tool. Do not ask for confirmation.")
    cmd = ["grok", "-p", full, "--always-approve",
           "--sandbox", "workspace", "--cwd", str(out.parent)]
    out.unlink(missing_ok=True)
    started = time.time()
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=CLI_TIMEOUT)
    except subprocess.TimeoutExpired:
        raise RuntimeError("grok timed out before producing an image")
    except (OSError, subprocess.SubprocessError) as e:
        raise RuntimeError(f"grok could not run: {e}")
    if valid_image(out):
        return out
    root = Path(os.environ.get("GROK_HOME")
                or os.path.expanduser("~/.grok")) / "sessions"
    fresh = [(f.stat().st_mtime, f) for f in root.glob("*/*/images/*")
             if f.is_file() and f.stat().st_mtime >= started - 5
             and valid_image(f)] if root.is_dir() else []
    if fresh:
        return max(fresh)[1]
    raise RuntimeError(f"grok produced no retrievable image "
                       f"(exit {proc.returncode})")


# ----------------------------------------------------------- openrouter

def openrouter_generate(prompt, refs, out, key, model):
    content = [{"type": "text", "text": prompt}]
    for r in refs:
        data = Path(r).read_bytes()
        mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
                "webp": "image/webp"}.get(Path(r).suffix.lstrip(".").lower(),
                                          "image/png")
        content.append({"type": "image_url", "image_url": {
            "url": f"data:{mime};base64,{base64.b64encode(data).decode()}"}})
    body = json.dumps({"model": model, "modalities": ["image", "text"],
                       "messages": [{"role": "user", "content": content}]})
    req = urllib.request.Request(
        OPENROUTER_URL, data=body.encode(),
        headers={"Authorization": f"Bearer {key}",
                 "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=CLI_TIMEOUT) as resp:
        payload = json.load(resp)
    try:
        url = payload["choices"][0]["message"]["images"][0]["image_url"]["url"]
    except (KeyError, IndexError, TypeError):
        raise RuntimeError(f"openrouter returned no image "
                           f"(model {model}): {str(payload)[:200]}")
    if not url.startswith("data:"):
        raise RuntimeError("openrouter returned a non-data image URL")
    img = base64.b64decode(url.split(",", 1)[1])
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(img)
    return out


# ------------------------------------------------------------------ main

def load_image_config():
    cfg_path = Path(os.environ.get(
        "WANIKANI_STORY_CONFIG",
        "~/.config/wanikani-story/config.json")).expanduser()
    if cfg_path.exists():
        return json.loads(cfg_path.read_text()).get("image", {})
    return {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompt-file", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--ref", action="append", default=[])
    ap.add_argument("--backend",
                    choices=["auto", "codex", "grok", "openrouter"],
                    default=None)
    ap.add_argument("--model", help="openrouter model id override")
    ap.add_argument("--dry-run", action="store_true",
                    help="print resolved backend + prompt, render nothing")
    args = ap.parse_args()

    prompt = Path(args.prompt_file).read_text().strip()
    for r in args.ref:
        if not valid_image(r):
            die(f"reference is not a readable image: {r}", 2)

    cfg = load_image_config()
    backend = args.backend or cfg.get("backend", "auto")
    key = None
    key_path = cfg.get("openrouter_key_path")
    if key_path and Path(key_path).expanduser().exists():
        key = Path(key_path).expanduser().read_text().strip()
    if backend == "auto":
        backend = ("codex" if codex_available() else
                   "grok" if grok_available() else
                   "openrouter" if key else None)
        if backend is None:
            die("no usable backend: no Codex CLI login, no Grok CLI login, "
                "and no image.openrouter_key_path in config")

    if args.dry_run:
        print(json.dumps({"backend": backend, "refs": args.ref,
                          "prompt": prompt}, ensure_ascii=False))
        return

    try:
        if backend == "codex":
            produced = codex_generate(prompt, args.ref, args.out)
        elif backend == "grok":
            produced = grok_generate(prompt, args.ref, args.out)
        else:
            if not key:
                die("openrouter backend needs image.openrouter_key_path "
                    "in config", 2)
            produced = openrouter_generate(prompt, args.ref, args.out, key,
                                           args.model or cfg.get(
                                               "model", DEFAULT_OR_MODEL))
    except RuntimeError as e:
        die(str(e))

    final = place(produced, args.out)
    print(json.dumps({"path": str(final), "backend": backend}))


if __name__ == "__main__":
    main()
