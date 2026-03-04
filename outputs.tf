output "seed_test_drift_enabled" {
  description = "Whether Terraform intentionally provisions drift for demo users."
  value       = var.seed_test_drift
}

output "selected_test_case" {
  description = "The active named test case used to seed intentional drift."
  value       = local.selected_test_case_name
}

output "expected_departments" {
  description = "The correct department assignment for each test user."
  value = {
    for user, item in local.user_map :
    user => item.dept
  }
}

output "provisioned_groups" {
  description = "The group memberships Terraform actually provisions for each test user."
  value = {
    for user, item in local.provisioned_user_state :
    user => item.groups
  }
}
