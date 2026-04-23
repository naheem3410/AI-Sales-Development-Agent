"""
factory.py
----------
Infrastructure factory.
Every agent asks this for a database and queue client.
It returns local (SQLite + file queue) or production (Aurora + SQS)
based on the active environment.

Agent code never imports LocalDatabase or ProductionDatabase directly.
It always goes through get_db() and get_queue().
"""

import logging
from typing import Protocol, Any, List, Optional, runtime_checkable

from backend.config.settings import settings, Environment

logger = logging.getLogger(__name__)


# ── Database Protocol 
# Defines the interface both local and production DB must implement.
# If you add a method to LocalDatabase, add it here too.

@runtime_checkable
class DatabaseClient(Protocol):
    def create_user(self, email: str, full_name: Optional[str]) -> dict: ...
    def get_user(self, user_id: str) -> Optional[dict]: ...
    def create_campaign(self, user_id: str, name: str, website_url: Optional[str], company_name: Optional[str]) -> dict: ...
    def get_campaign(self, campaign_id: str) -> Optional[dict]: ...
    def get_campaigns_for_user(self, user_id: str) -> List[dict]: ...
    def update_campaign_status(self, campaign_id: str, status: Any, failure_reason: Optional[str], agent: Optional[str], from_status: Optional[str], notes: Optional[str]): ...
    def save_icp(self, campaign_id: str, user_id: str, icp_data: dict) -> dict: ...
    def get_icp(self, campaign_id: str) -> Optional[dict]: ...
    def save_product_brief(self, campaign_id: str, user_id: str, brief_data: dict) -> dict: ...
    def get_product_brief(self, campaign_id: str) -> Optional[dict]: ...
    def init_orchestration_state(self, campaign_id: str, user_id: str) -> dict: ...
    def update_orchestration_state(self, campaign_id: str, updates: dict): ...
    def get_orchestration_state(self, campaign_id: str) -> Optional[dict]: ...
    def save_lead(self, campaign_id: str, user_id: str, lead_data: dict) -> dict: ...
    def save_leads_batch(self, campaign_id: str, user_id: str, leads: List[dict]) -> List[dict]: ...
    def get_leads_for_campaign(self, campaign_id: str, status: Optional[str]) -> List[dict]: ...
    def resolve_lead_review_decision(self, campaign_id: str, lead_id: str, approve: bool) -> dict: ...
    def update_lead_status(self, lead_id: str, status: Any): ...
    def save_lead_queries(self, lead_id: str, campaign_id: str, user_id: str, queries: List[str]): ...
    def save_enrichment_result(self, lead_id: str, campaign_id: str, user_id: str, enrichment: dict) -> dict: ...
    def save_qualification_result(self, lead_id: str, campaign_id: str, user_id: str, decision: dict) -> dict: ...
    def save_email_sequence(self, lead_id: str, campaign_id: str, user_id: str, sequence: dict) -> dict: ...
    def log_pipeline_message(self, message_dict: dict): ...
    def update_message_status(self, message_id: str, status: str, completed_at: Optional[str]): ...
    def get_campaign_summary(self, campaign_id: str) -> dict: ...


# ── Queue Protocol 

@runtime_checkable
class QueueClient(Protocol):
    def send(self, message: Any) -> str: ...
    def poll(self, queue: Any, max_messages: int) -> List[Any]: ...
    def acknowledge(self, message: Any): ...
    def fail(self, message: Any, error_message: str): ...
    def send_to_orchestration(self, message: Any) -> str: ...
    def poll_orchestration_out(self) -> List[Any]: ...
    def queue_depth(self, queue: Any) -> dict: ...


# ── Factory Functions 

def get_db() -> DatabaseClient:
    """
    Returns the appropriate database client for the current environment.
    Local → SQLite via LocalDatabase
    Production → Aurora PostgreSQL (stub — implement when deploying)
    """
    if settings.is_local():
        from backend.infrastructure.local.local_db import get_local_db
        return get_local_db()

    elif settings.is_production():
        # Production Aurora client — implement when ready to deploy
        # from infrastructure.production.aurora_db import get_aurora_db
        # return get_aurora_db()
        raise NotImplementedError(
            "Production database client not yet implemented. "
            "Set SDA_ENV=local for development."
        )

    else:
        raise ValueError(f"Unknown environment: {settings.env}")


def get_queue() -> QueueClient:
    """
    Returns the appropriate queue client for the current environment.
    Local → File-based queue via LocalQueue
    Production → AWS SQS (stub — implement when deploying)
    """
    if settings.is_local():
        from backend.infrastructure.local.local_queue import get_local_queue
        return get_local_queue()

    elif settings.is_production():
        # Production SQS client — implement when ready to deploy
        # from infrastructure.production.sqs_queue import get_sqs_queue
        # return get_sqs_queue()
        raise NotImplementedError(
            "Production SQS client not yet implemented. "
            "Set SDA_ENV=local for development."
        )

    else:
        raise ValueError(f"Unknown environment: {settings.env}")


# ── Storage Factory (S3 / local mock) 

def get_storage():
    """
    Returns the appropriate object storage client.
    Local → Local filesystem mock
    Production → AWS S3
    Used for large payloads (raw enrichment evidence, email sequences).
    """
    if settings.is_local():
        from backend.infrastructure.local.local_storage import get_local_storage
        return get_local_storage()

    elif settings.is_production():
        # from infrastructure.production.s3_storage import get_s3_storage
        # return get_s3_storage()
        raise NotImplementedError("Production S3 client not yet implemented.")

    else:
        raise ValueError(f"Unknown environment: {settings.env}")


# ── Convenience: log active environment on import 
logger.info(f"[Infrastructure] Active environment: {settings.env.value}")
