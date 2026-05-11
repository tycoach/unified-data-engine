# engine/ingestion/consumer.py
# Pub/Sub consumer — replaces Kafka in UDE v2
# Uses REST API directly — no GCP credentials needed for MiniSky
# Pulls messages in 30-second micro-batch windows

import json
import time
import base64
import logging
import urllib.request
import urllib.error
from datetime import datetime, timezone

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MINISKY_BASE = "http://localhost:8080"


class MicroBatchConsumer:
    """
    Pulls messages from a Pub/Sub subscription in 30-second windows.
    """

    def __init__(
        self,
        project_id: str,
        subscription_id: str,
        batch_window_seconds: int = 30,
    ):
        self.project_id = project_id
        self.subscription_id = subscription_id
        self.batch_window_seconds = batch_window_seconds
        self.subscription_path = (
            f"projects/{project_id}/subscriptions/{subscription_id}"
        )
        self.pull_url = f"{MINISKY_BASE}/v1/{self.subscription_path}:pull"
        self.ack_url = f"{MINISKY_BASE}/v1/{self.subscription_path}:acknowledge"
        self.nack_url = (
            f"{MINISKY_BASE}/v1/{self.subscription_path}:modifyAckDeadline"
        )

        logger.info(f"[Consumer] Initialized: {self.subscription_path}")
        logger.info(f"[Consumer] Batch window: {batch_window_seconds}s")

    def _post(self, url: str, payload: dict) -> dict:
        """POST to MiniSky REST API. Returns {} on empty or error response."""
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                body = resp.read().decode().strip()
                if not body or body == "{}":
                    return {}
                return json.loads(body)
        except urllib.error.HTTPError as e:
            body = e.read().decode()
            logger.error(f"[Consumer] HTTP {e.code}: {body}")
            return {}
        except Exception as e:
            logger.error(f"[Consumer] Request error: {e}")
            return {}

    def pull_batch(self) -> tuple[list[dict], list[str]]:
        """
        Pull all available messages within the batch window.
        """
        messages = []
        ack_ids = []
        deadline = time.time() + self.batch_window_seconds

        logger.info(
            f"[Consumer] Opening {self.batch_window_seconds}s batch window..."
        )

        while time.time() < deadline:
            result = self._post(self.pull_url, {"maxMessages": 1000})
            received = result.get("receivedMessages", [])

            if not received:
                time.sleep(1)
                continue

            for msg in received:
                ack_ids.append(msg["ackId"])
                try:
                    raw = msg["message"]["data"]
                    decoded = base64.b64decode(raw).decode("utf-8")
                    payload = json.loads(decoded)

                    # Skip malformed stub messages
                    if len(payload) < 2:
                        logger.debug(f"[Consumer] Skipping stub: {payload}")
                        continue

                    payload["_message_id"] = msg["message"].get("messageId", "")
                    payload["_publish_time"] = msg["message"].get(
                        "publishTime",
                        datetime.now(timezone.utc).isoformat(),
                    )
                    messages.append(payload)

                except Exception as e:
                    logger.warning(f"[Consumer] Skipping bad message: {e}")

        logger.info(
            f"[Consumer] Batch closed — {len(messages)} messages collected."
        )
        return messages, ack_ids

    def ack(self, ack_ids: list[str]):
        """
        Acknowledge messages after successful processing.
        """
        if not ack_ids:
            return
        self._post(self.ack_url, {"ackIds": ack_ids})
        logger.info(f"[Consumer] Acked {len(ack_ids)} messages.")

    def nack(self, ack_ids: list[str]):
        """
        Nack messages — redelivered on next pull cycle.
        """
        if not ack_ids:
            return
        self._post(
            self.nack_url,
            {"ackIds": ack_ids, "ackDeadlineSeconds": 0},
        )
        logger.info(
            f"[Consumer] Nacked {len(ack_ids)} messages — will redeliver."
        )