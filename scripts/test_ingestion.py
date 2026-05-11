# scripts/test_ingestion.py
# Quick end-to-end test of Phase 2 ingestion
# Publishes records then immediately pulls them back
# Run: python scripts/test_ingestion.py

import sys
import json
import logging

sys.path.insert(0, ".")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def test_publish():
    logger.info("===  Publishing test records ===")
    from data-generator.scenarios.happy_path import run
    run(num_customers=10, num_orders=20, repeat=1)


def test_pull():
    logger.info("===  Pulling records back (5s window) ===")
    from engine.ingestion.consumer import MicroBatchConsumer
    from engine.ingestion.offset_manager import OffsetManager

    consumer = MicroBatchConsumer(
        project_id="local-dev-project",
        subscription_id="raw.customers-sub",
        batch_window_seconds=5,  # short window for testing
    )

    offset_mgr = OffsetManager(pipeline_id="customers")
    batch_id = offset_mgr.open_batch()
    logger.info(f"Batch ID: {batch_id}")

    messages, ack_ids = consumer.pull_batch()

    if messages:
        logger.info(f" Pulled {len(messages)} messages")
        logger.info(f"Sample record: {json.dumps(messages[0], indent=2)}")
        consumer.ack(ack_ids)
        offset_mgr.complete_batch(len(messages))
        logger.info("Acked and batch marked complete")
    else:
        logger.warning(" No messages received — check MiniSky is running")

    consumer.close() if hasattr(consumer, "close") else None


if __name__ == "__main__":
    test_publish()
    test_pull()
    logger.info("\ningestion test complete.")