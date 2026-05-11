# data-generator/scenarios/products.py
# Publishes synthetic product records to MiniSky Pub/Sub
# Run: python data-generator/scenarios/products.py

import json
import random
import base64
import logging
import urllib.request
from datetime import datetime, timezone

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PROJECT_ID = "local-dev-project"
MINISKY_BASE = "http://localhost:8080"

CATEGORIES = ["Electronics", "Clothing", "Food", "Books", "Tools", "Sports"]


def generate_product(product_id: int) -> dict:
    return {
        "product_id": f"P-{product_id:04d}",
        "sku": f"SKU-{product_id:06d}",
        "name": f"Product {product_id}",
        "category": random.choice(CATEGORIES),
        "price": round(random.uniform(5.0, 999.99), 2),
        "in_stock": random.choice([True, False]),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def publish_to_minisky(topic: str, records: list[dict]):
    url = f"{MINISKY_BASE}/v1/projects/{PROJECT_ID}/topics/{topic}:publish"
    messages = [
        {"data": base64.b64encode(json.dumps(r).encode()).decode()}
        for r in records
    ]
    payload = json.dumps({"messages": messages}).encode()
    req = urllib.request.Request(
        url, data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        result = json.loads(resp.read())
        ids = result.get("messageIds", [])
        logger.info(
            f"[Generator]---- Published {len(records)} products "
            f"to {topic} — IDs: {ids[:3]}..."
        )


def run(num_products: int = 50):
    # Provision topic + subscription if not exists
    for url, data in [
        (f"{MINISKY_BASE}/v1/projects/{PROJECT_ID}/topics/raw.products",
         "{}"),
        (f"{MINISKY_BASE}/v1/projects/{PROJECT_ID}/subscriptions/raw.products-sub",
         json.dumps({
             "topic": f"projects/{PROJECT_ID}/topics/raw.products",
             "ackDeadlineSeconds": 60,
         })),
    ]:
        try:
            req = urllib.request.Request(
                url, data=data.encode(),
                headers={"Content-Type": "application/json"},
                method="PUT",
            )
            urllib.request.urlopen(req)
        except Exception:
            pass  # already exists

    products = [generate_product(i) for i in range(1, num_products + 1)]
    publish_to_minisky("raw.products", products)
    logger.info(f"[Generator] ---- Done — {num_products} products published")


if __name__ == "__main__":
    run(num_products=50)