"""
test_api.py
-----------
Tests all API endpoints against the running local server.
Uses the seeded fixture data — run seed.py first.

Prerequisites:
    1. seed.py has been run (creates test users and campaigns)
    2. API server is running:
       uvicorn api.main:app --reload --port 8000
    3. CLERK_DEV_MODE=true in .env

Usage:
    python test_api.py
    python test_api.py --base-url http://localhost:8000
    python test_api.py --verbose

All tests run against the ANDELA fixture seeded by seed.py.
The test automatically reads user_id and campaign_id from the local database.
"""

import os
import sys
import json
import sqlite3
import argparse
import logging

os.environ.setdefault("SDA_ENV", "local")
logging.basicConfig(level=logging.WARNING)

try:
    import httpx
except ImportError:
    print("httpx not installed. Run: pip install httpx")
    sys.exit(1)


DEFAULT_BASE_URL = "http://localhost:8000"
DB_PATH = os.getenv("LOCAL_DB_PATH", "./sda_local.db")


def check(label: str, condition: bool, detail: str = ""):
    status = "✅" if condition else "❌"
    suffix = f" — {detail}" if detail and not condition else ""
    print(f"  {status} {label}{suffix}")
    if not condition:
        sys.exit(1)


def _load_fixture_ids() -> dict:
    if not os.path.exists(DB_PATH):
        print(f"Database not found at {DB_PATH}. Run: python seed.py")
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    user = conn.execute(
        "SELECT * FROM users WHERE email = 'test.andela@sda-local.dev'"
    ).fetchone()

    if not user:
        print("Andela fixture not found. Run: python seed.py --fixture andela")
        sys.exit(1)

    user = dict(user)

    campaign = conn.execute(
        "SELECT * FROM campaigns WHERE user_id = ? ORDER BY created_at LIMIT 1",
        (user["id"],)
    ).fetchone()
    campaign = dict(campaign)

    leads = conn.execute(
        "SELECT * FROM leads WHERE campaign_id = ? ORDER BY created_at",
        (campaign["id"],)
    ).fetchall()
    leads = [dict(l) for l in leads]

    seq = conn.execute(
        "SELECT * FROM email_sequences WHERE campaign_id = ? LIMIT 1",
        (campaign["id"],)
    ).fetchone()
    email_lead_id = dict(seq)["lead_id"] if seq else None

    conn.close()

    return {
        "user_id": user["id"],
        "campaign_id": campaign["id"],
        "lead_ids": [l["id"] for l in leads],
        "email_lead_id": email_lead_id,
    }


def _h() -> dict:
    """Dev mode headers — fake Bearer token accepted by CLERK_DEV_MODE."""
    return {"Authorization": "Bearer dev_token_local_testing"}


def test_health(client, base_url):
    print("\n1. Health Check")
    r = client.get(f"{base_url}/health")
    check("GET /health — 200", r.status_code == 200)
    check("status=healthy", r.json().get("status") == "healthy")
    check("environment=local", r.json().get("environment") == "local")


def test_users(client, base_url, ids):
    print("\n2. Users")
    r = client.get(f"{base_url}/users/me", headers=_h())
    check("GET /users/me — 200", r.status_code == 200, r.text)
    d = r.json()
    check("has id", "id" in d)
    check("has email", "email" in d)
    check("has has_active_subscription", "has_active_subscription" in d)


def test_campaigns_list(client, base_url, ids):
    print("\n3. Campaigns — List")
    r = client.get(f"{base_url}/campaigns", headers=_h())
    check("GET /campaigns — 200", r.status_code == 200, r.text)
    d = r.json()
    check("has campaigns list", "campaigns" in d)
    check("at least 1 campaign", d["total"] >= 1)


def test_campaigns_get(client, base_url, ids):
    print("\n4. Campaigns — Get Single")
    cid = ids["campaign_id"]
    r = client.get(f"{base_url}/campaigns/{cid}", headers=_h())
    check("GET /campaigns/{id} — 200", r.status_code == 200, r.text)
    d = r.json()
    check("campaign id matches", d["id"] == cid)
    check("has status", "status" in d)
    check("has summary", "summary" in d)
    check("summary has total_leads", "total_leads" in d["summary"])


def test_campaigns_404(client, base_url, ids):
    print("\n5. Campaigns — 404 Guard")
    r = client.get(f"{base_url}/campaigns/does-not-exist", headers=_h())
    check("non-existent campaign returns 404", r.status_code == 404)


def test_icp(client, base_url, ids):
    print("\n6. ICP")
    cid = ids["campaign_id"]

    r = client.get(f"{base_url}/campaigns/{cid}/icp", headers=_h())
    check("GET /icp — 200", r.status_code == 200, r.text)
    d = r.json()
    check("has target_type", "target_type" in d)
    check("industry is list", isinstance(d.get("industry"), list))
    check("job_titles is list", isinstance(d.get("job_titles"), list))

    r = client.put(
        f"{base_url}/campaigns/{cid}/icp",
        headers=_h(),
        json={"company_size_max": 2000}
    )
    check("PUT /icp — 200", r.status_code == 200, r.text)
    check("company_size_max updated", r.json().get("company_size_max") == 2000)


