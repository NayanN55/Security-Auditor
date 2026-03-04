terraform {
  required_version = ">= 1.5.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region  = var.aws_region
  profile = var.aws_profile
}

locals {
  config               = yamldecode(file("${path.module}/config/hierarchy.yaml"))
  test_case_config     = yamldecode(file("${path.module}/config/test_cases.yaml"))
  available_test_cases = lookup(local.test_case_config, "cases", {})
  selected_test_case_name = coalesce(
    var.test_case_name,
    lookup(local.test_case_config, "default_case", null)
  )
  selected_test_case = local.available_test_cases[local.selected_test_case_name]

  company = lookup(local.config, "company", "Company")

  departments_raw = lookup(local.config, "departments", {})
  departments = {
    for dept_name, cfg in local.departments_raw :
    dept_name => {
      group_name = lookup(cfg, "group_name", dept_name)
      policies   = lookup(cfg, "policies", [])
      users      = lookup(cfg, "users", [])
    }
  }

  user_overrides = lookup(local.config, "user_overrides", {})
  seed_overrides = lookup(local.selected_test_case, "drift", {})
}
