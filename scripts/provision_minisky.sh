#!/bin/bash
MINISKY="http://localhost:8080"
PROJECT="local-dev-project"

echo "🚀 Provisioning UDE v2 resources on MiniSky..."

echo "📦 Creating BigQuery datasets..."
for dataset in raw_staging snapshots marts quarantine staging; do
  curl -s -X POST \
    "$MINISKY/bigquery/v2/projects/$PROJECT/datasets" \
    -H "Content-Type: application/json" \
    -d "{\"datasetReference\": {\"datasetId\": \"$dataset\", \"projectId\": \"$PROJECT\"}}"
  echo "  ✅ $dataset"
done

echo "📨 Creating Pub/Sub topics..."
for topic in "raw.customers" "raw.orders"; do
  curl -s -X PUT \
    "$MINISKY/v1/projects/$PROJECT/topics/$topic" \
    -H "Content-Type: application/json" \
    -d "{}"
  echo "  ✅ $topic"
done

echo "📬 Creating Pub/Sub subscriptions..."
for topic in "raw.customers" "raw.orders"; do
  sub="${topic}-sub"
  curl -s -X PUT \
    "$MINISKY/v1/projects/$PROJECT/subscriptions/$sub" \
    -H "Content-Type: application/json" \
    -d "{\"topic\": \"projects/$PROJECT/topics/$topic\", \"ackDeadlineSeconds\": 60}"
  echo "  ✅ $sub"
done

echo ""
echo "✅ Done. Verifying..."
echo ""
echo "BigQuery datasets:"
curl -s "$MINISKY/bigquery/v2/projects/$PROJECT/datasets" | python3 -c "
import sys,json
data=json.load(sys.stdin)
[print('  -', d['datasetReference']['datasetId']) for d in data.get('datasets',[])]
"

echo "Pub/Sub topics:"
curl -s "$MINISKY/v1/projects/$PROJECT/topics" | python3 -c "
import sys,json
data=json.load(sys.stdin)
[print('  -', t['name']) for t in data.get('topics',[])]
"