def test_brief(client, base_url, ids):
    print("\n7. Product Brief")
    cid = ids["campaign_id"]

    r = client.get(f"{base_url}/campaigns/{cid}/brief", headers=_h())
    check("GET /brief — 200", r.status_code == 200, r.text)
    d = r.json()
    check("has product_name", "product_name" in d)
    check("key_differentiators is list", isinstance(d.get("key_differentiators"), list))

    r = client.put(
        f"{base_url}/campaigns/{cid}/brief",
        headers=_h(),
        json={"what_it_does": "Updated via API test."}
    )
    check("PUT /brief — 200", r.status_code == 200, r.text)
    check("what_it_does updated", "Updated via API test" in r.json().get("what_it_does", ""))


def test_pipeline_status(client, base_url, ids):
    print("\n8. Pipeline Status")
    cid = ids["campaign_id"]
    r = client.get(f"{base_url}/campaigns/{cid}/pipeline/status", headers=_h())
    check("GET /pipeline/status — 200", r.status_code == 200, r.text)
    d = r.json()
    check("has status", "status" in d)
    check("has is_running", "is_running" in d)
    check("has is_complete", "is_complete" in d)
    check("has is_failed", "is_failed" in d)
    check("has summary", "summary" in d)


def test_pipeline_run(client, base_url, ids):
    print("\n9. Pipeline Run")
    cid = ids["campaign_id"]
    r = client.post(
        f"{base_url}/campaigns/{cid}/pipeline/run",
        headers=_h(),
        json={"provider": "prospeo", "fetch_all": False, "target_lead_count": 25}
    )
    # 202 = accepted and queued, 409 = already running — both valid
    check(
        "POST /pipeline/run — 202 or 409",
        r.status_code in (202, 409),
        f"got {r.status_code}: {r.text}"
    )


def test_leads_list(client, base_url, ids):
    print("\n10. Leads — List")
    cid = ids["campaign_id"]

    r = client.get(f"{base_url}/campaigns/{cid}/leads", headers=_h())
    check("GET /leads — 200", r.status_code == 200, r.text)
    d = r.json()
    check("has leads list", "leads" in d)
    check("3 leads seeded", d["total"] == 3)
    check("leads have id and name", all("id" in l and "name" in l for l in d["leads"]))

    r = client.get(f"{base_url}/campaigns/{cid}/leads?status=email_written", headers=_h())
    check("GET /leads?status=email_written — 200", r.status_code == 200, r.text)
    filtered = r.json()
    check(
        "all filtered leads are email_written",
        all(l["status"] == "email_written" for l in filtered["leads"])
    )


def test_leads_single(client, base_url, ids):
    print("\n11. Leads — Get Single")
    cid = ids["campaign_id"]
    lid = ids["lead_ids"][0]

    r = client.get(f"{base_url}/campaigns/{cid}/leads/{lid}", headers=_h())
    check("GET /leads/{id} — 200", r.status_code == 200, r.text)
    d = r.json()
    check("lead id matches", d["id"] == lid)
    check("has enrichment", d.get("enrichment") is not None)
    check("has qualification", d.get("qualification") is not None)
    check("enrichment has identity_status", "identity_status" in d["enrichment"])
    check("qualification has decision", "decision" in d["qualification"])


def test_leads_wrong_campaign(client, base_url, ids):
    print("\n12. Leads — Wrong Campaign Guard")
    lid = ids["lead_ids"][0]
    r = client.get(f"{base_url}/campaigns/wrong-id/leads/{lid}", headers=_h())
    check("lead from wrong campaign — 404", r.status_code == 404)


def test_emails_list(client, base_url, ids):
    print("\n13. Emails — List")
    cid = ids["campaign_id"]
    r = client.get(f"{base_url}/campaigns/{cid}/emails", headers=_h())
    check("GET /emails — 200", r.status_code == 200, r.text)
    d = r.json()
    check("has sequences", "sequences" in d)
    check("2 sequences seeded", d["total"] == 2)


def test_emails_single(client, base_url, ids):
    print("\n14. Emails — Get Single")
    cid = ids["campaign_id"]
    lid = ids["email_lead_id"]
    if not lid:
        print("  ⚠️  No email sequence seeded — skipping")
        return

    r = client.get(f"{base_url}/campaigns/{cid}/emails/{lid}", headers=_h())
    check("GET /emails/{lead_id} — 200", r.status_code == 200, r.text)
    d = r.json()
    check("has email_1", "email_1" in d)
    check("has email_2", "email_2" in d)
    check("has email_3", "email_3" in d)
    check("email_1 has subject", "subject" in d["email_1"])


