# engine/staging/staging_writer.py
# Writes clean records to BigQuery raw_staging dataset on MiniSky
# raw_staging.{pipeline_id}_staged is the dbt source table
# Uses BigQuery REST API directly — no GCP credentials needed for MiniSky
#
# Flow:
#   EdgeCaseHandler → clean_records → StagingWriter → BigQuery raw_staging
#                                                   → dbt reads from here

import json
import logging
import urllib.request
import urllib.error
from datetime import datetime, timezone

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MINISKY_BASE = "http://localhost:8080"
PROJECT_ID = "local-dev-project"


class StagingWriter:
    """
    Writes clean records to BigQuery raw_staging.{pipeline_id}_staged.
    """

    def __init__(self, pipeline_id: str, project_id: str = PROJECT_ID):
        self.pipeline_id = pipeline_id
        self.project_id = project_id
        self.dataset = "raw_staging"
        self.table = f"{pipeline_id}_staged"
        self.table_ref = f"{project_id}/{self.dataset}/{self.table}"

        logger.info(
            f"[StagingWriter] Initialized for "
            f"{self.dataset}.{self.table}"
        )

    def _bq_request(self, method: str, path: str, body: dict = None) -> dict:
        """Make a request to BigQuery REST API on MiniSky."""
        url = f"{MINISKY_BASE}/bigquery/v2/{path}"
        data = json.dumps(body).encode() if body else None
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method=method,
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = resp.read().decode().strip()
                return json.loads(body) if body else {}
        except urllib.error.HTTPError as e:
            err_body = e.read().decode()
            logger.error(f"[StagingWriter] HTTP {e.code}: {err_body}")
            raise
        except Exception as e:
            logger.error(f"[StagingWriter] Request error: {e}")
            raise

    def ensure_table(self, locked_schema: dict):
        """
        Ensure the staging table exists in BigQuery.
        """
        path = (
            f"projects/{self.project_id}/datasets/{self.dataset}"
            f"/tables/{self.table}"
        )

        try:
            self._bq_request("GET", path)
            logger.debug(f"[StagingWriter] Table {self.table} exists.")
            return
        except urllib.error.HTTPError as e:
            if e.code != 404:
                raise

        # Table doesn't exist — create it
        schema_fields = self._build_bq_schema(locked_schema)

        # Always add batch_id and ingestion_time columns
        schema_fields.extend([
            {"name": "batch_id", "type": "STRING", "mode": "REQUIRED"},
            {"name": "_ingested_at", "type": "TIMESTAMP", "mode": "NULLABLE"},
        ])

        table_body = {
            "tableReference": {
                "projectId": self.project_id,
                "datasetId": self.dataset,
                "tableId": self.table,
            },
            "schema": {"fields": schema_fields},
        }

        self._bq_request(
            "POST",
            f"projects/{self.project_id}/datasets/{self.dataset}/tables",
            table_body,
        )
        logger.info(f"[StagingWriter] ✅ Created table {self.dataset}.{self.table}")

    def write(
        self,
        records: list[dict],
        batch_id: str,
        locked_schema: dict,
    ) -> int:
        """
        Write clean records to BigQuery staging table.
    
        """
        if not records:
            logger.info("[StagingWriter] No records to write.")
            return 0

        # Ensure table exists
        self.ensure_table(locked_schema)

        # Inject batch_id and ingestion timestamp into every record
        ingested_at = datetime.now(timezone.utc).isoformat()
        rows = []
        for record in records:
            row = {
                k: v for k, v in record.items()
                if not k.startswith("_")  # strip consumer meta
            }
            row["batch_id"] = batch_id
            row["_ingested_at"] = ingested_at
            rows.append({"insertId": f"{batch_id}-{record.get(self._natural_key(locked_schema), len(rows))}", "json": row})

        # BigQuery insertAll (streaming insert)
        path = (
            f"projects/{self.project_id}/datasets/{self.dataset}"
            f"/tables/{self.table}/insertAll"
        )

        body = {"rows": rows, "skipInvalidRows": False}
        result = self._bq_request("POST", path, body)

        errors = result.get("insertErrors", [])
        if errors:
            logger.error(f"[StagingWriter] Insert errors: {errors}")
            raise RuntimeError(f"BigQuery insert errors: {errors}")

        logger.info(
            f"[StagingWriter] Wrote {len(rows)} rows to "
            f"{self.dataset}.{self.table} (batch={batch_id})"
        )
        return len(rows)

    def write_quarantine(self, dirty_records: list[dict], batch_id: str):
        """
        Write dirty records to BigQuery quarantine dataset.
        """
        if not dirty_records:
            return

        quarantine_table = f"{self.pipeline_id}_quarantine"
        ingested_at = datetime.now(timezone.utc).isoformat()

        rows = [
            {
                "insertId": f"q-{batch_id}-{i}",
                "json": {
                    "pipeline_id": self.pipeline_id,
                    "batch_id": batch_id,
                    "quarantined_at": ingested_at,
                    "failure_reason": record.get("_failure_reason", "UNKNOWN"),
                    "raw_record": json.dumps(
                        {k: v for k, v in record.items() if not k.startswith("_")}
                    ),
                },
            }
            for i, record in enumerate(dirty_records)
        ]

        # Ensure quarantine table exists
        self._ensure_quarantine_table(quarantine_table)

        path = (
            f"projects/{self.project_id}/datasets/quarantine"
            f"/tables/{quarantine_table}/insertAll"
        )
        self._bq_request("POST", path, {"rows": rows})
        logger.info(
            f"[StagingWriter] 🚨 Quarantined {len(dirty_records)} records → "
            f"quarantine.{quarantine_table}"
        )

    def _ensure_quarantine_table(self, table_name: str):
        """Create quarantine table if it doesn't exist."""
        path = f"projects/{self.project_id}/datasets/quarantine/tables/{table_name}"
        try:
            self._bq_request("GET", path)
            return
        except urllib.error.HTTPError as e:
            if e.code != 404:
                raise

        schema_fields = [
            {"name": "pipeline_id",    "type": "STRING",    "mode": "REQUIRED"},
            {"name": "batch_id",       "type": "STRING",    "mode": "REQUIRED"},
            {"name": "quarantined_at", "type": "TIMESTAMP", "mode": "NULLABLE"},
            {"name": "failure_reason", "type": "STRING",    "mode": "NULLABLE"},
            {"name": "raw_record",     "type": "STRING",    "mode": "NULLABLE"},
        ]

        self._bq_request(
            "POST",
            f"projects/{self.project_id}/datasets/quarantine/tables",
            {
                "tableReference": {
                    "projectId": self.project_id,
                    "datasetId": "quarantine",
                    "tableId": table_name,
                },
                "schema": {"fields": schema_fields},
            },
        )
        logger.info(f"[StagingWriter] Created quarantine table: {table_name}")

    def _build_bq_schema(self, locked_schema: dict) -> list[dict]:
        """Convert UDE schema fields to BigQuery schema fields."""
        type_map = {
            "string":   "STRING",
            "integer":  "INTEGER",
            "float":    "FLOAT",
            "boolean":  "BOOLEAN",
            "date":     "DATE",
            "datetime": "TIMESTAMP",
        }
        fields = []
        for name, meta in locked_schema["fields"].items():
            fields.append({
                "name": name,
                "type": type_map.get(meta["type"], "STRING"),
                "mode": "NULLABLE" if meta.get("nullable", True) else "REQUIRED",
            })
        return fields

    def _natural_key(self, locked_schema: dict) -> str:
        """Guess the natural key from the schema — first non-nullable field."""
        for name, meta in locked_schema["fields"].items():
            if not meta.get("nullable", True):
                return name
        return "id"