"""
local_queue.py
--------------
File-based message queue for local development.
Mimics SQS behaviour: write, poll, acknowledge, dead-letter.
Agents never know whether they are talking to a file or SQS.

Directory structure:
    sda_queues/
        {queue_name}/
            pending/      ← messages waiting to be consumed
            processing/   ← messages currently being handled
            complete/     ← processed messages (archive)
            dead/         ← failed messages that exceeded retries
"""

import json
import uuid
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List

from config.settings import settings
from core.enums import QueueName, MessageStatus
from core.messages import PipelineMessage

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class LocalQueue:
    """
    File-system backed queue that behaves like SQS.
    Each message is a JSON file. State is determined by which subfolder it lives in.
    """

    def __init__(self, queue_path: Optional[str] = None):
        self.base_path = Path(queue_path or settings.local.queue_path)
        self._init_queues()
        logger.info(f"[LocalQueue] Initialised at {self.base_path}")

    def _init_queues(self):
        """Create all queue directories on startup."""
        for queue in QueueName:
            for state in ["pending", "processing", "complete", "dead"]:
                (self.base_path / queue.value / state).mkdir(parents=True, exist_ok=True)
        logger.info("[LocalQueue] All queue directories initialised.")

    def _msg_path(self, queue: QueueName, state: str, message_id: str) -> Path:
        return self.base_path / queue.value / state / f"{message_id}.json"

    # ── Send 

    def send(self, message: PipelineMessage) -> str:
        """
        Place a message on the queue.
        Returns the message_id.
        """
        message.status = MessageStatus.PENDING
        path = self._msg_path(message.queue, "pending", message.message_id)
        path.write_text(message.model_dump_json(indent=2))
        logger.info(
            f"[LocalQueue] → {message.queue.value} | "
            f"msg={message.message_id[:8]} | "
            f"{message.source_agent.value} → {message.target_agent.value}"
        )
        return message.message_id

    # ── Poll 

    def poll(self, queue: QueueName, max_messages: int = 1) -> List[PipelineMessage]:
        """
        Poll for pending messages. Moves them to processing/ on receipt.
        Returns up to max_messages messages.
        """
        pending_dir = self.base_path / queue.value / "pending"
        files = sorted(pending_dir.glob("*.json"))[:max_messages]

        if not files:
            return []

        messages = []
        for file in files:
            try:
                data = json.loads(file.read_text())
                message = PipelineMessage.model_validate(data)
                message.mark_processing()

                # Move to processing/
                processing_path = self._msg_path(queue, "processing", message.message_id)
                file.rename(processing_path)
                processing_path.write_text(message.model_dump_json(indent=2))

                messages.append(message)
                logger.info(
                    f"[LocalQueue] ← {queue.value} | "
                    f"msg={message.message_id[:8]} | "
                    f"processing"
                )
            except Exception as e:
                logger.error(f"[LocalQueue] Failed to poll message {file.name}: {e}")

        return messages

    # ── Acknowledge 

    def acknowledge(self, message: PipelineMessage):
        """
        Mark a message as successfully processed.
        Moves it from processing/ to complete/.
        """
        message.mark_complete()
        processing_path = self._msg_path(message.queue, "processing", message.message_id)
        complete_path = self._msg_path(message.queue, "complete", message.message_id)

        if processing_path.exists():
            processing_path.rename(complete_path)
            complete_path.write_text(message.model_dump_json(indent=2))
        else:
            # Already moved or never in processing — write to complete directly
            complete_path.write_text(message.model_dump_json(indent=2))

        logger.info(
            f"[LocalQueue] ✓ {message.queue.value} | "
            f"msg={message.message_id[:8]} | "
            f"complete"
        )

    # ── Fail / Retry 

    def fail(self, message: PipelineMessage, error_message: str):
        """
        Mark a message as failed.
        If retries remain, put it back in pending/.
        If retries exhausted, move to dead/.
        """
        from core.messages import PipelineError
        from core.enums import AgentName

        error = PipelineError(
            error_type="processing_error",
            error_message=error_message,
            agent=message.target_agent,
            recoverable=message.can_retry(),
            retry_suggested=message.can_retry(),
        )
        message.mark_failed(error)

        processing_path = self._msg_path(message.queue, "processing", message.message_id)

        if message.can_retry():
            pending_path = self._msg_path(message.queue, "pending", message.message_id)
            if processing_path.exists():
                processing_path.rename(pending_path)
            pending_path.write_text(message.model_dump_json(indent=2))
            logger.warning(
                f"[LocalQueue] ↺ {message.queue.value} | "
                f"msg={message.message_id[:8]} | "
                f"retry {message.retry_count}/{message.max_retries}"
            )
        else:
            message.to_dead_letter()
            dead_path = self._msg_path(QueueName.DEAD_LETTER, "pending", message.message_id)
            if processing_path.exists():
                processing_path.unlink()
            dead_path.write_text(message.model_dump_json(indent=2))
            logger.error(
                f"[LocalQueue] ✗ dead-letter | "
                f"msg={message.message_id[:8]} | "
                f"source={message.source_agent.value} | "
                f"error={error_message}"
            )

    # ── Orchestration Queue (pass-through today) 

    def send_to_orchestration(self, message: PipelineMessage) -> str:
        """
        Send a message to the orchestration queue.
        Today this is a pass-through — the orchestration slot exists but is not active.
        When the orchestration agent is activated, this method routes to it.
        """
        message.queue = QueueName.ORCHESTRATION_IN
        return self.send(message)

    def poll_orchestration_out(self) -> List[PipelineMessage]:
        """Poll the orchestration output queue."""
        return self.poll(QueueName.ORCHESTRATION_OUT)

    # ── Inspect 

    def queue_depth(self, queue: QueueName) -> dict:
        """Return count of messages in each state for a queue."""
        result = {}
        for state in ["pending", "processing", "complete", "dead"]:
            state_dir = self.base_path / queue.value / state
            result[state] = len(list(state_dir.glob("*.json")))
        return result

    def all_queue_depths(self) -> dict:
        return {q.value: self.queue_depth(q) for q in QueueName}

    def purge_complete(self, queue: QueueName):
        """Clear completed messages from a queue (housekeeping)."""
        complete_dir = self.base_path / queue.value / "complete"
        count = 0
        for f in complete_dir.glob("*.json"):
            f.unlink()
            count += 1
        if count:
            logger.info(f"[LocalQueue] Purged {count} complete messages from {queue.value}")

    def reset_queue(self, queue: QueueName):
        """Wipe all messages from a queue. Use in tests only."""
        for state in ["pending", "processing", "complete", "dead"]:
            state_dir = self.base_path / queue.value / state
            shutil.rmtree(state_dir, ignore_errors=True)
            state_dir.mkdir(parents=True, exist_ok=True)
        logger.warning(f"[LocalQueue] Reset queue: {queue.value}")


# ── Singleton 
_local_queue: Optional[LocalQueue] = None

def get_local_queue() -> LocalQueue:
    global _local_queue
    if _local_queue is None:
        _local_queue = LocalQueue()
    return _local_queue
