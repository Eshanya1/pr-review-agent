#!/usr/bin/env python3
"""Generates eval/fixtures/<id>/{pr.diff,ground_truth.json} and eval/cassettes/<id>.json.

Each fixture is authored as a small new file (a self-contained PR). Run this
whenever you add or change a fixture in FIXTURES below -- it's the single
source of truth, so the diff, ground truth, and recorded cassette can never
drift out of sync with each other.

    python scripts/generate_fixtures.py
"""
from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = REPO_ROOT / "eval" / "fixtures"
CASSETTES_DIR = REPO_ROOT / "eval" / "cassettes"


def make_diff(file_path: str, code: str) -> str:
    lines = code.strip("\n").split("\n")
    body = "\n".join(f"+{line}" for line in lines)
    return (
        f"diff --git a/{file_path} b/{file_path}\n"
        f"new file mode 100644\n"
        f"index 0000000..0000000\n"
        f"--- /dev/null\n"
        f"+++ b/{file_path}\n"
        f"@@ -0,0 +1,{len(lines)} @@\n"
        f"{body}\n"
    )


def line_of(code: str, needle: str) -> int:
    lines = code.strip("\n").split("\n")
    for i, line in enumerate(lines, start=1):
        if needle in line:
            return i
    raise ValueError(f"substring not found in fixture code: {needle!r}")


# Each entry: id, file, code, ground_truth, cassette_findings (what the
# recorded reviewer run actually returned -- including its real mistakes,
# see README for the two intentionally-imperfect fixtures).
FIXTURES = []


def add_fixture(fid, file, code, clean, categories, severity, cassette_findings):
    FIXTURES.append(
        dict(
            id=fid,
            file=file,
            code=code,
            clean=clean,
            categories=categories,
            severity=severity,
            cassette_findings=cassette_findings,
        )
    )


# ---------------------------------------------------------------------------
# 1. SQL injection
# ---------------------------------------------------------------------------
code = '''
from flask import request
from app.db import get_connection


def search_users(query: str):
    conn = get_connection()
    cursor = conn.cursor()
    sql = "SELECT id, name, email FROM users WHERE name LIKE '%" + query + "%'"
    cursor.execute(sql)
    return cursor.fetchall()


@app.route("/api/users/search")
def search_endpoint():
    query = request.args.get("q", "")
    return {"results": search_users(query)}
'''
evidence = '    sql = "SELECT id, name, email FROM users WHERE name LIKE \'%" + query + "%\'"'
add_fixture(
    "sql_injection", "app/api/search.py", code, False, ["sql_injection"], "critical",
    [dict(category="sql_injection", severity="critical", file="app/api/search.py",
          line=line_of(code, "sql = "),
          summary="User-controlled `query` is concatenated directly into a SQL string, allowing SQL injection via the /api/users/search endpoint.",
          evidence=evidence)],
)

# ---------------------------------------------------------------------------
# 2. Insecure deserialization
# ---------------------------------------------------------------------------
code = '''
import pickle
import redis

r = redis.Redis()


def process_job(job_id: str):
    raw = r.get(f"job:{job_id}")
    job = pickle.loads(raw)
    return job.run()
'''
add_fixture(
    "insecure_deserialization", "app/jobs/worker.py", code, False, ["insecure_deserialization"], "critical",
    [dict(category="insecure_deserialization", severity="critical", file="app/jobs/worker.py",
          line=line_of(code, "pickle.loads"),
          summary="pickle.loads() on data read from Redis lets anyone who can write to that key execute arbitrary code when the job runs.",
          evidence="    job = pickle.loads(raw)")],
)

# ---------------------------------------------------------------------------
# 3. PII in logs
# ---------------------------------------------------------------------------
code = '''
import logging

logger = logging.getLogger("requests")


def log_signup(user):
    logger.info(f"New signup: email={user.email} ssn={user.ssn} phone={user.phone}")
    return user
'''
add_fixture(
    "pii_logging", "app/middleware/logging.py", code, False, ["pii_logging"], "high",
    [dict(category="pii_logging", severity="high", file="app/middleware/logging.py",
          line=line_of(code, "logger.info(f\"New signup"),
          summary="Logging the user's SSN and phone number in plaintext puts regulated PII into log storage/aggregators.",
          evidence='    logger.info(f"New signup: email={user.email} ssn={user.ssn} phone={user.phone}")')],
)

