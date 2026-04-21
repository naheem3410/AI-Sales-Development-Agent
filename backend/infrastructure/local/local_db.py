"""
local_db.py
-----------
SQLite database for local development.
Implements the same interface as the production Aurora client.
Swap the connection — agent code never changes.
"""

import sqlite3
import json
import uuid
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from contextlib import contextmanager
from pathlib import Path

from backend.config.settings import settings
from backend.core.schema import SCHEMA_SQL, FUTURE_SCHEMA_SQL
from backend.core.enums import CampaignStatus, LeadStatus

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return str(uuid.uuid4())


class LocalDatabase:
    """
    SQLite-backed database for local development.
    Thread-safe via check_same_thread=False + WAL mode.
    """

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or settings.local.db_path
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        logger.info(f"[LocalDB] Initialised at {self.db_path}")

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    @contextmanager
    def _conn(self):
        conn = self._get_connection()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self):
        with self._conn() as conn:
            conn.executescript(SCHEMA_SQL)
            conn.executescript(FUTURE_SCHEMA_SQL)
        logger.info("[LocalDB] Schema initialised.")

    # ── Users 

    def create_user(self, email: str, full_name: Optional[str] = None) -> Dict:
        user = {
            "id": _new_id(),
            "email": email,
            "full_name": full_name,
            "stripe_customer_id": None,
            "plan": "free",
            "created_at": _now(),
            "updated_at": _now(),
        }
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO users (id, email, full_name, stripe_customer_id, plan, created_at, updated_at)
                   VALUES (:id, :email, :full_name, :stripe_customer_id, :plan, :created_at, :updated_at)""",
                user
            )
        logger.info(f"[LocalDB] Created user {user['id']}")
        return user

    def get_user(self, user_id: str) -> Optional[Dict]:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            return dict(row) if row else None

    
    def create_user_with_id(self, user_id: str, email: str, full_name: Optional[str] = None) -> Dict:
        """Create a user with a pre-supplied ID (e.g. Clerk user_id)."""
        user = {
            "id": user_id,
            "email": email,
            "full_name": full_name,
            "stripe_customer_id": None,
            "plan": "paid",
            "created_at": _now(),
            "updated_at": _now(),
        }
        with self._conn() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO users (id, email, full_name, stripe_customer_id, plan, created_at, updated_at)
                   VALUES (:id, :email, :full_name, :stripe_customer_id, :plan, :created_at, :updated_at)""",
                user
            )
        logger.info(f"[LocalDB] Created user with Clerk ID {user_id}")
        return self.get_user(user_id)
 
    def get_user_by_email(self, email: str) -> Optional[Dict]:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
            return dict(row) if row else None
 
    def update_user(self, user_id: str, updates: Dict):
        updates["updated_at"] = _now()
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [user_id]
        with self._conn() as conn:
            conn.execute(f"UPDATE users SET {set_clause} WHERE id = ?", values)
    # ── Campaigns 

    def create_campaign(
        self,
        user_id: str,
        name: str,
        website_url: Optional[str] = None,
        company_name: Optional[str] = None,
    ) -> Dict:
        campaign = {
            "id": _new_id(),
            "user_id": user_id,
            "name": name,
            "status": CampaignStatus.CREATED,
            "website_url": website_url,
            "company_name": company_name,
            "pipeline_version": "1.0.0",
            "created_at": _now(),
            "updated_at": _now(),
            "completed_at": None,
            "paused_at": None,
            "failure_reason": None,
        }
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO campaigns 
                   (id, user_id, name, status, website_url, company_name, pipeline_version,
                    created_at, updated_at, completed_at, paused_at, failure_reason)
                   VALUES (:id, :user_id, :name, :status, :website_url, :company_name,
                           :pipeline_version, :created_at, :updated_at, :completed_at,
                           :paused_at, :failure_reason)""",
                campaign
            )
        logger.info(f"[LocalDB] Created campaign {campaign['id']} for user {user_id}")
        return campaign

    def get_campaign(self, campaign_id: str) -> Optional[Dict]:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM campaigns WHERE id = ?", (campaign_id,)).fetchone()
            return dict(row) if row else None

    def get_campaigns_for_user(self, user_id: str) -> List[Dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM campaigns WHERE user_id = ? ORDER BY created_at DESC",
                (user_id,)
            ).fetchall()
            return [dict(r) for r in rows]

    def update_campaign_status(
        self,
        campaign_id: str,
        status: CampaignStatus,
        failure_reason: Optional[str] = None,
        agent: Optional[str] = None,
        from_status: Optional[str] = None,
        notes: Optional[str] = None,
    ):
        now = _now()
        with self._conn() as conn:
            conn.execute(
                """UPDATE campaigns SET status = ?, updated_at = ?, failure_reason = ?
                   WHERE id = ?""",
                (status, now, failure_reason, campaign_id)
            )
            if status == CampaignStatus.CAMPAIGN_COMPLETE:
                conn.execute(
                    "UPDATE campaigns SET completed_at = ? WHERE id = ?",
                    (now, campaign_id)
                )
            if status == CampaignStatus.PAUSED:
                conn.execute(
                    "UPDATE campaigns SET paused_at = ? WHERE id = ?",
                    (now, campaign_id)
                )
            # Log the state change
            if agent:
                conn.execute(
                    """INSERT INTO pipeline_events (id, campaign_id, user_id, agent, from_status, to_status, notes, created_at)
                       SELECT ?, id, user_id, ?, ?, ?, ?, ? FROM campaigns WHERE id = ?""",
                    (_new_id(), agent, from_status, status, notes, now, campaign_id)
                )
        logger.info(f"[LocalDB] Campaign {campaign_id} → {status}")

    # ── ICP 

    def save_icp(self, campaign_id: str, user_id: str, icp_data: Dict) -> Dict:
        icp = {
            "id": _new_id(),
            "campaign_id": campaign_id,
            "user_id": user_id,
            "target_type": icp_data.get("target_type"),
            "industry": json.dumps(icp_data.get("industry", [])),
            "company_size_min": icp_data.get("company_size_min"),
            "company_size_max": icp_data.get("company_size_max"),
            "funding_status": json.dumps(icp_data.get("funding_status")) if icp_data.get("funding_status") else None,
            "job_titles": json.dumps(icp_data.get("job_titles", [])),
            "seniority": json.dumps(icp_data.get("seniority")) if icp_data.get("seniority") else None,
            "locations": json.dumps(icp_data.get("locations", [])),
            "tech_stack": json.dumps(icp_data.get("tech_stack")) if icp_data.get("tech_stack") else None,
            "demographics": icp_data.get("demographics"),
            "confidence_score": icp_data.get("confidence_score"),
            "missing_fields": json.dumps(icp_data.get("missing_fields", [])),
            "created_at": _now(),
            "updated_at": _now(),
        }
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO icps (id, campaign_id, user_id, target_type, industry, company_size_min,
                   company_size_max, funding_status, job_titles, seniority, locations, tech_stack,
                   demographics, confidence_score, missing_fields, created_at, updated_at)
                   VALUES (:id, :campaign_id, :user_id, :target_type, :industry, :company_size_min,
                           :company_size_max, :funding_status, :job_titles, :seniority, :locations,
                           :tech_stack, :demographics, :confidence_score, :missing_fields,
                           :created_at, :updated_at)""",
                icp
            )
        logger.info(f"[LocalDB] Saved ICP for campaign {campaign_id}")
        return icp

    def get_icp(self, campaign_id: str) -> Optional[Dict]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM icps WHERE campaign_id = ? ORDER BY created_at DESC LIMIT 1",
                (campaign_id,)
            ).fetchone()
            if not row:
                return None
            d = dict(row)
            # Deserialise JSON fields
            for f in ["industry", "funding_status", "job_titles", "seniority", "locations", "tech_stack", "missing_fields"]:
                if d.get(f):
                    d[f] = json.loads(d[f])
            return d

    # ── Product Brief 

    def save_product_brief(self, campaign_id: str, user_id: str, brief_data: Dict) -> Dict:
        brief = {
            "id": _new_id(),
            "campaign_id": campaign_id,
            "user_id": user_id,
            "product_name": brief_data.get("product_name"),
            "what_it_does": brief_data.get("what_it_does"),
            "who_it_is_for": brief_data.get("who_it_is_for"),
            "pain_it_solves": brief_data.get("pain_it_solves"),
            "key_differentiators": json.dumps(brief_data.get("key_differentiators", [])),
            "ideal_customer_description": brief_data.get("ideal_customer_description"),
            "created_at": _now(),
            "updated_at": _now(),
        }
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO product_briefs (id, campaign_id, user_id, product_name, what_it_does,
                   who_it_is_for, pain_it_solves, key_differentiators, ideal_customer_description,
                   created_at, updated_at)
                   VALUES (:id, :campaign_id, :user_id, :product_name, :what_it_does,
                           :who_it_is_for, :pain_it_solves, :key_differentiators,
                           :ideal_customer_description, :created_at, :updated_at)""",
                brief
            )
        logger.info(f"[LocalDB] Saved product brief for campaign {campaign_id}")
        return brief

    def get_product_brief(self, campaign_id: str) -> Optional[Dict]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM product_briefs WHERE campaign_id = ? ORDER BY created_at DESC LIMIT 1",
                (campaign_id,)
            ).fetchone()
            if not row:
                return None
            d = dict(row)
            if d.get("key_differentiators"):
                d["key_differentiators"] = json.loads(d["key_differentiators"])
            return d

    # ── Orchestration State 

    def init_orchestration_state(self, campaign_id: str, user_id: str) -> Dict:
        """Create the orchestration slot for a campaign — empty by default."""
        state = {
            "id": _new_id(),
            "campaign_id": campaign_id,
            "user_id": user_id,
            "provider_selected": None,
            "fetch_all": None,
            "enrich_mobile": 0,
            "target_lead_count": None,
            "batch_quality_score": None,
            "filters_relaxed": 0,
            "relaxed_fields": None,
            "retry_count": 0,
            "decision_log": json.dumps([]),
            "notes": None,
            "activated": 0,
            "created_at": _now(),
            "updated_at": _now(),
        }
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO orchestration_state 
                   (id, campaign_id, user_id, provider_selected, fetch_all, enrich_mobile,
                    target_lead_count, batch_quality_score, filters_relaxed, relaxed_fields,
                    retry_count, decision_log, notes, activated, created_at, updated_at)
                   VALUES (:id, :campaign_id, :user_id, :provider_selected, :fetch_all,
                           :enrich_mobile, :target_lead_count, :batch_quality_score,
                           :filters_relaxed, :relaxed_fields, :retry_count, :decision_log,
                           :notes, :activated, :created_at, :updated_at)""",
                state
            )
        logger.info(f"[LocalDB] Initialised orchestration slot for campaign {campaign_id}")
        return state

    def update_orchestration_state(self, campaign_id: str, updates: Dict):
        updates["updated_at"] = _now()
        if "decision_log" in updates and isinstance(updates["decision_log"], list):
            updates["decision_log"] = json.dumps(updates["decision_log"])
        if "relaxed_fields" in updates and isinstance(updates["relaxed_fields"], list):
            updates["relaxed_fields"] = json.dumps(updates["relaxed_fields"])
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [campaign_id]
        with self._conn() as conn:
            conn.execute(
                f"UPDATE orchestration_state SET {set_clause} WHERE campaign_id = ?",
                values
            )

    def get_orchestration_state(self, campaign_id: str) -> Optional[Dict]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM orchestration_state WHERE campaign_id = ?",
                (campaign_id,)
            ).fetchone()
            if not row:
                return None
            d = dict(row)
            if d.get("decision_log"):
                d["decision_log"] = json.loads(d["decision_log"])
            if d.get("relaxed_fields"):
                d["relaxed_fields"] = json.loads(d["relaxed_fields"])
            return d

    # ── Leads 

    def save_lead(self, campaign_id: str, user_id: str, lead_data: Dict) -> Dict:
        lead = {
            "id": _new_id(),
            "campaign_id": campaign_id,
            "user_id": user_id,
            "status": LeadStatus.INGESTED,
            "name": lead_data.get("name"),
            "first_name": lead_data.get("first_name"),
            "last_name": lead_data.get("last_name"),
            "title": lead_data.get("title"),
            "seniority": lead_data.get("seniority"),
            "email": lead_data.get("email"),
            "email_status": lead_data.get("email_status"),
            "phone": lead_data.get("phone"),
            "company": lead_data.get("company"),
            "company_size": lead_data.get("company_size"),
            "industry": lead_data.get("industry"),
            "location": lead_data.get("location"),
            "country": lead_data.get("country"),
            "linkedin": lead_data.get("linkedin"),
            "provider_id": lead_data.get("provider_id"),
            "provider": lead_data.get("provider"),
            "lead_type": lead_data.get("type"),
            "created_at": _now(),
            "updated_at": _now(),
        }
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO leads (id, campaign_id, user_id, status, name, first_name, last_name,
                   title, seniority, email, email_status, phone, company, company_size, industry,
                   location, country, linkedin, provider_id, provider, lead_type, created_at, updated_at)
                   VALUES (:id, :campaign_id, :user_id, :status, :name, :first_name, :last_name,
                           :title, :seniority, :email, :email_status, :phone, :company,
                           :company_size, :industry, :location, :country, :linkedin,
                           :provider_id, :provider, :lead_type, :created_at, :updated_at)""",
                lead
            )
        return lead

    def save_leads_batch(self, campaign_id: str, user_id: str, leads: List[Dict]) -> List[Dict]:
        saved = [self.save_lead(campaign_id, user_id, lead) for lead in leads]
        logger.info(f"[LocalDB] Saved {len(saved)} leads for campaign {campaign_id}")
        return saved

    def get_leads_for_campaign(self, campaign_id: str, status: Optional[str] = None) -> List[Dict]:
        with self._conn() as conn:
            if status:
                rows = conn.execute(
                    "SELECT * FROM leads WHERE campaign_id = ? AND status = ? ORDER BY created_at",
                    (campaign_id, status)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM leads WHERE campaign_id = ? ORDER BY created_at",
                    (campaign_id,)
                ).fetchall()
            return [dict(r) for r in rows]

    def update_lead_status(self, lead_id: str, status: LeadStatus):
        with self._conn() as conn:
            conn.execute(
                "UPDATE leads SET status = ?, updated_at = ? WHERE id = ?",
                (status, _now(), lead_id)
            )

    # ── Lead Queries 

    def save_lead_queries(self, lead_id: str, campaign_id: str, user_id: str, queries: List[str]):
        now = _now()
        with self._conn() as conn:
            for i, query_text in enumerate(queries, 1):
                conn.execute(
                    """INSERT INTO lead_queries (id, lead_id, campaign_id, user_id, query_slot, query_text, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (_new_id(), lead_id, campaign_id, user_id, i, query_text, now)
                )

    # ── Enrichment Results 

    def save_enrichment_result(self, lead_id: str, campaign_id: str, user_id: str, enrichment: Dict) -> Dict:
        enriched_data = enrichment.get("enriched_data", {})
        record = {
            "id": _new_id(),
            "lead_id": lead_id,
            "campaign_id": campaign_id,
            "user_id": user_id,
            "identity_status": enrichment.get("identity_status"),
            "confidence_score": enrichment.get("confidence_score"),
            "current_title": enriched_data.get("current_title"),
            "social_links": json.dumps(enriched_data.get("social_links", [])),
            "company_signals": json.dumps(enriched_data.get("company_signals", [])),
            "notable_achievements": json.dumps(enriched_data.get("notable_achievements", [])),
            "discrepancies": json.dumps(enrichment.get("discrepancies", [])),
            "raw_search_evidence": json.dumps(enrichment.get("raw_search_evidence", [])),
            "raw_search_evidence_s3": None,
            "evidence_used": json.dumps(enrichment.get("evidence_used", [])),
            "query_slot_coverage": json.dumps(enrichment.get("query_slot_coverage", [])),
            "enrichment_summary": enrichment.get("enrichment_summary"),
            "created_at": _now(),
            "updated_at": _now(),
        }
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO enrichment_results 
                   (id, lead_id, campaign_id, user_id, identity_status, confidence_score,
                    current_title, social_links, company_signals, notable_achievements,
                    discrepancies, raw_search_evidence, raw_search_evidence_s3, evidence_used,
                    query_slot_coverage, enrichment_summary, created_at, updated_at)
                   VALUES (:id, :lead_id, :campaign_id, :user_id, :identity_status, :confidence_score,
                           :current_title, :social_links, :company_signals, :notable_achievements,
                           :discrepancies, :raw_search_evidence, :raw_search_evidence_s3,
                           :evidence_used, :query_slot_coverage, :enrichment_summary,
                           :created_at, :updated_at)""",
                record
            )
        return record

    # ── Qualification Results 

    def save_qualification_result(self, lead_id: str, campaign_id: str, user_id: str, decision: Dict) -> Dict:
        record = {
            "id": _new_id(),
            "lead_id": lead_id,
            "campaign_id": campaign_id,
            "user_id": user_id,
            "decision": decision.get("decision"),
            "decision_reason": decision.get("decision_reason"),
            "icp_match_score": decision.get("icp_match_score"),
            "match_breakdown": json.dumps(decision.get("match_breakdown", [])),
            "blocking_issues": json.dumps(decision.get("blocking_issues", [])),
            "review_flags": json.dumps(decision.get("review_flags", [])),
            "recommended_angle": decision.get("recommended_angle"),
            "created_at": _now(),
            "updated_at": _now(),
        }
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO qualification_results
                   (id, lead_id, campaign_id, user_id, decision, decision_reason, icp_match_score,
                    match_breakdown, blocking_issues, review_flags, recommended_angle,
                    created_at, updated_at)
                   VALUES (:id, :lead_id, :campaign_id, :user_id, :decision, :decision_reason,
                           :icp_match_score, :match_breakdown, :blocking_issues, :review_flags,
                           :recommended_angle, :created_at, :updated_at)""",
                record
            )
        return record

    # ── Email Sequences 

    def save_email_sequence(self, lead_id: str, campaign_id: str, user_id: str, sequence: Dict) -> Dict:
        record = {
            "id": _new_id(),
            "lead_id": lead_id,
            "campaign_id": campaign_id,
            "user_id": user_id,
            "lead_email": sequence.get("lead_email"),
            "email_1_subject": sequence.get("email_1", {}).get("subject"),
            "email_1_body": sequence.get("email_1", {}).get("body"),
            "email_2_subject": sequence.get("email_2", {}).get("subject"),
            "email_2_body": sequence.get("email_2", {}).get("body"),
            "email_3_subject": sequence.get("email_3", {}).get("subject"),
            "email_3_body": sequence.get("email_3", {}).get("body"),
            "sequence_notes": sequence.get("sequence_notes"),
            "email_1_sent_at": None,
            "email_2_sent_at": None,
            "email_3_sent_at": None,
            "email_1_opened_at": None,
            "email_2_opened_at": None,
            "email_3_opened_at": None,
            "replied_at": None,
            "reply_content": None,
            "reply_classification": None,
            "created_at": _now(),
            "updated_at": _now(),
        }
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO email_sequences
                   (id, lead_id, campaign_id, user_id, lead_email,
                    email_1_subject, email_1_body, email_2_subject, email_2_body,
                    email_3_subject, email_3_body, sequence_notes,
                    email_1_sent_at, email_2_sent_at, email_3_sent_at,
                    email_1_opened_at, email_2_opened_at, email_3_opened_at,
                    replied_at, reply_content, reply_classification,
                    created_at, updated_at)
                   VALUES (:id, :lead_id, :campaign_id, :user_id, :lead_email,
                           :email_1_subject, :email_1_body, :email_2_subject, :email_2_body,
                           :email_3_subject, :email_3_body, :sequence_notes,
                           :email_1_sent_at, :email_2_sent_at, :email_3_sent_at,
                           :email_1_opened_at, :email_2_opened_at, :email_3_opened_at,
                           :replied_at, :reply_content, :reply_classification,
                           :created_at, :updated_at)""",
                record
            )
        return record

    # ── Pipeline Messages 

    def log_pipeline_message(self, message_dict: Dict):
        with self._conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO pipeline_messages
                   (id, correlation_id, user_id, campaign_id, source_agent, target_agent,
                    queue, status, campaign_status_on_send, orchestration_metadata,
                    payload_summary, payload_s3_key, retry_count, last_error,
                    pipeline_version, created_at, processed_at, completed_at)
                   VALUES (:id, :correlation_id, :user_id, :campaign_id, :source_agent,
                           :target_agent, :queue, :status, :campaign_status_on_send,
                           :orchestration_metadata, :payload_summary, :payload_s3_key,
                           :retry_count, :last_error, :pipeline_version, :created_at,
                           :processed_at, :completed_at)""",
                message_dict
            )

    def update_message_status(self, message_id: str, status: str, completed_at: Optional[str] = None):
        with self._conn() as conn:
            conn.execute(
                "UPDATE pipeline_messages SET status = ?, completed_at = ? WHERE id = ?",
                (status, completed_at or _now(), message_id)
            )

    # ── Campaign Summary 

    def get_campaign_summary(self, campaign_id: str) -> Dict:
        with self._conn() as conn:
            total_leads = conn.execute(
                "SELECT COUNT(*) FROM leads WHERE campaign_id = ?", (campaign_id,)
            ).fetchone()[0]
            enriched = conn.execute(
                "SELECT COUNT(*) FROM enrichment_results WHERE campaign_id = ?", (campaign_id,)
            ).fetchone()[0]
            approved = conn.execute(
                "SELECT COUNT(*) FROM qualification_results WHERE campaign_id = ? AND decision = 'approved'",
                (campaign_id,)
            ).fetchone()[0]
            review = conn.execute(
                "SELECT COUNT(*) FROM qualification_results WHERE campaign_id = ? AND decision = 'review'",
                (campaign_id,)
            ).fetchone()[0]
            rejected = conn.execute(
                "SELECT COUNT(*) FROM qualification_results WHERE campaign_id = ? AND decision = 'rejected'",
                (campaign_id,)
            ).fetchone()[0]
            emails_written = conn.execute(
                "SELECT COUNT(*) FROM email_sequences WHERE campaign_id = ?", (campaign_id,)
            ).fetchone()[0]
        return {
            "campaign_id": campaign_id,
            "total_leads": total_leads,
            "enriched": enriched,
            "approved": approved,
            "review": review,
            "rejected": rejected,
            "emails_written": emails_written,
        }


# ── Singleton 
_local_db: Optional[LocalDatabase] = None

def get_local_db() -> LocalDatabase:
    global _local_db
    if _local_db is None:
        _local_db = LocalDatabase()
    return _local_db
