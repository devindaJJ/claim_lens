"""API workflow tests.

They need PostgreSQL with pgvector (e.g. `make test`) and run in a separate ``<db>_test``
database, created on demand, so they never touch the application's data.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, make_url, text

from app import db
from app.config import get_settings


def _use_test_database(settings) -> None:
    url = make_url(settings.database_url)
    test_url = url.set(database=f"{url.database}_test")
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            exists = conn.scalar(text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": test_url.database})
            if not exists:
                conn.execute(text(f'CREATE DATABASE "{test_url.database}"'))
    finally:
        admin.dispose()
    settings.database_url = test_url.render_as_string(hide_password=False)
    db.get_engine.cache_clear()
    db._session_factory.cache_clear()


@pytest.fixture(scope="module")
def client(data_dir, tmp_path_factory, retriever):
    from fastapi.testclient import TestClient

    settings = get_settings()
    original_url, original_storage = settings.database_url, settings.storage_dir
    try:
        _use_test_database(settings)
    except Exception:
        pytest.skip("PostgreSQL is not reachable")

    from alembic import command
    from alembic.config import Config

    import app.api.claims as claims_api
    from app.cli import ingest_policies
    from app.main import app
    from app.worker import process_claim

    settings.storage_dir = tmp_path_factory.mktemp("storage")
    command.upgrade(Config("alembic.ini"), "head")
    with db.session_scope() as session:
        session.execute(text("TRUNCATE claims CASCADE"))
    ingest_policies(data_dir / "policies")

    original_enqueue = claims_api.enqueue
    claims_api.enqueue = lambda claim_id: process_claim.run(str(claim_id))  # run inline
    try:
        yield TestClient(app)
    finally:
        claims_api.enqueue = original_enqueue
        settings.database_url, settings.storage_dir = original_url, original_storage
        db.get_engine.cache_clear()
        db._session_factory.cache_clear()


def _upload(client, data_dir, claim_id: str) -> dict:
    path = data_dir / "claims" / f"{claim_id}.pdf"
    response = client.post("/api/claims", files={"file": (path.name, path.read_bytes(), "application/pdf")})
    assert response.status_code == 202, response.text
    return client.get(f"/api/claims/{response.json()['id']}").json()


def test_rejects_non_pdf(client):
    response = client.post("/api/claims", files={"file": ("x.txt", b"hello", "text/plain")})
    assert response.status_code == 415


def test_review_workflow(client, data_dir):
    claim = _upload(client, data_dir, "CLM-2025-0017")  # dental claim over the $1,500 limit
    assert claim["status"] == "needs_review"
    assert [r["code"] for r in claim["rules"] if not r["passed"]] == ["within_limit"]
    assert client.get(f"/api/claims/{claim['id']}/document").headers["content-type"] == "application/pdf"

    # Approval is blocked until every field has been reviewed.
    response = client.post(f"/api/claims/{claim['id']}/decision", json={"decision": "approve"})
    assert response.status_code == 409

    # Correcting the amount re-runs the rules.
    url = f"/api/claims/{claim['id']}/fields/amount"
    assert client.patch(url, json={"action": "correct", "value": "abc"}).status_code == 422
    updated = client.patch(url, json={"action": "correct", "value": "1450"}).json()
    amount = next(f for f in updated["fields"] if f["name"] == "amount")
    assert amount["status"] == "corrected" and amount["value"] == "1450.00"
    assert all(r["passed"] for r in updated["rules"])

    for field in updated["fields"]:
        if field["status"] == "pending":
            client.patch(f"/api/claims/{claim['id']}/fields/{field['name']}", json={"action": "accept"})
    decided = client.post(
        f"/api/claims/{claim['id']}/decision", json={"decision": "approve", "notes": "Agreed with dentist"}
    ).json()
    assert decided["status"] == "approved"
    assert client.patch(url, json={"action": "accept"}).status_code == 409


def test_list_and_stats(client, data_dir):
    _upload(client, data_dir, "CLM-2025-0001")
    listing = client.get("/api/claims", params={"status": "auto_approved"}).json()
    assert listing["total"] >= 1 and all(c["status"] == "auto_approved" for c in listing["items"])
    stats = client.get("/api/claims/stats").json()
    assert stats["total"] == sum(stats["counts"].values())
    assert len(client.get("/api/policies").json()) == 4