# ---------------------------------------------------------------------------
# 4. Off-by-one: pagination slice (medium)
# ---------------------------------------------------------------------------
code = '''
def paginate(items, page: int, page_size: int = 20):
    start = page * page_size
    end = start + page_size
    return items[start:end + 1]


def get_page_count(total_items: int, page_size: int = 20):
    return total_items // page_size
'''
add_fixture(
    "off_by_one_pagination", "app/api/pagination.py", code, False, ["off_by_one"], "medium",
    [dict(category="off_by_one", severity="medium", file="app/api/pagination.py",
          line=line_of(code, "return items[start:end"),
          summary="Slicing `items[start:end + 1]` returns page_size + 1 items instead of page_size, leaking one row from the next page.",
          evidence="    return items[start:end + 1]")],
)

# ---------------------------------------------------------------------------
# 5. Off-by-one: loop bound (low) -- INTENTIONALLY MISSED by the cassette
# ---------------------------------------------------------------------------
code = '''
def chunk_ids(ids: list[int], batch_size: int):
    batches = []
    for i in range(0, len(ids), batch_size):
        batches.append(ids[i:i + batch_size])
    return batches


def last_n_days(days: int):
    result = []
    for i in range(1, days):
        result.append(i)
    return result
'''
add_fixture(
    "off_by_one_loop", "app/utils/batching.py", code, False, ["off_by_one"], "low",
    [],  # recorded run missed this one -- see README "known limitations"
)

# ---------------------------------------------------------------------------
# 6. Missing auth on a state-changing webhook
# ---------------------------------------------------------------------------
code = '''
from flask import Blueprint, request

bp = Blueprint("webhooks", __name__)


@bp.route("/webhooks/stripe/refund", methods=["POST"])
def stripe_refund():
    payload = request.get_json()
    order_id = payload["order_id"]
    process_refund(order_id, payload["amount"])
    return {"status": "ok"}
'''
add_fixture(
    "missing_auth_webhook", "app/api/webhooks.py", code, False, ["missing_auth"], "critical",
    [dict(category="missing_auth", severity="critical", file="app/api/webhooks.py",
          line=line_of(code, '@bp.route("/webhooks/stripe/refund"'),
          summary="The refund webhook has no signature/auth check, so anyone who finds the URL can trigger refunds for arbitrary orders.",
          evidence='@bp.route("/webhooks/stripe/refund", methods=["POST"])')],
)

# ---------------------------------------------------------------------------
# 7. Timezone bug (medium)
# ---------------------------------------------------------------------------
code = '''
from datetime import datetime


def is_invoice_overdue(due_date: datetime) -> bool:
    return datetime.now() > due_date


def days_until_due(due_date: datetime) -> int:
    delta = due_date - datetime.now()
    return delta.days
'''
add_fixture(
    "timezone_bug", "app/billing/invoices.py", code, False, ["timezone_bug"], "medium",
    [dict(category="timezone_bug", severity="medium", file="app/billing/invoices.py",
          line=line_of(code, "return datetime.now() > due_date"),
          summary="datetime.now() returns naive local time; comparing it against a UTC due_date will misjudge overdue status depending on server timezone.",
          evidence="    return datetime.now() > due_date")],
)

# ---------------------------------------------------------------------------
# 8. Shell injection
# ---------------------------------------------------------------------------
code = '''
import os


def convert_to_pdf(input_path: str, output_path: str):
    os.system(f"libreoffice --headless --convert-to pdf --outdir {output_path} {input_path}")
'''
add_fixture(
    "shell_injection", "app/tools/convert.py", code, False, ["shell_injection"], "critical",
    [dict(category="shell_injection", severity="critical", file="app/tools/convert.py",
          line=line_of(code, "os.system"),
          summary="input_path/output_path are interpolated directly into a shell command, allowing command injection via a crafted filename.",
          evidence='    os.system(f"libreoffice --headless --convert-to pdf --outdir {output_path} {input_path}")')],
)

# ---------------------------------------------------------------------------
# 9. Session expiry never checked -- INTENTIONALLY paraphrased evidence
#    (cassette quotes something close but not exact, so the critic marks it
#    unverified; escalation still fires via the unverified-high-severity rule)
# ---------------------------------------------------------------------------
code = '''
import time

SESSIONS = {}


def create_session(user_id: str) -> str:
    token = generate_token()
    SESSIONS[token] = {"user_id": user_id, "created_at": time.time()}
    return token


def is_session_valid(token: str) -> bool:
    return token in SESSIONS
'''
add_fixture(
    "session_expiry", "app/auth/sessions.py", code, False, ["session_expiry"], "high",
    [dict(category="session_expiry", severity="high", file="app/auth/sessions.py",
          line=line_of(code, "return token in SESSIONS"),
          summary="is_session_valid() only checks membership and never compares created_at against a TTL, so sessions never expire.",
          # Paraphrased, not a literal substring of the diff -> critic will fail to verify it.
          evidence="return token in SESSIONS_STORE  # no expiry check")],
)

