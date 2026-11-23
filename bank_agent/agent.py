"""Local intent planning or optional user-configured LLM tool calling."""

import asyncio
from contextlib import asynccontextmanager
import json
import os
import re
import sys
import time
from urllib.parse import urlparse

import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from .analytics import DEFAULT_PERIOD, period_bounds
from .data import ROOT, BANKS, database_path


@asynccontextmanager
async def connect_mcp():
    # Explicit environment: no company credentials/configuration forwarded.
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "bank_agent.mcp_server"],
        cwd=str(ROOT),
        env={"BANK_AGENT_DB": str(database_path())},
    )
    async with stdio_client(params) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            yield session


class TreasuryAgent:
    def __init__(self, session, *, mode: str = "local"):
        self.session = session
        self.mode = mode
        self.lock = asyncio.Lock()
        self.tools = {}

    async def initialize(self):
        self.tools = {
            tool.name: tool for tool in (await self.session.list_tools()).tools
        }

    async def call(self, name, arguments):
        if name not in self.tools:
            raise ValueError("Tool is not in the read-only allowlist.")
        started = time.perf_counter()
        async with self.lock:
            result = await self.session.call_tool(name, arguments)
        if result.isError:
            raise ValueError(
                "The requested filters could not be applied. Check the bank and quarter."
            )
        data = result.structuredContent
        if data is None:
            data = json.loads(
                next(item.text for item in result.content if item.type == "text")
            )
        return data, round((time.perf_counter() - started) * 1000)

    async def stream(self, text: str, state: dict):
        # User input can never add a write tool. This check adds a readable response.
        if re.search(
            r"\b(delete|drop|update|insert|modify|execute|transfer|send money)\b|删除|修改|转账|汇款",
            text,
            re.I,
        ):
            yield {
                "type": "answer",
                "text": "This workspace only analyzes synthetic records. It cannot modify accounts or initiate payments.",
            }
            return
        if self.mode == "llm":
            async for event in self._llm_stream(text, state):
                yield event
            return
        lowered = text.lower()
        found = re.search(r"(20\d{2})\s*[- ]?q([1-4])", lowered)
        period = (
            found[1] + "Q" + found[2] if found else state.get("period", DEFAULT_PERIOD)
        )
        period_bounds(period)
        selected = [
            identifier
            for identifier, _ in BANKS
            if re.search(r"\b" + identifier + r"\b", lowered)
        ]
        bank = selected[0] if len(selected) == 1 else state.get("bank", "all")
        if re.search(r"all banks|all bank|overall|entire|所有|整体|全部", lowered):
            bank = "all"
        args = {"period": period, "bank": bank}
        if re.search(r"fee|cost|charge|费用|手续费", lowered):
            tool = "fee_analysis"
        elif re.search(r"credit|utiliz|授信|额度", lowered):
            tool = "credit_exposure"
        elif re.search(r"account|账户", lowered) and not re.search(
            r"balance|余额", lowered
        ):
            tool = "list_accounts"
            args = {
                "bank": bank,
                "status": "dormant"
                if re.search(r"dormant|inactive|休眠", lowered)
                else "all",
            }
        elif re.search(r"payment|outflow|付款|支付", lowered):
            tool = "payment_activity"
        elif re.search(r"debt|invest|loan|投资|债务", lowered):
            tool = "debt_investments"
        elif re.search(r"compare|versus| vs |比较|对比", lowered):
            tool = "compare_banks"
            args = {"period": period, "banks": selected or [b[0] for b in BANKS]}
        elif re.search(
            r"report|relationship|overview|balance|报告|关系|总览|余额", lowered
        ):
            tool = "relationship_report"
        else:
            yield {
                "type": "answer",
                "text": "Try: Show the overall bank relationship report for 2026Q3; compare Alder and Harbor; or analyze fees for all banks. Local mode supports these specific intents.",
            }
            return
        state.update(period=period, bank=bank)
        yield {
            "type": "plan",
            "text": f"Local intent planner → {tool} · {period} · {bank}",
        }
        yield {"type": "tool_start", "tool": tool, "arguments": args}
        data, elapsed = await self.call(tool, args)
        yield {
            "type": "tool_result",
            "tool": tool,
            "data": data,
            "duration_ms": elapsed,
        }
        yield {"type": "answer", "text": summarize(data)}

    async def _llm_stream(self, text, state):
        base = os.environ.get("LLM_BASE_URL", "http://127.0.0.1:11434/v1").rstrip("/")
        model = os.environ.get("LLM_MODEL", "")
        key = os.environ.get("LLM_API_KEY", "")
        parsed = urlparse(base)
        if (
            not model
            or parsed.scheme not in ("http", "https")
            or parsed.username
            or parsed.password
        ):
            raise ValueError(
                "Set LLM_MODEL and a valid LLM_BASE_URL before using LLM mode."
            )
        if parsed.hostname not in ("localhost", "127.0.0.1", "::1") and (
            parsed.scheme != "https" or not key
        ):
            raise ValueError(
                "Remote model endpoints require HTTPS and your own LLM_API_KEY."
            )
        messages = [
            {
                "role": "system",
                "content": "You are BankScope, a read-only analyst for a completely synthetic USD treasury dataset. "
                "Use the supplied tools for every financial fact. Data covers 2025Q1 through 2026Q3; "
                "default to 2026Q3. Banks: Alder, Meridian, Harbor, Summit. Never invent facts or claim live "
                "banking access. Use relationship_report for overall or per-bank reports; fees use fee_analysis. "
                "No write or payment tools exist. Explain the period and scope. Keep replies concise.",
            },
            *state.get("history", [])[-6:],
            {"role": "user", "content": text},
        ]
        tools = [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.inputSchema,
                },
            }
            for t in self.tools.values()
        ]
        yield {"type": "plan", "text": "User-configured model → read-only MCP tools"}
        headers = {"Authorization": f"Bearer {key}"} if key else {}
        async with httpx.AsyncClient(timeout=60, trust_env=False) as client:
            for _ in range(4):
                response = await client.post(
                    base + "/chat/completions",
                    headers=headers,
                    json={
                        "model": model,
                        "messages": messages,
                        "tools": tools,
                        "tool_choice": "auto",
                    },
                )
                if not response.is_success:
                    raise ValueError(
                        f"The configured model returned HTTP {response.status_code}. Check your model settings."
                    )
                message = response.json()["choices"][0]["message"]
                calls = message.get("tool_calls") or []
                if not calls:
                    answer = (
                        message.get("content") or "No answer returned by the model."
                    )
                    state["history"] = [
                        *state.get("history", [])[-4:],
                        {"role": "user", "content": text},
                        {"role": "assistant", "content": answer},
                    ]
                    yield {"type": "answer", "text": answer}
                    return
                if len(calls) > 7:
                    raise ValueError("The model exceeded the per-round tool budget.")
                messages.append(
                    {
                        "role": "assistant",
                        "content": message.get("content"),
                        "tool_calls": calls,
                    }
                )
                for call in calls:
                    name = call["function"]["name"]
                    arguments = json.loads(call["function"]["arguments"])
                    yield {"type": "tool_start", "tool": name, "arguments": arguments}
                    data, elapsed = await self.call(name, arguments)
                    yield {
                        "type": "tool_result",
                        "tool": name,
                        "data": data,
                        "duration_ms": elapsed,
                    }
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call["id"],
                            "content": json.dumps(data),
                        }
                    )
        raise ValueError("Model tool-call budget exhausted; try a narrower question.")


def summarize(data):
    if data["kind"] == "relationship_report":
        return (
            f"{data['period']} · USD · {data['scope']}\n"
            + "\n".join(data["insights"])
            + "\nAll findings are calculated from generated records."
        )
    if data["kind"] == "accounts":
        return f"Found {data['count']} synthetic accounts matching your filters. These DEMO identifiers do not represent real bank accounts."
    if data["kind"] == "fees":
        top = max(data["banks"], key=lambda r: float(r["fee_bps"] or 0))
        return f"{top['bank']} has the highest fee-to-outflow ratio in this selection: {top['fee_bps']} bps. Compare transaction mix before interpreting this as pricing. The dataset does not establish a cause for fee differences."
    if data["kind"] == "credit":
        top = max(data["banks"], key=lambda r: float(r["utilization"] or 0))
        return f"{top['bank']} has the highest utilization in this selection at {top['utilization']}%. Credit figures are quarter-end snapshots, not quarterly sums."
    return f"Computed {data['kind']} for {data['period']} in USD. Values come from the local synthetic database; the table shows the exact tool results."
