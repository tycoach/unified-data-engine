# terraform/outputs.tf

output "minisky_endpoint" {
  value       = "http://localhost:8080"
  description = "MiniSky API gateway — all GCP SDK calls route here"
}

output "pubsub_customers_topic" {
  value = google_pubsub_topic.customers.name
}

output "pubsub_orders_topic" {
  value = google_pubsub_topic.orders.name
}

output "bigquery_staging_dataset" {
  value = google_bigquery_dataset.raw_staging.dataset_id
}