# ---------------------------------------------------------------------------
# 10. Race condition
# ---------------------------------------------------------------------------
code = '''
def reserve_stock(item_id: str, quantity: int) -> bool:
    current = get_stock(item_id)
    if current < quantity:
        return False
    set_stock(item_id, current - quantity)
    return True
'''
add_fixture(
    "race_condition", "app/inventory/stock.py", code, False, ["race_condition"], "high",
    [dict(category="race_condition", severity="high", file="app/inventory/stock.py",
          line=line_of(code, "current = get_stock(item_id)"),
          summary="Read-then-write on stock with no lock or transaction lets two concurrent requests both pass the check and oversell inventory.",
          evidence="    current = get_stock(item_id)")],
)

# ---------------------------------------------------------------------------
# 11. Path traversal (category: other)
# ---------------------------------------------------------------------------
code = '''
import os

UPLOAD_DIR = "/var/app/uploads"


def download_file(filename: str):
    path = os.path.join(UPLOAD_DIR, filename)
    with open(path, "rb") as f:
        return f.read()
'''
add_fixture(
    "path_traversal", "app/api/files.py", code, False, ["other"], "high",
    [dict(category="other", severity="high", file="app/api/files.py",
          line=line_of(code, "path = os.path.join"),
          summary="filename is joined into UPLOAD_DIR without sanitization, so a value like '../../etc/passwd' escapes the upload directory.",
          evidence="    path = os.path.join(UPLOAD_DIR, filename)")],
)

# ---------------------------------------------------------------------------
# Clean fixtures
# ---------------------------------------------------------------------------
code = '''
def format_currency(cents: int) -> str:
    dollars = cents / 100
    return f"${dollars:,.2f}"


def truncate(text: str, max_len: int = 100) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "..."
'''
add_fixture("clean_formatting_helpers", "app/utils/formatting.py", code, True, [], None, [])

code = '''
from flask import Blueprint, jsonify

bp = Blueprint("health", __name__)


@bp.route("/health")
def health_check():
    return jsonify({"status": "ok"})
'''
add_fixture("clean_health_endpoint", "app/api/health.py", code, True, [], None, [])

code = '''
from app.utils.formatting import format_currency, truncate


def test_format_currency():
    assert format_currency(150) == "$1.50"
    assert format_currency(100000) == "$1,000.00"


def test_truncate_short_text_unchanged():
    assert truncate("hi", max_len=10) == "hi"


def test_truncate_long_text_is_cut():
    result = truncate("a" * 200, max_len=10)
    assert len(result) == 10
'''
add_fixture("clean_formatting_tests", "tests/test_formatting.py", code, True, [], None, [])

# Correctly-fixed version of fixture #4's bug. The recorded reviewer run
# gets this one wrong -- it flags the ceiling-division as suspicious even
# though it's the correct fix. Low severity, so it does NOT trigger
# escalation, but it does count against precision. See README.
code = '''
def paginate(items, page: int, page_size: int = 20):
    start = page * page_size
    end = start + page_size
    return items[start:end]


def get_page_count(total_items: int, page_size: int = 20):
    return (total_items + page_size - 1) // page_size
'''
add_fixture(
    "clean_pagination_fix", "app/api/pagination_v2.py", code, True, [], None,
    [dict(category="off_by_one", severity="low", file="app/api/pagination_v2.py",
          line=line_of(code, "return (total_items + page_size - 1)"),
          summary="Unusual ceiling-division expression for page count -- worth a second look.",
          evidence="    return (total_items + page_size - 1) // page_size")],
)


def main():
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    CASSETTES_DIR.mkdir(parents=True, exist_ok=True)

    for fx in FIXTURES:
        fdir = FIXTURES_DIR / fx["id"]
        fdir.mkdir(parents=True, exist_ok=True)
        (fdir / "pr.diff").write_text(make_diff(fx["file"], fx["code"]))
        (fdir / "ground_truth.json").write_text(
            json.dumps(
                {"clean": fx["clean"], "categories": fx["categories"], "severity": fx["severity"]},
                indent=2,
            )
            + "\n"
        )
        (CASSETTES_DIR / f"{fx['id']}.json").write_text(
            json.dumps({"findings": fx["cassette_findings"]}, indent=2) + "\n"
        )
        print(f"wrote fixture: {fx['id']}")

    print(f"\n{len(FIXTURES)} fixtures generated ({sum(1 for f in FIXTURES if not f['clean'])} buggy, "
          f"{sum(1 for f in FIXTURES if f['clean'])} clean)")


if __name__ == "__main__":
    main()
