# Record the BankScope walkthrough

The GIF follows an overall report, Harbor Bank analysis and fee comparison, then provenance review and CSV export. The reference enterprise video's question sequence inspired the storyboard; its frames, identifiers, URLs and figures are not reused.

This records the **actual local application**: FastAPI → MCP stdio process → generated SQLite records. No responses are intercepted or mocked. Local mode uses intent rules and calculated summaries; it does not demonstrate live LLM reasoning.

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

The script starts and stops a temporary loopback server and database, forcing local mode. Your regular database stays separate. Non-local browser requests are blocked. Linux may need browser system packages reported by Playwright.

| Output                                           | Purpose                               |
| ------------------------------------------------ | ------------------------------------- |
| [bankscope-demo.gif](media/bankscope-demo.gif)   | Looping real-MCP walkthrough          |
| [workspace.png](media/workspace.png)             | Full-size overview                    |
| [analysis.png](media/analysis.png)               | Fee analysis and overview             |
| [capture-checks.json](media/capture-checks.json) | Tool, CSV, browser and network checks |

The recorder verifies seven MCP tools, the three expected chat results, the dashboard's bank scope, synthetic markers in CSV, and no browser errors or external requests. Separate tests validate arithmetic and the MCP integration.

Frame timing is edited for readability, not a benchmark. Tool duration shown in the UI is measured from actual calls. Model mode is tested with a simulated provider and not used in this recording.
