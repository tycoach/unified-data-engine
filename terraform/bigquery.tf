# terraform/bigquery.tf
# BigQuery datasets — replaces DuckDB target store in UDE v2

resource "google_bigquery_dataset" "raw_staging" {
  dataset_id  = "raw_staging"
  description = "Staging area — clean records written here before dbt runs"
  location    = "US"
  project     = var.project_id
}

resource "google_bigquery_dataset" "snapshots" {
  dataset_id  = "snapshots"
  description = "dbt SCD Type 2 snapshot tables"
  location    = "US"
  project     = var.project_id
}

resource "google_bigquery_dataset" "marts" {
  dataset_id  = "marts"
  description = "dbt SCD Type 1 incremental mart tables"
  location    = "US"
  project     = var.project_id
}

resource "google_bigquery_dataset" "quarantine" {
  dataset_id  = "quarantine"
  description = "Dirty records that failed edge case gate"
  location    = "US"
  project     = var.project_id
}