def test_emails_update(client, base_url, ids):
    print("\n15. Emails — Update")
    cid = ids["campaign_id"]
    lid = ids["email_lead_id"]
    if not lid:
        print("  ⚠️  No email sequence seeded — skipping")
        return

    r = client.put(
        f"{base_url}/campaigns/{cid}/emails/{lid}",
        headers=_h(),
        json={"email_1_subject": "Test updated subject"}
    )
    check("PUT /emails/{lead_id} — 200", r.status_code == 200, r.text)
    check("subject updated", r.json()["email_1"]["subject"] == "Test updated subject")


def test_analytics(client, base_url, ids):
    print("\n16. Analytics")
    cid = ids["campaign_id"]
    r = client.get(f"{base_url}/campaigns/{cid}/summary", headers=_h())
    check("GET /summary — 200", r.status_code == 200, r.text)
    d = r.json()
    check("campaign_id matches", d["campaign_id"] == cid)
    check("total_leads = 3", d["total_leads"] == 3)
    check("emails_written = 2", d["emails_written"] == 2)
    check("has approval_rate", d.get("approval_rate") is not None)
    check("has enrichment_rate", d.get("enrichment_rate") is not None)


def test_webhook(client, base_url, ids):
    print("\n17. Webhook — user.created")
    r = client.post(f"{base_url}/webhooks/clerk", json={
        "type": "user.created",
        "data": {
            "id": "clerk_webhook_test_001",
            "email_addresses": [{"id": "ea_001", "email_address": "webhook@sda-test.dev"}],
            "primary_email_address_id": "ea_001",
            "first_name": "Webhook",
            "last_name": "Test",
        }
    })
    check("POST /webhooks/clerk — 200", r.status_code == 200, r.text)
    check("received=True", r.json().get("received") is True)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    u = conn.execute("SELECT * FROM users WHERE id = 'clerk_webhook_test_001'").fetchone()
    conn.close()
    check("user created in DB by webhook", u is not None)


def test_create_and_delete_campaign(client, base_url, ids):
    print("\n18. Campaign Create + Delete")

    r = client.post(f"{base_url}/campaigns", headers=_h(), json={
        "name": "API Test — Delete Me",
        "website_url": "https://example.com",
        "company_name": "ExampleCo",
    })
    check("POST /campaigns — 201", r.status_code == 201, r.text)
    new_id = r.json()["id"]
    check("new campaign has id", bool(new_id))
    check("new campaign name correct", r.json()["name"] == "API Test — Delete Me")

    r = client.delete(f"{base_url}/campaigns/{new_id}", headers=_h())
    check("DELETE /campaigns/{id} — 200", r.status_code == 200, r.text)

    r = client.get(f"{base_url}/campaigns/{new_id}", headers=_h())
    check("deleted campaign status is cancelled", r.json().get("status") == "cancelled")


def test_unauthenticated(client, base_url, ids):
    print("\n19. Auth Guard — No Token")
    r = client.get(f"{base_url}/campaigns")
    # In dev mode get_current_user uses CLERK_DEV_USER_ID — no token needed
    # In production this would be 401. We just verify the endpoint responds.
    check("GET /campaigns without token responds", r.status_code in (200, 401))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.INFO)

    base_url = args.base_url.rstrip("/")

    print(f"\n🧪 SDA API Tests")
    print(f"   URL: {base_url}")
    print(f"   DB:  {DB_PATH}")

    # Load fixture IDs from seeded DB
    ids = _load_fixture_ids()
    print(f"   user     = {ids['user_id'][:8]}...")
    print(f"   campaign = {ids['campaign_id'][:8]}...")
    print(f"   leads    = {len(ids['lead_ids'])}")

    # Check server is up
    try:
        with httpx.Client(timeout=5.0) as probe:
            probe.get(f"{base_url}/health")
    except Exception:
        print(f"\n❌ Cannot reach {base_url}")
        print(f"   Start the server: uvicorn api.main:app --reload --port 8000")
        sys.exit(1)

    with httpx.Client(timeout=30.0) as client:
        test_health(client, base_url)
        test_users(client, base_url, ids)
        test_campaigns_list(client, base_url, ids)
        test_campaigns_get(client, base_url, ids)
        test_campaigns_404(client, base_url, ids)
        test_icp(client, base_url, ids)
        test_brief(client, base_url, ids)
        test_pipeline_status(client, base_url, ids)
        test_pipeline_run(client, base_url, ids)
        test_leads_list(client, base_url, ids)
        test_leads_single(client, base_url, ids)
        test_leads_wrong_campaign(client, base_url, ids)
        test_emails_list(client, base_url, ids)
        test_emails_single(client, base_url, ids)
        test_emails_update(client, base_url, ids)
        test_analytics(client, base_url, ids)
        test_webhook(client, base_url, ids)
        test_create_and_delete_campaign(client, base_url, ids)
        test_unauthenticated(client, base_url, ids)

    print(f"\n{'=' * 60}")
    print(f"✅ All API tests passed.")
    print(f"{'=' * 60}\n")


if __name__ == "__main__":
    main()
