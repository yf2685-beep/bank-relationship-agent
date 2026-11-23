"""Local web workspace; dashboard and chat both call the MCP subprocess."""

from collections import OrderedDict
from contextlib import asynccontextmanager
import csv
from io import StringIO
import json
import os
from pathlib import Path
import uuid

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from .agent import connect_mcp, TreasuryAgent
from .a2a import install_a2a
from .data import seed

STATIC = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app):
    seed()
    mode = os.environ.get("BANK_AGENT_MODE", "local")
    if mode not in ("local", "llm"):
        raise ValueError("BANK_AGENT_MODE must be local or llm")
    async with connect_mcp() as session:
        app.state.agent = TreasuryAgent(session, mode=mode)
        await app.state.agent.initialize()
        app.state.sessions = OrderedDict()
        try:
            yield
        finally:
            await app.state.a2a_executor.shutdown()


def create_app() -> FastAPI:
    app = FastAPI(title="BankScope — Synthetic Treasury Workspace", lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.middleware("http")
    async def browser_boundaries(request, call_next):
        if (
            request.headers.get("sec-fetch-site") == "cross-site"
            and request.method == "POST"
        ):
            return Response(status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'self'"
        )
        return response

    @app.get("/")
    async def index():
        return FileResponse(STATIC / "index.html")

    @app.get("/api/health")
    async def health():
        return {
            "status": "ok",
            "mode": app.state.agent.mode,
            "synthetic": True,
            "mcp_tools": len(app.state.agent.tools),
        }

    async def report_data(period, bank):
        try:
            data, _ = await app.state.agent.call(
                "relationship_report", {"period": period, "bank": bank}
            )
            return data
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/report")
    async def report(period: str = "2026Q3", bank: str = "all"):
        return await report_data(period, bank)

    @app.get("/api/export.csv")
    async def export(period: str = "2026Q3", bank: str = "all"):
        data = await report_data(period, bank)
        buffer = StringIO()
        rows = [
            {"dataset": "SYNTHETIC", "period": data["period"], "currency": "USD", **row}
            for row in data["banks"]
        ]
        writer = csv.DictWriter(buffer, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
        return Response(
            buffer.getvalue(),
            media_type="text/csv",
            headers={
                "Content-Disposition": "attachment; filename=bankscope-synthetic-report.csv"
            },
        )

    class ChatRequest(BaseModel):
        message: str = Field(min_length=1, max_length=2000)
        session_id: str = Field(
            default_factory=lambda: str(uuid.uuid4()), pattern=r"^[a-zA-Z0-9-]{1,64}$"
        )

    @app.post("/api/chat")
    async def chat(body: ChatRequest):
        sessions = app.state.sessions
        if body.session_id not in sessions:
            if len(sessions) >= 128:
                sessions.popitem(last=False)
            sessions[body.session_id] = {}
        sessions.move_to_end(body.session_id)
        state = sessions[body.session_id]

        async def events():
            try:
                async for event in app.state.agent.stream(body.message, state):
                    yield "data: " + json.dumps(event) + "\n\n"
            except ValueError as exc:
                yield (
                    "data: " + json.dumps({"type": "error", "text": str(exc)}) + "\n\n"
                )
            except Exception:
                yield (
                    "data: "
                    + json.dumps(
                        {
                            "type": "error",
                            "text": "The request could not finish. Check your local server and model configuration.",
                        }
                    )
                    + "\n\n"
                )
            yield (
                "data: "
                + json.dumps({"type": "done", "session_id": body.session_id})
                + "\n\n"
            )

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache"},
        )

    install_a2a(app)
    return app


app = create_app()
