#!/usr/bin/env python3
"""The wake word studio on a made-up household (Anna, Piotr, Ola) with a pretend GPU machine.

For trying the studio, its browser tests and the screenshots of the guide - nothing real is read:
no recordings, no Home Assistant (its address answers nothing), a fake training log.

    .venv/bin/python docs/studio_demo.py [--port 8766]      (login: demo / demo)
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "docs"))

from demo_household import Demo, make_household, training_log

from wakeword import elevenlabs, ha_sync
from wakeword.studio.server import make_server
from wakeword.trainer import runner as runner_module

LOGIN = ("demo", "demo")


def fake_repo(root: Path) -> Path:
    """A repository whose train.sh only says what it was asked (no TensorFlow on this computer); the real
    train/models.py lists the kept models (standard library only)."""
    repo = root / "repo"
    (repo / "train").mkdir(parents=True)
    script = repo / "train" / "train.sh"
    script.write_text('#!/usr/bin/env bash\necho "train.sh $*"\n', encoding="utf-8")
    script.chmod(0o755)
    (repo / "train" / "models.py").symlink_to(ROOT / "train" / "models.py")
    return repo


def start_studio(root: Path, demo: Demo | None = None, port: int = 0, host: str = "127.0.0.1"):
    """The studio on a demo household in `root`; (server, base url). The pretend machine reports `demo`."""
    demo = demo or Demo()
    # never the secrets of whoever runs this: the Home Assistant connection and the ElevenLabs key of the demo
    # live in the temporary folder (empty - the studio says "not set")
    ha_sync.CONFIG_FILE = root / "config" / "home_assistant.json"
    elevenlabs.KEY_FILE = root / "config" / "elevenlabs.json"
    os.environ.pop("WAKEWORD_HA_URL", None)
    os.environ.pop("WAKEWORD_HA_TOKEN", None)
    os.environ.pop("WAKEWORD_ESPHOME", None)  # make exports the real ESPHome folder - never in the pictures
    runner_module.LocalRunner.status = lambda runner, offset: demo.status(runner, offset)
    home = make_household(root)
    server = make_server(home, LOGIN, host=host, port=port, verbose=False, secret_folder=root / "secret", repo=fake_repo(root))
    server.demo = demo
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def set_log(server, text: str, running: bool) -> None:
    """The pretend machine's training log (what the live view and the models read)."""
    studio = server.studio
    with studio.lock:
        studio.log.clear()
        studio._polled = 0.0
    server.demo.log, server.demo.running = text, running
    studio.started_at = time.time() - 42 * 60 if running else None
    studio.poll(force=True)


SHOTS = ROOT / "docs" / "assets" / "screens"
# the studio's screenshots in the guide (docs/<lang>/11-studio.md, 13-studio-step-by-step.md): name → node of the tree
STUDIO_SHOTS = {"studio-overview": "overview", "studio-word": "word/hej_jarvis", "studio-live": "train-live",
                "studio-save": "people",
                # the step-by-step guide (docs/<lang>/13-studio-step-by-step.md)
                "studio-words": "words", "studio-devices": "devices", "studio-recordings": "rec/hej_jarvis",
                "studio-data": "train-data", "studio-run": "train-run", "studio-models": "models/hej_jarvis",
                "studio-export": "export", "studio-ha": "ha", "studio-gear": "overview"}


def shoot(base: str, server, languages=("pl", "en")) -> list[Path]:
    """The studio's pictures for the guide, in the dark look, at the size of a laptop screen."""
    from playwright.sync_api import sync_playwright

    saved = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome")
        for lang in languages:
            context = browser.new_context(viewport={"width": 1500, "height": 920}, color_scheme="dark")
            context.add_init_script(f"localStorage.setItem('wakeword-studio-lang', '{lang}');")
            page = context.new_page()
            page.goto(f"{base}/login")
            page.fill("input[name=user]", LOGIN[0])
            page.fill("input[name=password]", LOGIN[1])
            page.click("button[type=submit]")
            page.wait_for_selector(".view-host > *")
            for name, node in STUDIO_SHOTS.items():
                page.evaluate(f"location.hash = '#/{node}'")
                page.wait_for_selector(f"[data-view='{node}'] > *")
                if name == "studio-save":  # a person added: the save dialog with its changes
                    page.fill("[data-new-person]", "tomek")
                    page.click("[data-add-person]")
                    page.click("[data-save]")
                    page.wait_for_selector("[data-dialog='save'] [data-diff]")
                if name == "studio-models":  # the kept runs, compared
                    page.click("#load-models")
                    page.wait_for_selector("#models table, #models .model-row, #models tr", timeout=10000)
                if name == "studio-gear":  # ⚙: the pop-up with the look and the language
                    page.click("[data-settings]")
                    page.wait_for_selector("[data-gear-pop]")
                page.wait_for_timeout(600)
                out = SHOTS / lang / f"{name}.png"
                out.parent.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(out))
                saved.append(out)
                if name == "studio-gear":
                    page.keyboard.press("Escape")
                if name == "studio-save":
                    page.keyboard.press("Escape")
                    page.click("[data-discard]")
                    page.click("dialog.ask [data-ask-ok]")
            context.close()
        browser.close()
    return saved


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--host", default="127.0.0.1",
                        help="the address to listen on (0.0.0.0 inside the demo container, make demo)")
    parser.add_argument("--shots", action="store_true", help="make the guide's screenshots of the studio and stop")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        if args.shots:
            server, base = start_studio(Path(tmp))
            set_log(server, training_log(time.time() - 42 * 60, 12000, finished=False), running=True)
            for path in shoot(base, server):
                print(path.relative_to(ROOT))
            server.shutdown()
            return
        server, base = start_studio(Path(tmp), port=args.port, host=args.host)
        base = f"http://localhost:{args.port}"  # what the browser on this computer opens (also from the container)
        set_log(server, training_log(time.time() - 42 * 60, 9000, finished=False), running=True)
        print(f"Demo studio: {base}/  (login {LOGIN[0]} / {LOGIN[1]}) - Ctrl+C stops it", flush=True)
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            pass
        finally:
            server.shutdown()


if __name__ == "__main__":
    main()
