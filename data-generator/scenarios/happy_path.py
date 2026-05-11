# data-generator/scenarios/happy_path.py
# Publishes synthetic customer + order records to MiniSky Pub/Sub
# Uses REST API directly — no GCP auth required for MiniSky

import json
import random
import time
import base64
import logging
import urllib.request

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PROJECT_ID = "local-dev-project"
MINISKY_BASE = "http://localhost:8080"

CITIES = ["Lagos", "Abuja", "London", "New York", "Nairobi", "Accra", "Dubai"]
TIERS = ["free", "pro", "enterprise"]
COUNTRIES = ["NG", "UK", "US", "KE", "GH", "AE"]


def generate_customer(customer_id: int) -> dict:
    from datetime import datetime
    return {
        "customer_id": f"C-{customer_id:04d}",
        "email": f"user{customer_id}@example.com",
        "city": random.choice(CITIES),
        "country": random.choice(COUNTRIES),
        "tier": random.choice(TIERS),
        "updated_at": datetime.utcnow().isoformat(),
    }


def generate_order(order_id: int, customer_id: int) -> dict:
    from datetime import datetime
    return {
        "order_id": f"O-{order_id:06d}",
        "customer_id": f"C-{customer_id:04d}",
        "amount": round(random.uniform(10.0, 5000.0), 2),
        "currency": "USD",
        "status": random.choice(["pending", "confirmed", "shipped", "delivered"]),
        "created_at": datetime.utcnow().isoformat(),
    }


def publish_to_minisky(topic: str, records: list[dict]):
    """
    Publish records to MiniSky Pub/Sub via REST.
    """
    url = f"{MINISKY_BASE}/v1/projects/{PROJECT_ID}/topics/{topic}:publish"

    messages = [
        {"data": base64.b64encode(json.dumps(r).encode()).decode()}
        for r in records
    ]
    payload = json.dumps({"messages": messages}).encode()

    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req) as resp:
            result = json.loads(resp.read())
            msg_ids = result.get("messageIds", [])
            logger.info(f"[Generator]  Published {len(records)} records to {topic} — IDs: {msg_ids[:3]}...")
    except Exception as e:
        logger.error(f"[Generator]  Failed to publish to {topic}: {e}")
        raise


def run(num_customers: int = 100, num_orders: int = 200, repeat: int = 1):
    for run_num in range(repeat):
        logger.info(f"[Generator] --- Run {run_num + 1}/{repeat} ---")

        customers = [generate_customer(i) for i in range(1, num_customers + 1)]
        publish_to_minisky("raw.customers", customers)

        orders = [
            generate_order(i, random.randint(1, num_customers))
            for i in range(1, num_orders + 1)
        ]
        publish_to_minisky("raw.orders", orders)

        if repeat > 1 and run_num < repeat - 1:
            logger.info("[Generator] Waiting 5s before next run...")
            time.sleep(5)

    logger.info("[Generator]  All runs complete.")


if __name__ == "__main__":
    run(num_customers=100, num_orders=200, repeat=1)