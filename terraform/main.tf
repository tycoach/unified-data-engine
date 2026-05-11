# terraform/main.tf

terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }
}

provider "google" {
  project      = var.project_id
  region       = var.region
  access_token = "local-minisky-token"

  # Override all API endpoints to hit MiniSky
  batching {
    enable_batching = false
  }
}
