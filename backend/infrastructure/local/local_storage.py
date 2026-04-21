"""
local_storage.py
----------------
Local filesystem mock for S3.
Stores large payloads (enrichment evidence, full email sequences)
that would be too large for the database.

In production, swap for the S3 client — same interface.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from backend.config.settings import settings

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class LocalStorage:
    """
    Filesystem-backed object storage. Mimics S3 put/get/delete.
    Files are stored at: sda_s3_mock/{key}
    """

    def __init__(self, base_path: Optional[str] = None):
        self.base_path = Path(base_path or settings.local.s3_mock_path)
        self.base_path.mkdir(parents=True, exist_ok=True)
        logger.info(f"[LocalStorage] Initialised at {self.base_path}")

    def put(self, key: str, data: Any) -> str:
        """
        Store an object. Data can be dict, list, or string.
        Returns the key.
        Key format: {campaign_id}/{agent}/{filename}
        e.g. "abc123/enrichment/lead_001_evidence.json"
        """
        path = self.base_path / key
        path.parent.mkdir(parents=True, exist_ok=True)

        if isinstance(data, (dict, list)):
            path.write_text(json.dumps(data, indent=2))
        else:
            path.write_text(str(data))

        logger.debug(f"[LocalStorage] PUT {key}")
        return key

    def get(self, key: str) -> Optional[Any]:
        """Retrieve an object by key. Returns parsed JSON or raw string."""
        path = self.base_path / key
        if not path.exists():
            logger.warning(f"[LocalStorage] GET {key} — not found")
            return None
        content = path.read_text()
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return content

    def delete(self, key: str):
        """Delete an object by key."""
        path = self.base_path / key
        if path.exists():
            path.unlink()
            logger.debug(f"[LocalStorage] DELETE {key}")

    def exists(self, key: str) -> bool:
        return (self.base_path / key).exists()

    def list_keys(self, prefix: str) -> list:
        """List all keys with a given prefix."""
        prefix_path = self.base_path / prefix
        if not prefix_path.exists():
            return []
        return [
            str(p.relative_to(self.base_path))
            for p in prefix_path.rglob("*")
            if p.is_file()
        ]

    # ── Convenience helpers 

    def put_enrichment_evidence(self, campaign_id: str, lead_id: str, evidence: list) -> str:
        key = f"{campaign_id}/enrichment/{lead_id}_evidence.json"
        return self.put(key, evidence)

    def get_enrichment_evidence(self, campaign_id: str, lead_id: str) -> Optional[list]:
        key = f"{campaign_id}/enrichment/{lead_id}_evidence.json"
        return self.get(key)

    def put_email_sequence(self, campaign_id: str, lead_id: str, sequence: dict) -> str:
        key = f"{campaign_id}/emails/{lead_id}_sequence.json"
        return self.put(key, sequence)

    def put_pipeline_payload(self, campaign_id: str, message_id: str, payload: dict) -> str:
        """Store large pipeline message payloads."""
        key = f"{campaign_id}/messages/{message_id}_payload.json"
        return self.put(key, payload)

    # ── Future: RAG template storage slot 
    # These will eventually go to S3 Vectors + SageMaker

    def put_email_template(self, template_id: str, template: dict) -> str:
        """Future: store email templates for RAG retrieval."""
        key = f"templates/{template_id}.json"
        return self.put(key, template)

    def get_email_template(self, template_id: str) -> Optional[dict]:
        """Future: retrieve email template for RAG."""
        key = f"templates/{template_id}.json"
        return self.get(key)


# ── Singleton 
_local_storage: Optional[LocalStorage] = None

def get_local_storage() -> LocalStorage:
    global _local_storage
    if _local_storage is None:
        _local_storage = LocalStorage()
    return _local_storage
