"""Record a real local app + MCP + SQLite run; no fixture responses or live model."""

import argparse
from io import BytesIO
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

from PIL import Image, ImageDraw, ImageFont
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def font(size):
    for path in (
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ):
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size=size)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--browser", help="Optional Chrome/Chromium executable")
    parser.add_argument("--output", type=Path, default=ROOT / "docs/media")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    with tempfile.TemporaryDirectory(prefix="bankscope-demo-") as temp:
        env = {
            **os.environ,
            "BANK_AGENT_DB": str(Path(temp) / "demo.sqlite"),
            "BANK_AGENT_MODE": "local",
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
                url = "http://127.0.0.1:" + str(port)
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
                with sync_playwright() as p:
                    browser = p.chromium.launch(
                        headless=True, executable_path=args.browser
                    )
                    page = browser.new_page(
                        viewport={"width": 1600, "height": 1120},
                        device_scale_factor=1,
                        locale="en-US",
                    )
                    errors = []
                    external = []
                    observed = []
                    frames = []
                    durations = []
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    page.on(
                        "console",
                        lambda message: (
                            errors.append(message.text)
                            if message.type == "error"
                            else None
                        ),
                    )

                    def local_only(route):
                        if urlparse(route.request.url).hostname != "127.0.0.1":
                            external.append(route.request.url)
                            route.abort()
                        else:
                            route.continue_()

                    page.route("**/*", local_only)

                    def response_received(response):
                        if response.url.endswith("/api/chat"):
                            observed.append(response)

                    page.on("response", response_received)

                    def snap(step, duration=2000):
                        page.wait_for_timeout(300)
                        shot = (
                            Image.open(BytesIO(page.screenshot(animations="disabled")))
                            .convert("RGB")
                            .resize((1200, 840), Image.Resampling.LANCZOS)
                        )
                        frame = Image.new("RGB", (1200, 930), "#122b35")
                        frame.paste(shot, (0, 62))
                        draw = ImageDraw.Draw(frame)
                        draw.text(
                            (23, 12),
                            "BankScope / " + step,
                            font=font(23),
                            fill="#ffffff",
                        )
                        draw.text(
                            (906, 21),
                            "LOCAL DATA / REAL MCP",
                            font=font(15),
                            fill="#a4d6c7",
                        )
                        draw.text(
                            (23, 908),
                            "Actual app recording · Generated SQLite records · Local intent planner · No live bank or model",
                            font=font(14),
                            fill="#aecac3",
                        )
                        frames.append(frame)
                        durations.append(duration)

                    def ask(message, step):
                        prompt = page.locator("#prompt")
                        for n in (len(message) // 2, len(message)):
                            prompt.fill(message[:n])
                            snap(step, 500 if n < len(message) else 1500)
                        count = page.locator(".message.answer").count()
                        prompt.press("Enter")
                        page.wait_for_function(
                            '(n)=>document.querySelectorAll(".message.answer").length>n',
                            arg=count,
                        )
                        page.wait_for_function(
                            '() => !document.querySelector("#send").disabled'
                        )
                        assert page.locator(".chat-error").count() == 0

                    page.goto(url, wait_until="networkidle")
                    page.locator("#bank-table tbody tr").nth(3).wait_for()
                    snap("01 / Explore the relationship overview", 2400)
                    page.screenshot(
                        path=str(args.output / "workspace.png"), full_page=True
                    )
                    ask(
                        "Show the overall bank relationship report for 2026Q3",
                        "02 / Ask for the full relationship report",
                    )
                    snap("02 / Review calculated findings and evidence", 2400)
                    page.locator(".trace summary").last.click()
                    snap("03 / Inspect the actual MCP tool arguments", 2200)
                    page.locator(".trace summary").last.click()
                    ask(
                        "Show the relationship report for Harbor Bank",
                        "04 / Focus the analysis on one bank",
                    )
                    assert page.locator("#bank").input_value() == "harbor"
                    snap("04 / The dashboard follows the bank scope", 2600)
                    ask(
                        "Compare fees for all banks in 2026Q3",
                        "05 / Compare fees across banking partners",
                    )
                    assert "fee_analysis" in page.locator(".trace").last.inner_text()
                    snap("05 / Compare costs using the same quarter", 2600)
                    page.locator("#bank").select_option("all")
                    page.wait_for_function(
                        '() => document.querySelectorAll("#bank-table tbody tr").length===4'
                    )
                    snap("06 / Reconcile the report with the overview", 2200)
                    page.screenshot(
                        path=str(args.output / "analysis.png"), full_page=True
                    )
                    with page.expect_download() as download:
                        page.locator("#export").click()
                    saved = Path(temp) / "report.csv"
                    download.value.save_as(saved)
                    assert "SYNTHETIC,2026Q3,USD" in saved.read_text()
                    page.locator("#evidence summary").click()
                    page.locator("#evidence").scroll_into_view_if_needed()
                    snap("07 / Check provenance and export the report", 2700)
                    assert not errors, errors
                    assert not external, external
                    traces = []
                    for response in observed:
                        events = [
                            json.loads(line[6:])
                            for line in response.text().splitlines()
                            if line.startswith("data: ")
                        ]
                        traces.extend(
                            {
                                "tool": event["tool"],
                                "synthetic": event["data"]["synthetic"],
                            }
                            for event in events
                            if event["type"] == "tool_result"
                        )
                    assert [row["tool"] for row in traces] == [
                        "relationship_report",
                        "relationship_report",
                        "fee_analysis",
                    ]
                    assert all(row["synthetic"] for row in traces)
                    # Per-frame adaptive palettes retain readable accent colors.
                    encoded = [frame.quantize(colors=256) for frame in frames]
                    target = args.output / "bankscope-demo.gif"
                    encoded[0].save(
                        target,
                        save_all=True,
                        append_images=encoded[1:],
                        duration=durations,
                        loop=0,
                        optimize=True,
                        disposal=2,
                    )
                    with Image.open(target) as gif:
                        assert gif.n_frames > 10 and gif.info["loop"] == 0
                        count = gif.n_frames
                    checks = {
                        "mode": "actual local app + stdio MCP + generated SQLite; deterministic planner",
                        "frames": count,
                        "duration_ms": sum(durations),
                        "bytes": target.stat().st_size,
                        "tool_results": traces,
                        "csv_download_verified": True,
                        "browser_errors": errors,
                        "external_requests": external,
                    }
                    (args.output / "capture-checks.json").write_text(
                        json.dumps(checks, indent=2) + chr(10)
                    )
                    print(json.dumps(checks))
                    browser.close()
            finally:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


if __name__ == "__main__":
    main()
