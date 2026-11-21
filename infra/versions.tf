terraform {
  required_version = "~> 1.9.8"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.50"
    }
    google-beta = {
      source  = "hashicorp/google-beta"
      version = "~> 6.50"
    }
  }

  backend "gcs" {
    bucket = "onolys-tfstate"
    prefix = "infra"
  }
}

provider "google" {
  project               = var.project
  region                = var.region
  user_project_override = true
  billing_project       = var.project
}

provider "google-beta" {
  project               = var.project
  region                = var.region
  user_project_override = true
  billing_project       = var.project
}
