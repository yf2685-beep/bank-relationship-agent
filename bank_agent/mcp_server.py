"""Actual MCP stdio service exposing seven read-only treasury tools."""

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from . import analytics as a

mcp = FastMCP("BankScope synthetic treasury")
READ_ONLY = ToolAnnotations(
    readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False
)

mcp.tool(annotations=READ_ONLY)(a.relationship_report)
mcp.tool(annotations=READ_ONLY)(a.compare_banks)
mcp.tool(annotations=READ_ONLY)(a.list_accounts)


@mcp.tool(annotations=READ_ONLY)
def fee_analysis(period: str = a.DEFAULT_PERIOD, bank: str = "all") -> dict:
    """Compare service fees and fee-to-payment-outflow ratios, in basis points."""
    return a.metric_report("fees", period, bank)


@mcp.tool(annotations=READ_ONLY)
def payment_activity(period: str = a.DEFAULT_PERIOD, bank: str = "all") -> dict:
    """Total gross outgoing payments and transaction counts for a quarter."""
    return a.metric_report("payments", period, bank)


@mcp.tool(annotations=READ_ONLY)
def credit_exposure(period: str = a.DEFAULT_PERIOD, bank: str = "all") -> dict:
    """Quarter-end credit limits, utilized amounts and utilization percentages."""
    return a.metric_report("credit", period, bank)


@mcp.tool(annotations=READ_ONLY)
def debt_investments(period: str = a.DEFAULT_PERIOD, bank: str = "all") -> dict:
    """Quarter-end debt and investment positions, reported separately."""
    return a.metric_report("positions", period, bank)


if __name__ == "__main__":
    mcp.run(transport="stdio")
