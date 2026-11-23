"""Read-only, parameterized queries and reproducible financial arithmetic."""

from calendar import monthrange
from contextlib import closing
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
import re

from .data import BANKS, START, END, connect

DEFAULT_PERIOD = "2026Q3"


def period_bounds(period: str) -> tuple[str, str]:
    if not re.fullmatch(r"20\d{2}Q[1-4]", period):
        raise ValueError("Use a quarter such as 2026Q3.")
    year, quarter = int(period[:4]), int(period[-1])
    month = quarter * 3
    start = date(year, month - 2, 1)
    end = date(year, month, monthrange(year, month)[1])
    if start < START or end > END:
        raise ValueError("Synthetic data covers 2025Q1 through 2026Q3.")
    return str(start), str(end)


def bank_scope(bank: str) -> str:
    key = bank.strip().lower()
    if key == "all":
        return key
    for identifier, name in BANKS:
        if key in (identifier, name.lower()):
            return identifier
    raise ValueError("Unknown bank. Choose Alder, Meridian, Harbor or Summit.")


def dollars(cents) -> str:
    return str((Decimal(cents) / 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def percentage(numerator, denominator) -> str | None:
    if not denominator:
        return None
    return str(
        (Decimal(numerator) * 100 / Decimal(denominator)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
    )


def _metrics(period: str, bank: str) -> dict:
    start, end = period_bounds(period)
    bank = bank_scope(bank)
    rows = {
        identifier: {
            "id": identifier,
            "bank": name,
            "accounts": 0,
            "average_balance_cents": Decimal(0),
            "payments_cents": 0,
            "payment_count": 0,
            "fees_cents": 0,
            "credit_limit_cents": 0,
            "credit_used_cents": 0,
            "debt_cents": 0,
            "investment_cents": 0,
        }
        for identifier, name in BANKS
        if bank in ("all", identifier)
    }
    parameters = (start, end, bank, bank)
    with closing(connect()) as con:
        for row in con.execute(
            "SELECT bank_id,COUNT(*) AS n FROM accounts WHERE (?='all' OR bank_id=?) GROUP BY bank_id",
            (bank, bank),
        ):
            rows[row["bank_id"]]["accounts"] = row["n"]
        # Sum per-account calendar-day averages, not a sum of daily snapshots.
        for row in con.execute(
            """SELECT a.bank_id,b.account_id,SUM(b.amount_cents) AS total,COUNT(*) AS days
            FROM balances b JOIN accounts a ON a.id=b.account_id
            WHERE b.day BETWEEN ? AND ? AND (?='all' OR a.bank_id=?) GROUP BY a.bank_id,b.account_id""",
            parameters,
        ):
            rows[row["bank_id"]]["average_balance_cents"] += (
                Decimal(row["total"]) / row["days"]
            )
        for table, extra, target in (
            ("payments", " AND p.direction='outflow'", "payments_cents"),
            ("fees", "", "fees_cents"),
        ):
            # Identifiers are fixed code constants; user values are SQL parameters.
            query = f"""SELECT a.bank_id,SUM(p.amount_cents) AS total,COUNT(*) AS n
                FROM {table} p JOIN accounts a ON a.id=p.account_id
                WHERE p.day BETWEEN ? AND ? AND (?='all' OR a.bank_id=?) {extra} GROUP BY a.bank_id"""
            for row in con.execute(query, parameters):
                rows[row["bank_id"]][target] = row["total"]
                if table == "payments":
                    rows[row["bank_id"]]["payment_count"] = row["n"]
        for row in con.execute(
            "SELECT * FROM credit_lines WHERE day=? AND (?='all' OR bank_id=?)",
            (end, bank, bank),
        ):
            rows[row["bank_id"]]["credit_limit_cents"] = row["limit_cents"]
            rows[row["bank_id"]]["credit_used_cents"] = row["used_cents"]
        for row in con.execute(
            "SELECT * FROM positions WHERE day=? AND (?='all' OR bank_id=?)",
            (end, bank, bank),
        ):
            rows[row["bank_id"]][row["kind"] + "_cents"] = row["amount_cents"]
        trend = [
            dict(row)
            for row in con.execute(
                """SELECT substr(b.day,1,7) AS month,
            SUM(b.amount_cents) AS total,COUNT(DISTINCT b.day) AS days
            FROM balances b JOIN accounts a ON a.id=b.account_id
            WHERE b.day BETWEEN ? AND ? AND (?='all' OR a.bank_id=?) GROUP BY month ORDER BY month""",
                parameters,
            )
        ]
    for row in rows.values():
        row["average_balance_cents"] = int(
            row["average_balance_cents"].quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        )
    return {
        "rows": list(rows.values()),
        "trend": [
            {
                "month": r["month"],
                "average_balance": dollars(Decimal(r["total"]) / r["days"]),
            }
            for r in trend
        ],
    }


def relationship_report(period: str = DEFAULT_PERIOD, bank: str = "all") -> dict:
    """Quarterly balances, payment outflows, fees and end-of-quarter exposures in USD."""
    bank = bank_scope(bank)
    start, end = period_bounds(period)
    metrics = _metrics(period, bank)
    money_keys = [k for k in metrics["rows"][0] if k.endswith("_cents")]
    totals = {key: sum(row[key] for row in metrics["rows"]) for key in money_keys}
    rendered = []
    for row in metrics["rows"]:
        rendered.append(
            {
                "id": row["id"],
                "bank": row["bank"],
                "accounts": row["accounts"],
                "payment_count": row["payment_count"],
                **{key.removesuffix("_cents"): dollars(row[key]) for key in money_keys},
                "balance_share": percentage(
                    row["average_balance_cents"], totals["average_balance_cents"]
                ),
                "utilization": percentage(
                    row["credit_used_cents"], row["credit_limit_cents"]
                ),
                "fee_bps": percentage(row["fees_cents"] * 100, row["payments_cents"]),
            }
        )
    summary = {
        key.removesuffix("_cents"): dollars(value) for key, value in totals.items()
    }
    summary.update(
        accounts=sum(r["accounts"] for r in rendered),
        utilization=percentage(
            totals["credit_used_cents"], totals["credit_limit_cents"]
        ),
        payment_count=sum(r["payment_count"] for r in rendered),
    )
    quarter, year = int(period[-1]), int(period[:4])
    previous = (
        f"{year if quarter > 1 else year - 1}Q{quarter - 1 if quarter > 1 else 4}"
    )
    try:
        prior = _metrics(previous, bank)
    except ValueError:
        prior = None
    prior_total = (
        sum(r["average_balance_cents"] for r in prior["rows"]) if prior else None
    )
    summary["balance_change_pct"] = (
        percentage(totals["average_balance_cents"] - prior_total, prior_total)
        if prior_total
        else None
    )
    ranked = sorted(rendered, key=lambda r: Decimal(r["average_balance"]), reverse=True)
    highest_fee = max(rendered, key=lambda r: Decimal(r["fee_bps"] or 0))
    highest_use = max(rendered, key=lambda r: Decimal(r["utilization"] or 0))
    insights = [
        f"{ranked[0]['bank']} holds {ranked[0]['balance_share']}% of this scope's average cash balance.",
        f"{highest_fee['bank']} has the highest fee-to-outflow ratio in this scope: {highest_fee['fee_bps']} bps.",
        f"{highest_use['bank']} uses {highest_use['utilization']}% of its quarter-end credit limit.",
    ]
    return {
        "kind": "relationship_report",
        "synthetic": True,
        "currency": "USD",
        "period": period,
        "scope": bank,
        "start": start,
        "end": end,
        "summary": summary,
        "banks": ranked,
        "trend": metrics["trend"],
        "insights": insights,
        "evidence": {
            "source": "Generated SQLite dataset · seed 2685",
            "balance": "Sum of per-account daily averages; includes calendar days and zero balances",
            "payments": "Gross outflows in the selected quarter; never netted against inflows",
            "fees": "Quarterly service and transaction fees",
            "credit_and_positions": f"Snapshot at {end}; debt and investments shown separately",
            "comparison": previous if prior else "No prior quarter in dataset",
            "rounding": "Integer USD cents; Decimal averages; displayed bank totals reconcile to summary",
        },
    }


def compare_banks(period: str = DEFAULT_PERIOD, banks: list[str] | None = None) -> dict:
    """Compare two or more fictional banks using the same period and currency."""
    chosen = list(
        dict.fromkeys(bank_scope(b) for b in (banks or [b[0] for b in BANKS]))
    )
    if "all" in chosen or len(chosen) < 2:
        raise ValueError("Select at least two distinct named banks.")
    report = relationship_report(period)
    return {
        "kind": "comparison",
        "synthetic": True,
        "period": period,
        "currency": "USD",
        "banks": [r for r in report["banks"] if r["id"] in chosen],
        "evidence": {
            **report["evidence"],
            "balance_share": "Each bank's share of ALL four banks; not reweighted to the selection",
        },
    }


def list_accounts(bank: str = "all", status: str = "all", country: str = "all") -> dict:
    """List the synthetic account registry; IDs are demo labels, not real bank numbers."""
    bank = bank_scope(bank)
    if status not in ("all", "active", "dormant") or country not in (
        "all",
        "US",
        "DE",
        "GB",
        "SG",
    ):
        raise ValueError("Unsupported account status or country.")
    with closing(connect()) as con:
        rows = [
            dict(r)
            for r in con.execute(
                """SELECT a.id,b.name AS bank,a.country,a.company,a.status,a.currency
          FROM accounts a JOIN banks b ON b.id=a.bank_id
          WHERE (?='all' OR a.bank_id=?) AND (?='all' OR a.status=?) AND (?='all' OR a.country=?) ORDER BY a.id""",
                (bank, bank, status, status, country, country),
            )
        ]
    return {"kind": "accounts", "synthetic": True, "count": len(rows), "accounts": rows}


def metric_report(kind: str, period: str, bank: str) -> dict:
    fields = {
        "fees": ["fees", "payments", "fee_bps"],
        "payments": ["payments", "payment_count"],
        "credit": ["credit_limit", "credit_used", "utilization"],
        "positions": ["debt", "investment"],
    }[kind]
    report = relationship_report(period, bank)
    return {
        "kind": kind,
        "synthetic": True,
        "period": period,
        "currency": "USD",
        "scope": bank,
        "banks": [
            {key: r[key] for key in ["id", "bank", *fields]} for r in report["banks"]
        ],
        "evidence": report["evidence"],
    }
