"""Generate fictional treasury records; never import an external dataset."""

from __future__ import annotations

import argparse
from contextlib import closing
from datetime import date, timedelta
import os
from pathlib import Path
import random
import sqlite3

ROOT = Path(__file__).resolve().parents[1]
START = date(2025, 1, 1)
END = date(2026, 9, 30)
BANKS = [
    ("alder", "Alder Bank"),
    ("meridian", "Meridian Bank"),
    ("harbor", "Harbor Bank"),
    ("summit", "Summit Bank"),
]
COUNTRIES = [
    ("US", "United States"),
    ("DE", "Germany"),
    ("GB", "United Kingdom"),
    ("SG", "Singapore"),
]

SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE banks (id TEXT PRIMARY KEY, name TEXT NOT NULL);
CREATE TABLE accounts (id TEXT PRIMARY KEY, bank_id TEXT REFERENCES banks(id),
 country TEXT NOT NULL, company TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('active','dormant')),
 currency TEXT NOT NULL CHECK(currency='USD'));
CREATE TABLE balances (account_id TEXT REFERENCES accounts(id), day TEXT NOT NULL,
 amount_cents INTEGER NOT NULL CHECK(amount_cents>=0), PRIMARY KEY(account_id,day));
CREATE TABLE payments (id INTEGER PRIMARY KEY, account_id TEXT REFERENCES accounts(id),
 day TEXT NOT NULL, direction TEXT NOT NULL CHECK(direction IN ('inflow','outflow')),
 amount_cents INTEGER NOT NULL CHECK(amount_cents>0));
CREATE TABLE fees (id INTEGER PRIMARY KEY, account_id TEXT REFERENCES accounts(id),
 day TEXT NOT NULL, category TEXT NOT NULL, amount_cents INTEGER NOT NULL CHECK(amount_cents>=0));
CREATE TABLE credit_lines (bank_id TEXT REFERENCES banks(id), day TEXT NOT NULL,
 limit_cents INTEGER NOT NULL CHECK(limit_cents>0), used_cents INTEGER NOT NULL CHECK(used_cents>=0 AND used_cents<=limit_cents),
 PRIMARY KEY(bank_id,day));
CREATE TABLE positions (bank_id TEXT REFERENCES banks(id), day TEXT NOT NULL,
 kind TEXT NOT NULL CHECK(kind IN ('debt','investment')), amount_cents INTEGER NOT NULL CHECK(amount_cents>=0),
 PRIMARY KEY(bank_id,day,kind));
CREATE INDEX payments_period ON payments(day,account_id);
CREATE INDEX fees_period ON fees(day,account_id);
CREATE INDEX balances_period ON balances(day,account_id);
"""


def database_path() -> Path:
    return Path(
        os.environ.get("BANK_AGENT_DB", ROOT / "data/treasury.sqlite")
    ).resolve()


def connect(path: Path | None = None) -> sqlite3.Connection:
    path = path or database_path()
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    return connection


def seed(path: Path | None = None, *, reset: bool = False) -> dict:
    path = path or database_path()
    if path.exists() and not reset:
        with closing(connect(path)) as con:
            meta = dict(con.execute("SELECT key,value FROM metadata").fetchall())
            if meta.get("generator") != "bankscope-v1":
                raise ValueError(
                    "Unexpected database. Choose a new BANK_AGENT_DB path."
                )
            return meta
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.unlink(missing_ok=True)
    rng = random.Random(2685)
    con = sqlite3.connect(temporary)
    try:
        con.executescript(SCHEMA)
        metadata = {
            "generator": "bankscope-v1",
            "seed": "2685",
            "provenance": "Entirely synthetic; no imported records",
            "currency": "USD",
            "start": str(START),
            "end": str(END),
        }
        con.executemany("INSERT INTO metadata VALUES (?,?)", metadata.items())
        con.executemany("INSERT INTO banks VALUES (?,?)", BANKS)
        for index, (bank, _) in enumerate(BANKS):
            for country_index, (country, _) in enumerate(COUNTRIES):
                for number in range(2):
                    identifier = f"DEMO-{bank.upper()}-{country}-{number + 1:02d}"
                    status = (
                        "dormant"
                        if number == 1 and country_index == index
                        else "active"
                    )
                    con.execute(
                        "INSERT INTO accounts VALUES (?,?,?,?,?,?)",
                        (identifier, bank, country, f"DemoCo {country}", status, "USD"),
                    )
                    day = START
                    while day <= END:
                        drift = (day - START).days * 1300
                        base = (6 - index) * 45_000_000 + country_index * 8_000_000
                        amount = base + drift + rng.randint(-12_000_000, 12_000_000)
                        con.execute(
                            "INSERT INTO balances VALUES (?,?,?)",
                            (identifier, str(day), amount if status == "active" else 0),
                        )
                        if status == "active" and day.day in (3, 8, 13, 18, 23, 28):
                            for direction in ("inflow", "outflow"):
                                payment = rng.randint(5_000_000, 45_000_000) * (
                                    5 - index
                                )
                                con.execute(
                                    "INSERT INTO payments(account_id,day,direction,amount_cents) VALUES (?,?,?,?)",
                                    (identifier, str(day), direction, payment),
                                )
                        if day.day == 28 and status == "active":
                            con.execute(
                                "INSERT INTO fees(account_id,day,category,amount_cents) VALUES (?,?,?,?)",
                                (
                                    identifier,
                                    str(day),
                                    "Service & transaction fees",
                                    rng.randint(20_000, 70_000) * (index + 1),
                                ),
                            )
                        day += timedelta(days=1)
            for year in (2025, 2026):
                for month, last in ((3, 31), (6, 30), (9, 30), (12, 31)):
                    snapshot = date(year, month, last)
                    if snapshot > END:
                        continue
                    limit = (6 - index) * 900_000_000
                    utilization = [36, 54, 79, 48][index] + rng.randint(-3, 3)
                    con.execute(
                        "INSERT INTO credit_lines VALUES (?,?,?,?)",
                        (bank, str(snapshot), limit, limit * utilization // 100),
                    )
                    for kind, multiplier in (
                        ("debt", 120_000_000),
                        ("investment", 85_000_000),
                    ):
                        con.execute(
                            "INSERT INTO positions VALUES (?,?,?,?)",
                            (
                                bank,
                                str(snapshot),
                                kind,
                                (index + 1) * multiplier + rng.randint(0, 25_000_000),
                            ),
                        )
        con.commit()
    finally:
        con.close()
    temporary.replace(path)
    return metadata


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reset", action="store_true", help="Replace the selected synthetic database"
    )
    args = parser.parse_args()
    print(seed(reset=args.reset))
    print(database_path())
