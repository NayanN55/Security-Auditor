locals {
  dept_policy_pairs = flatten([
    for dept_name, cfg in local.departments : [
      for policy in cfg.policies : {
        dept   = dept_name
        policy = policy
      }
    ]
  ])

  dept_users = flatten([
    for dept_name, cfg in local.departments : [
      for user in cfg.users : {
        dept = dept_name
        user = user
      }
    ]
  ])

  user_map = {
    for item in local.dept_users :
    item.user => item
  }

  expected_user_policies = {
    for user, item in local.user_map :
    user => lookup(lookup(local.user_overrides, user, {}), "extra_policies", [])
  }

  seed_override_by_user = {
    for user, item in local.user_map :
    user => lookup(local.seed_overrides, user, {})
  }

  provisioned_user_state = {
    for user, item in local.user_map :
    user => {
      groups = (
        var.seed_test_drift &&
        lookup(local.seed_override_by_user[user], "groups", null) != null
        ) ? sort(distinct([
          for dept in local.seed_override_by_user[user].groups :
          local.departments[dept].group_name
      ])) : [local.departments[item.dept].group_name]

      extra_policies = (
        var.seed_test_drift &&
        lookup(local.seed_override_by_user[user], "extra_policies", null) != null
      ) ? sort(distinct(local.seed_override_by_user[user].extra_policies)) : sort(distinct(local.expected_user_policies[user]))
    }
  }

  provisioned_user_policy_pairs = flatten([
    for user, cfg in local.provisioned_user_state : [
      for policy in cfg.extra_policies : {
        user   = user
        policy = policy
      }
    ]
  ])
}

resource "aws_iam_group" "department" {
  for_each = local.departments
  name     = each.value.group_name
}

resource "aws_iam_group_policy_attachment" "department" {
  for_each = {
    for pair in local.dept_policy_pairs :
    "${pair.dept}-${pair.policy}" => pair
  }

  group      = aws_iam_group.department[each.value.dept].name
  policy_arn = each.value.policy
}

resource "aws_iam_user" "user" {
  for_each = local.user_map
  name     = each.key
}

resource "aws_iam_user_group_membership" "department" {
  for_each = local.provisioned_user_state

  user   = aws_iam_user.user[each.key].name
  groups = each.value.groups
}

resource "aws_iam_user_policy_attachment" "extra" {
  for_each = {
    for pair in local.provisioned_user_policy_pairs :
    "${pair.user}-${pair.policy}" => pair
  }

  user       = aws_iam_user.user[each.value.user].name
  policy_arn = each.value.policy
}
