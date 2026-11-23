"""Record the real chat UI, MCP and generated SQLite; never mock report responses."""

import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlparse
from urllib.request import urlopen

import imageio_ffmpeg
from PIL import Image
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]


class Recorder:
    """Sample actual browser frames; hold readable states and capture motion at 8 fps."""

    def __init__(self, page, directory):
        self.page, self.directory = page, directory
        self.frames = []
        self.scenes = []

    def frame(self, duration=125):
        path = self.directory / (str(len(self.frames)).zfill(4) + ".png")
        self.page.screenshot(path=str(path), caret="initial")
        self.frames.append((path, duration))

    def hold(self, duration):
        self.frame(duration)

    def scene(self, label):
        self.scenes.append({"at_ms": sum(d for _, d in self.frames), "label": label})

    def ask(self, message, response_duration):
        self.scene(message)
        prompt = self.page.locator("#prompt")
        prompt.focus()
        # Real keyboard events; no replacement of application data or SSE responses.
        for start in range(0, len(message), 3):
            prompt.press_sequentially(message[start : start + 3])
            self.frame()
        self.hold(450)
        prompt.press("Enter")
        response_start = len(self.frames)
        deadline = time.monotonic() + 30
        while True:
            self.frame()
            turn = self.page.locator(".turn").last
            if turn.get_attribute("data-complete") == "true":
                assert turn.get_attribute("data-success") == "true", turn.inner_text()
                break
            if time.monotonic() > deadline:
                raise TimeoutError("The actual MCP report did not finish")
            self.page.wait_for_timeout(80)
        assert self.page.locator(".chat-error").count() == 0
        # Retain the published storyboard timing even when high-density screenshots
        # take longer to capture. This edits presentation time, never MCP responses.
        count = len(self.frames) - response_start
        duration, remainder = divmod(response_duration, count)
        for i in range(count):
            path, _ = self.frames[response_start + i]
            self.frames[response_start + i] = (path, duration + (i < remainder))

    def scroll_to(self, selector, duration=1250):
        position = self.page.locator(selector).last.evaluate(
            """item => {
                const c = document.querySelector('#conversation');
                return {start: c.scrollTop, end: Math.max(0, Math.min(
                    c.scrollHeight - c.clientHeight,
                    c.scrollTop + item.getBoundingClientRect().top
                    - c.getBoundingClientRect().top - 18))};
            }"""
        )
        steps = max(1, duration // 125)
        for i in range(1, steps + 1):
            t = i / steps
            eased = t * t * (3 - 2 * t)
            value = position["start"] + (position["end"] - position["start"]) * eased
            self.page.locator("#conversation").evaluate(
                "(c, y) => c.scrollTop = y", value
            )
            self.frame()

    def encode(self, output):
        # A shared palette and changed-rectangle encoding keep the GIF small and stable.
        playlist = self.directory / "frames.txt"
        playlist.write_text(
            "".join(
                "file '" + p.name + "'\nduration " + str(d / 1000) + "\n"
                for p, d in self.frames
            )
            + "file '"
            + self.frames[-1][0].name
            + "'\n"
        )
        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        source = ["-f", "concat", "-safe", "0", "-i", str(playlist)]

        def run(arguments):
            subprocess.run([ffmpeg, "-y", "-loglevel", "error", *arguments], check=True)

        palette = self.directory / "palette.png"
        # Keep the native 2x browser pixels: no shrinking or synthetic upscaling.
        scaling = "fps=8"
        run(
            [
                *source,
                "-vf",
                scaling + ",palettegen=stats_mode=diff",
                "-frames:v",
                "1",
                str(palette),
            ]
        )
        target = output / "bankscope-demo.gif"
        run(
            [
                *source,
                "-i",
                str(palette),
                "-filter_complex",
                "[0:v]"
                + scaling
                + "[v];[v][1:v]paletteuse=dither=none:diff_mode=rectangle",
                "-loop",
                "0",
                "-gifflags",
                "+transdiff",
                str(target),
            ]
        )
        video = output / "bankscope-demo.mp4"
        run(
            [
                *source,
                "-vf",
                "fps=24",
                "-c:v",
                "libx264",
                "-preset",
                "medium",
                "-crf",
                "20",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                str(video),
            ]
        )
        with Image.open(target) as gif:
            count, duration = gif.n_frames, 0
            dimensions = list(gif.size)
            assert count > 80 and gif.info["loop"] == 0
            for i in range(count):
                gif.seek(i)
                duration += gif.info["duration"]
        return {
            "frames": count,
            "duration_ms": duration,
            "bytes": target.stat().st_size,
            "mp4_bytes": video.stat().st_size,
            "viewport_css": [1440, 960],
            "device_scale_factor": 2,
            "gif_size_px": dimensions,
            "gif_dither": "none",
            "scenes": self.scenes,
        }


def record(url, args, temp):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, executable_path=args.browser)
        context = browser.new_context(
            viewport={"width": 1440, "height": 960},
            device_scale_factor=2,
            locale="en-US",
        )
        errors, external, observed = [], [], []
        context.on("weberror", lambda error: errors.append(str(error.error)))

        def local_only(route):
            if urlparse(route.request.url).hostname != "127.0.0.1":
                external.append(route.request.url)
                route.abort()
            else:
                route.continue_()

        context.route("**/*", local_only)
        page = context.new_page()
        page.on(
            "console", lambda m: errors.append(m.text) if m.type == "error" else None
        )
        page.on(
            "response",
            lambda r: observed.append(r) if r.url.endswith("/api/chat") else None,
        )
        frames = Path(temp) / "frames"
        frames.mkdir()
        rec = Recorder(page, frames)
        page.goto(url, wait_until="networkidle")
        rec.scene("Welcome to the cash and treasury assistant")
        rec.hold(1600)
        page.screenshot(path=str(args.output / "conversation.png"))
        rec.ask("Show the overall bank relationship report for 2026Q3", 1375)
        rec.hold(2000)
        overall = page.locator('[data-kind="relationship_report"]').first
        assert overall.get_attribute("data-scope") == "all"
        assert overall.locator('[data-section="accounts"] tbody tr').count() == 4
        page.screenshot(path=str(args.output / "report.png"))
        for name, hold in (
            ("balances", 1900),
            ("payments", 1700),
            ("fees", 2000),
            ("credit", 2400),
        ):
            rec.scene("Read the " + name + " section")
            rec.scroll_to('[data-section="' + name + '"]')
            rec.hold(hold)
        page.screenshot(path=str(args.output / "credit.png"))
        rec.scroll_to('[data-section="followups"]')
        rec.hold(1200)
        rec.ask("Show the relationship report for Harbor Bank", 1375)
        rec.hold(1700)
        harbor = page.locator('[data-kind="relationship_report"]').last
        assert harbor.get_attribute("data-scope") == "harbor"
        rec.scroll_to('[data-scope="harbor"] [data-section="credit"]', 1500)
        rec.hold(2300)
        rec.ask("Why are Harbor Bank fees high?", 875)
        rec.hold(2600)
        rec.ask("Compare bank fees among all bank groups for 2026Q3", 750)
        rec.hold(3200)
        assert page.locator('[data-kind="fees"]').last.locator("tbody tr").count() == 4
        page.screenshot(path=str(args.output / "analysis.png"))
        rec.scene("Inspect the real MCP query")
        page.locator(".tool-trace summary").last.click()
        rec.scroll_to(".tool-trace", 1000)
        rec.hold(1800)

        # Functional checks are separate from the edited visual walkthrough.
        page.locator("#more").click()
        with page.expect_download() as download:
            page.locator("#export").click()
        saved = Path(temp) / "report.csv"
        download.value.save_as(saved)
        csv = saved.read_text()
        assert (
            "SYNTHETIC,2026Q3,USD" in csv
            and "Harbor Bank" in csv
            and "Alder Bank" not in csv
        )
        traces = []
        for response in observed:
            events = [
                json.loads(line[6:])
                for line in response.text().splitlines()
                if line.startswith("data: ")
            ]
            assert not any(e["type"] == "error" for e in events)
            traces.extend(
                {
                    "tool": e["tool"],
                    "synthetic": e["data"]["synthetic"],
                    "scope": e["data"]["scope"],
                }
                for e in events
                if e["type"] == "tool_result"
            )
        assert [(r["tool"], r["scope"]) for r in traces] == [
            ("relationship_report", "all"),
            ("relationship_report", "harbor"),
            ("fee_analysis", "harbor"),
            ("fee_analysis", "all"),
        ]
        assert all(row["synthetic"] for row in traces)
        page.locator("#more").click()
        page.locator("#about").click()
        assert page.locator("#about-dialog").is_visible()
        page.locator("#close-about").click()
        page.locator("#new-chat").click()
        assert (
            page.locator("#welcome").is_visible() and page.locator(".turn").count() == 0
        )
        page.locator("#view-library").click()
        page.locator('#prompt-library [data-prompt="List dormant accounts"]').click()
        page.locator('.turn[data-complete="true"]').wait_for()
        assert page.locator('[data-kind="accounts"] tbody tr').count() == 4
        assert page.locator('.turn[data-success="false"]').count() == 0
        page.locator(".workspace-link").click()
        page.locator("#bank-table tbody tr").nth(3).wait_for()
        page.screenshot(path=str(args.output / "workspace.png"), full_page=True)
        page.locator("#bank").select_option("harbor")
        page.wait_for_function(
            "() => document.querySelectorAll('#bank-table tbody tr').length === 1"
        )

        # A fresh mobile viewport also checks horizontal table scrolling and the composer.
        mobile = context.new_page()
        mobile.set_viewport_size({"width": 375, "height": 812})
        mobile.goto(url, wait_until="networkidle")
        mobile.locator("#prompt").fill("Show overall relationship report")
        mobile.locator("#send").click()
        mobile.locator('.turn[data-complete="true"]').wait_for()
        assert mobile.locator('.turn[data-success="true"]').count() == 1
        assert mobile.evaluate("document.body.scrollWidth === innerWidth")
        composer = mobile.locator("#chat").bounding_box()
        assert composer["y"] + composer["height"] <= 812
        assert not errors, errors
        assert not external, external
        browser.close()
        checks = {
            "mode": "actual local app + stdio MCP + generated SQLite; deterministic planner",
            **rec.encode(args.output),
            "tool_results": traces,
            "csv_download_verified": True,
            "prompt_library_verified": True,
            "new_conversation_verified": True,
            "dashboard_verified": True,
            "mobile_verified": True,
            "browser_errors": errors,
            "external_requests": external,
        }
        (args.output / "capture-checks.json").write_text(
            json.dumps(checks, indent=2) + "\n"
        )
        print(json.dumps(checks, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--browser", help="Optional Chrome/Chromium executable")
    parser.add_argument("--output", type=Path, default=ROOT / "docs/media")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    url = "http://127.0.0.1:" + str(port)
    with tempfile.TemporaryDirectory(prefix="bankscope-demo-") as temp:
        env = {
            **os.environ,
            "BANK_AGENT_DB": str(Path(temp) / "demo.sqlite"),
            "BANK_AGENT_MODE": "local",
            "BANK_AGENT_PUBLIC_URL": url,
        }
        with (Path(temp) / "server.log").open("w") as log:
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "bank_agent.web:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                ],
                cwd=ROOT,
                env=env,
                stdout=log,
                stderr=log,
            )
            try:
                for _ in range(100):
                    if process.poll() is not None:
                        raise RuntimeError((Path(temp) / "server.log").read_text())
                    try:
                        with urlopen(url + "/api/health", timeout=1) as response:
                            assert json.load(response)["mcp_tools"] == 7
                        break
                    except OSError:
                        time.sleep(0.2)
                else:
                    raise RuntimeError("Local app did not start")
                record(url, args, temp)
            finally:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


if __name__ == "__main__":
    main()
