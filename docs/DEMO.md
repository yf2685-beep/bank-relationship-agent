# Record the BankScope walkthrough

The GIF follows a welcome screen, typed report request, multi-section report, continuous scrolling through balances/payments/fees/credit, Harbor Bank detail, a fee follow-up and an all-bank fee comparison. The visual treatment recreates the reference video's centered white conversation, purple composer, grey report background, numbered headings and grid tables. Its frames, identifiers, URLs and figures are not reused.

This records the **actual local application**: FastAPI → MCP stdio process → generated SQLite records. No responses are intercepted or mocked. Local mode uses intent rules and calculated summaries; it does not demonstrate live LLM reasoning. Report sections progressively appear after the tool returns data; that is a frontend presentation effect, not model token streaming.

From the repository root with your virtual environment active:

```bash
python -m pip install -r requirements-dev.txt
python -m playwright install chromium
python scripts/capture_demo.py
```

Or use an existing browser:

```bash
python scripts/capture_demo.py --browser '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
```

The script starts and stops a temporary loopback server and database, forcing local mode. Your regular database stays separate. Non-local browser requests are blocked. Linux may need browser system packages reported by Playwright. The development dependency imageio-ffmpeg provides the encoder on supported platforms; other platforms can point IMAGEIO_FFMPEG_EXE at an installed FFmpeg.

| Output                                           | Purpose                                                  |
| ------------------------------------------------ | -------------------------------------------------------- |
| [bankscope-demo.gif](media/bankscope-demo.gif)   | Looping chat walkthrough, sampled at 8 fps during motion |
| [bankscope-demo.mp4](media/bankscope-demo.mp4)   | Clearer 1440 × 960 video of the same walkthrough         |
| [conversation.png](media/conversation.png)       | Welcome screen and composer                              |
| [report.png](media/report.png)                   | Overall report and account table                         |
| [credit.png](media/credit.png)                   | Credit availability and debt/investments                 |
| [analysis.png](media/analysis.png)               | Cross-bank fee comparison                                |
| [workspace.png](media/workspace.png)             | Preserved dashboard at /dashboard                        |
| [capture-checks.json](media/capture-checks.json) | Tool, CSV, browser and network checks                    |

The recorder verifies discovery of seven MCP tools, the four expected chat results and their bank scopes, the dashboard's bank filter, a fresh conversation, prompt-library account lookup, mobile width and composer placement, synthetic markers and bank scope in CSV, and no browser errors or external requests. CSV and additional interaction checks run after the recorded storyboard. Separate tests validate arithmetic, prior-quarter comparison data, MCP and A2A integration.

Frame timing is edited for readability, not a benchmark. Typing and scrolling use actual browser events and positions; readable states are held longer. A shared GIF palette and changed-frame compression reduce file size. Tool duration shown in the UI is measured from actual calls. Model mode is tested with a simulated provider and not used in this recording. Capture duration, frame count, file sizes and scene timestamps are written to capture-checks.json.
