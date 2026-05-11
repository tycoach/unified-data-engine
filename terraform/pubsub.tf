# terraform/pubsub.tf
# Pub/Sub topics + subscriptions — replaces Kafka in UDE v2

# customers topic
resource "google_pubsub_topic" "customers" {
  name    = "raw.customers"
  project = var.project_id
}

resource "google_pubsub_subscription" "customers" {
  name    = "raw.customers-sub"
  topic   = google_pubsub_topic.customers.name
  project = var.project_id

  ack_deadline_seconds = 60

  # Retain unacked messages for 24 hours
  message_retention_duration = "86400s"
}

# orders topic
resource "google_pubsub_topic" "orders" {
  name    = "raw.orders"
  project = var.project_id
}

resource "google_pubsub_subscription" "orders" {
  name    = "raw.orders-sub"
  topic   = google_pubsub_topic.orders.name
  project = var.project_id

  ack_deadline_seconds = 60
  message_retention_duration = "86400s"
}
