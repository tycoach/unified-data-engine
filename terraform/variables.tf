# terraform/variables.tf

variable "project_id" {
  description = "GCP project ID — matches MiniSky's local-dev-project"
  type        = string
  default     = "local-dev-project"
}

variable "region" {
  description = "GCP region"
  type        = string
  default     = "us-central1"
}

variable "environment" {
  description = "local | production"
  type        = string
  default     = "local"
}

variable "minisky_endpoint" {
  description = "MiniSky API gateway endpoint. Empty string = real GCP."
  type        = string
  default     = "http://localhost:8080"
}