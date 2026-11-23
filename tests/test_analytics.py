from contextlib import closing
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import sqlite3
import pytest
from bank_agent import analytics as a
from bank_agent.data import seed, connect


def test_generator_is_reproducible_and_fully_synthetic(database, tmp_path):
    other = tmp_path / "other.sqlite"
    seed(other)
    assert (
        hashlib.sha256(database.read_bytes()).digest()
        == hashlib.sha256(other.read_bytes()).digest()
    )
    with closing(connect()) as con:
        assert con.execute("PRAGMA foreign_key_check").fetchall() == []
        assert con.execute("SELECT COUNT(*) FROM accounts").fetchone()[0] == 32
        assert con.execute("SELECT COUNT(*) FROM balances").fetchone()[0] == 638 * 32
        assert (
            con.execute(
                "SELECT COUNT(*) FROM accounts WHERE id NOT LIKE 'DEMO-%'"
            ).fetchone()[0]
            == 0
        )
        assert (
            con.execute("SELECT value FROM metadata WHERE key=?", ("provenance",))
            .fetchone()[0]
            .startswith("Entirely synthetic")
        )


@pytest.mark.parametrize("period", ["2025Q1", "2025Q4", "2026Q2", "2026Q3"])
def test_balances_are_daily_averages_and_totals_reconcile(database, period):
    report = a.relationship_report(period)
    start, end = a.period_bounds(period)
    with closing(connect()) as con:
        days = con.execute(
            "SELECT COUNT(DISTINCT day) FROM balances WHERE day BETWEEN ? AND ?",
            (start, end),
        ).fetchone()[0]
        for bank in report["banks"]:
            total = con.execute(
                "SELECT SUM(b.amount_cents) FROM balances b JOIN accounts a ON a.id=b.account_id WHERE a.bank_id=? AND day BETWEEN ? AND ?",
                (bank["id"], start, end),
            ).fetchone()[0]
            cents = (Decimal(total) / days).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP
            )
            assert Decimal(bank["average_balance"]) == cents / 100
    assert sum(Decimal(b["average_balance"]) for b in report["banks"]) == Decimal(
        report["summary"]["average_balance"]
    )
    if period == "2025Q1":
        assert report["summary"]["balance_change_pct"] is None


def test_credit_snapshot_and_gross_outflow_semantics(database):
    report = a.relationship_report("2026Q3", "harbor")
    assert len(report["banks"]) == 1 and report["banks"][0]["balance_share"] == "100.00"
    with closing(connect()) as con:
        limit = con.execute(
            "SELECT limit_cents FROM credit_lines WHERE bank_id='harbor' AND day='2026-09-30'"
        ).fetchone()[0]
        outflow = con.execute(
            "SELECT SUM(p.amount_cents) FROM payments p JOIN accounts a ON a.id=p.account_id WHERE a.bank_id='harbor' AND p.direction='outflow' AND p.day BETWEEN '2026-07-01' AND '2026-09-30'"
        ).fetchone()[0]
    assert Decimal(report["summary"]["credit_limit"]) * 100 == limit
    assert Decimal(report["summary"]["payments"]) * 100 == outflow
    assert (
        Decimal(report["summary"]["debt"]) > 0
        and Decimal(report["summary"]["investment"]) > 0
    )


@pytest.mark.parametrize("bank", ["all", "harbor"])
@pytest.mark.parametrize(
    "period,previous", [("2026Q3", "2026Q2"), ("2026Q1", "2025Q4")]
)
def test_comparison_uses_previous_quarter_and_same_bank_scope(
    database, bank, period, previous
):
    comparison = a.relationship_report(period, bank)["comparison"]
    prior_report = a.relationship_report(previous, bank)
    assert comparison["period"] == previous
    assert comparison["basis"] == "quarter-over-quarter"
    prior_rows = {row["id"]: row for row in prior_report["banks"]}
    assert {row["id"] for row in comparison["banks"]} == set(prior_rows)
    for key, value in comparison["summary"].items():
        assert value == prior_report["summary"][key]
        assert sum(Decimal(row[key]) for row in comparison["banks"]) == Decimal(value)
        for row in comparison["banks"]:
            assert row[key] == prior_rows[row["id"]][key]
    assert a.relationship_report("2025Q1", bank)["comparison"] is None


@pytest.mark.parametrize(
    "bank", ["' OR 1=1 --", "unknown", "all; DROP TABLE accounts;"]
)
def test_invalid_scope_cannot_become_sql(database, bank):
    with pytest.raises(ValueError):
        a.relationship_report(bank=bank)
    assert a.list_accounts()["count"] == 32


@pytest.mark.parametrize(
    "period", ["2026Q4", "2024Q1", "2026Q9", "last year", "2026Q3' --"]
)
def test_unsupported_periods_fail_explicitly(database, period):
    with pytest.raises(ValueError):
        a.relationship_report(period)


def test_runtime_connection_rejects_writes(database):
    with closing(connect()) as con:
        with pytest.raises(sqlite3.OperationalError):
            con.execute("DELETE FROM accounts")


def test_account_filter_and_comparison_scope(database):
    assert a.list_accounts(status="dormant")["count"] == 4
    assert a.list_accounts(bank="Alder Bank", country="US")["count"] == 2
    comparison = a.compare_banks(banks=["Alder", "Harbor"])
    assert {row["id"] for row in comparison["banks"]} == {"alder", "harbor"}
    assert sum(Decimal(row["balance_share"]) for row in comparison["banks"]) < 100
