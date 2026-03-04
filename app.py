from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import boto3
from botocore.exceptions import ClientError, NoCredentialsError, PartialCredentialsError
from dotenv import load_dotenv
import yaml

ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG = ROOT / "config" / "hierarchy.yaml"
DEFAULT_CASES_CONFIG = ROOT / "config" / "test_cases.yaml"
DEFAULT_ARTIFACTS = ROOT / "artifacts"


def load_config(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Config not found: {path}")
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError("Config must be a YAML mapping.")
    return data


def normalize_config(data: dict) -> dict:
    company = data.get("company", "Company")
    departments_raw = data.get("departments") or {}
    if not isinstance(departments_raw, dict) or not departments_raw:
        raise ValueError("Config must include a departments mapping.")

    departments: dict[str, dict] = {}
    user_to_dept: dict[str, str] = {}
    for dept_name, cfg in departments_raw.items():
        cfg = cfg or {}
        group_name = cfg.get("group_name", dept_name)
        policies = list(cfg.get("policies", []) or [])
        users = list(cfg.get("users", []) or [])
        departments[dept_name] = {
            "group_name": group_name,
            "policies": policies,
            "users": users,
        }
        for user in users:
            if user in user_to_dept:
                raise ValueError(f"User '{user}' is listed in multiple departments.")
            user_to_dept[user] = dept_name

    user_overrides = data.get("user_overrides") or {}
    if not isinstance(user_overrides, dict):
        raise ValueError("user_overrides must be a mapping if present.")

    user_extra_policies: dict[str, set[str]] = {}
    for user, cfg in user_overrides.items():
        cfg = cfg or {}
        user_extra_policies[user] = set(cfg.get("extra_policies", []) or [])

    policy_management = data.get("policy_management") or {}
    managed_policy_arns = set(policy_management.get("managed_policy_arns") or [])
    detach_unknown_managed = bool(policy_management.get("detach_unknown_managed", False))

    if not managed_policy_arns:
        for dept_cfg in departments.values():
            managed_policy_arns.update(dept_cfg.get("policies", []))
        for policies in user_extra_policies.values():
            managed_policy_arns.update(policies)

    dept_to_group = {name: cfg["group_name"] for name, cfg in departments.items()}
    group_to_dept = {cfg["group_name"]: name for name, cfg in departments.items()}

    unknown_override_users = sorted(
        user for user in user_extra_policies.keys() if user not in user_to_dept
    )

    return {
        "company": company,
        "departments": departments,
        "user_to_dept": user_to_dept,
        "dept_to_group": dept_to_group,
        "group_to_dept": group_to_dept,
        "user_extra_policies": user_extra_policies,
        "managed_policy_arns": managed_policy_arns,
        "detach_unknown_managed": detach_unknown_managed,
        "unknown_override_users": unknown_override_users,
    }


def normalize_test_cases(data: dict, config: dict) -> dict:
    cases_raw = data.get("cases") or {}
    if not isinstance(cases_raw, dict) or not cases_raw:
        raise ValueError("Test cases config must include a cases mapping.")

    cases: dict[str, dict] = {}
    for case_name, cfg in cases_raw.items():
        cfg = cfg or {}
        instructions = list(cfg.get("instructions", []) or [])
        if not all(isinstance(item, str) for item in instructions):
            raise ValueError(f"Test case '{case_name}' instructions must be a list of strings.")

        drift_raw = cfg.get("drift") or {}
        if not isinstance(drift_raw, dict):
            raise ValueError(f"Test case '{case_name}' drift must be a mapping.")

        drift: dict[str, dict] = {}
        for user, override in drift_raw.items():
            override = override or {}
            groups = override.get("groups")
            if groups is not None:
                groups = list(groups)
                for dept in groups:
                    if dept not in config["departments"]:
                        raise ValueError(
                            f"Test case '{case_name}' references unknown department '{dept}'."
                        )

            extra_policies = override.get("extra_policies")
            if extra_policies is not None:
                extra_policies = list(extra_policies)

            drift[user] = {
                "groups": groups,
                "extra_policies": extra_policies,
            }

        cases[case_name] = {
            "name": case_name,
            "title": cfg.get("title", case_name),
            "description": cfg.get("description", ""),
            "instructions": instructions,
            "drift": drift,
            "unknown_drift_users": sorted(
                user for user in drift.keys() if user not in config["user_to_dept"]
            ),
        }

    default_case = data.get("default_case") or next(iter(cases.keys()))
    if default_case not in cases:
        raise ValueError(f"Default test case '{default_case}' is not defined.")

    return {
        "default_case": default_case,
        "cases": cases,
    }


def attach_test_case(config: dict, test_cases: dict, selected_case_name: str | None) -> dict:
    case_name = selected_case_name or test_cases["default_case"]
    if case_name not in test_cases["cases"]:
        raise ValueError(f"Unknown test case: {case_name}")

    selected_case = test_cases["cases"][case_name]
    merged = dict(config)
    merged["test_cases"] = test_cases["cases"]
    merged["selected_test_case_name"] = case_name
    merged["selected_test_case"] = selected_case
    merged["seed_overrides"] = selected_case["drift"]
    merged["unknown_seed_users"] = selected_case["unknown_drift_users"]
    return merged


def make_iam_client():
    load_dotenv()
    profile = os.getenv("AWS_PROFILE")
    region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-east-1"
    if profile:
        session = boto3.Session(profile_name=profile, region_name=region)
    else:
        session = boto3.Session(region_name=region)
    return session.client("iam")


def paginate(client, method: str, key: str, **kwargs) -> list:
    paginator = client.get_paginator(method)
    items = []
    for page in paginator.paginate(**kwargs):
        items.extend(page.get(key, []))
    return items


def fetch_current_state(iam, expected: dict) -> dict:
    group_policy_cache: dict[str, list[str]] = {}
    current: dict[str, dict] = {}

    for user in expected["user_to_dept"].keys():
        try:
            groups = [
                item["GroupName"]
                for item in paginate(iam, "list_groups_for_user", "Groups", UserName=user)
            ]
            user_policies = [
                item["PolicyArn"]
                for item in paginate(
                    iam,
                    "list_attached_user_policies",
                    "AttachedPolicies",
                    UserName=user,
                )
            ]
            group_policies = []
            for group in groups:
                if group not in group_policy_cache:
                    group_policy_cache[group] = [
                        item["PolicyArn"]
                        for item in paginate(
                            iam,
                            "list_attached_group_policies",
                            "AttachedPolicies",
                            GroupName=group,
                        )
                    ]
                group_policies.extend(group_policy_cache[group])

            current[user] = {
                "missing": False,
                "groups": sorted(set(groups)),
                "user_policies": sorted(set(user_policies)),
                "group_policies": sorted(set(group_policies)),
            }
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") == "NoSuchEntity":
                current[user] = {
                    "missing": True,
                    "groups": [],
                    "user_policies": [],
                    "group_policies": [],
                }
            else:
                raise

    return current


def build_expected_state(expected: dict) -> dict:
    current: dict[str, dict] = {}

    for user, dept in expected["user_to_dept"].items():
        current[user] = {
            "missing": False,
            "groups": [expected["dept_to_group"][dept]],
            "user_policies": sorted(expected["user_extra_policies"].get(user, set())),
            "group_policies": sorted(expected["departments"][dept].get("policies", [])),
        }

    return current


def build_seeded_state(expected: dict) -> dict:
    current = build_expected_state(expected)

    for user, override in expected["seed_overrides"].items():
        if user not in current:
            continue

        groups = override.get("groups")
        if groups is not None:
            current[user]["groups"] = sorted(
                expected["dept_to_group"][dept] for dept in groups
            )

            group_policies = set()
            for dept in groups:
                group_policies.update(expected["departments"][dept].get("policies", []))
            current[user]["group_policies"] = sorted(group_policies)

        extra_policies = override.get("extra_policies")
        if extra_policies is not None:
            current[user]["user_policies"] = sorted(set(extra_policies))

    return current


def build_offline_state(expected: dict, demo_drift: bool = False) -> dict:
    current = build_expected_state(expected)
    if not demo_drift:
        return current

    if expected["seed_overrides"]:
        return build_seeded_state(expected)

    departments = list(expected["departments"].keys())
    if len(departments) < 2:
        return current

    first_dept, second_dept = departments[0], departments[1]
    first_users = list(expected["departments"][first_dept].get("users", []))
    second_users = list(expected["departments"][second_dept].get("users", []))

    if second_users:
        moved_user = second_users[0]
        current[moved_user]["groups"] = [expected["dept_to_group"][first_dept]]
        current[moved_user]["group_policies"] = sorted(
            expected["departments"][first_dept].get("policies", [])
        )

    if first_users:
        unassigned_user = first_users[0]
        current[unassigned_user]["groups"] = []
        current[unassigned_user]["group_policies"] = []

    return current


def build_plan(expected: dict, current: dict) -> dict:
    actions = {
        "add_group": [],
        "remove_group": [],
        "attach_policy": [],
        "detach_policy": [],
    }
    issues = []

    for user, dept in expected["user_to_dept"].items():
        state = current.get(user)
        if not state:
            issues.append(f"User missing from scan: {user}")
            continue
        if state["missing"]:
            issues.append(f"User not found in AWS: {user}")
            continue

        expected_group = expected["dept_to_group"][dept]
        actual_groups = state["groups"]
        managed_actual_groups = [
            group for group in actual_groups if group in expected["group_to_dept"]
        ]

        if expected_group not in actual_groups:
            actions["add_group"].append((user, expected_group))

        for group in managed_actual_groups:
            if group != expected_group:
                actions["remove_group"].append((user, group))

        expected_user_policies = expected["user_extra_policies"].get(user, set())
        attached_user_policies = set(state["user_policies"])

        for policy in sorted(expected_user_policies - attached_user_policies):
            actions["attach_policy"].append((user, policy))

        if expected["detach_unknown_managed"]:
            for policy in sorted(attached_user_policies - expected_user_policies):
                if policy in expected["managed_policy_arns"]:
                    actions["detach_policy"].append((user, policy))

    return {
        "actions": actions,
        "issues": issues,
    }


def apply_plan(iam, plan: dict, execute: bool) -> None:
    actions = plan["actions"]
    if not execute:
        print("Dry run only. Use --execute to apply changes.")
        return

    for user, group in actions["remove_group"]:
        iam.remove_user_from_group(UserName=user, GroupName=group)

    for user, group in actions["add_group"]:
        iam.add_user_to_group(UserName=user, GroupName=group)

    for user, policy in actions["detach_policy"]:
        iam.detach_user_policy(UserName=user, PolicyArn=policy)

    for user, policy in actions["attach_policy"]:
        iam.attach_user_policy(UserName=user, PolicyArn=policy)


def policy_name(policy_arn: str) -> str:
    if "/" in policy_arn:
        return policy_arn.rsplit("/", 1)[-1]
    return policy_arn


def selected_case_payload(expected: dict) -> dict:
    case = expected["selected_test_case"]
    return {
        "name": expected["selected_test_case_name"],
        "title": case["title"],
        "description": case["description"],
        "instructions": case["instructions"],
    }


def build_runtime_manifest(expected: dict, mode: str) -> dict:
    return {
        "company": expected["company"],
        "mode": mode,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "selected_case": selected_case_payload(expected),
        "cases": [
            {
                "name": case["name"],
                "title": case["title"],
                "description": case["description"],
                "instructions": case["instructions"],
            }
            for case in expected["test_cases"].values()
        ],
    }


def build_current_tree(expected: dict, current: dict, mode: str) -> dict:
    dept_order = list(expected["departments"].keys())
    dept_buckets: dict[str, list] = {dept: [] for dept in dept_order}
    extra_departments = []
    changes = []

    missing_count = 0
    mismatch_count = 0
    total_users = len(expected["user_to_dept"])

    for user, expected_dept in expected["user_to_dept"].items():
        state = current.get(user, {"missing": True})
        if state.get("missing"):
            actual_dept = "Missing"
            status = "missing"
            permissions = []
            missing_count += 1
        else:
            actual_dept_candidates = [
                expected["group_to_dept"][group]
                for group in state["groups"]
                if group in expected["group_to_dept"]
            ]
            if len(actual_dept_candidates) == 1:
                actual_dept = actual_dept_candidates[0]
            elif len(actual_dept_candidates) == 0:
                actual_dept = "Unassigned"
            else:
                actual_dept = "Conflicting"

            if actual_dept == expected_dept:
                status = "ok"
            elif actual_dept == "Unassigned":
                status = "unassigned"
            elif actual_dept == "Conflicting":
                status = "conflict"
            else:
                status = "moved"

            permissions = sorted(set(state["user_policies"]) | set(state["group_policies"]))

        if status not in ("ok", "missing"):
            mismatch_count += 1
            changes.append(
                {
                    "user": user,
                    "from": actual_dept,
                    "to": expected_dept,
                    "status": status,
                }
            )

        if actual_dept not in dept_buckets:
            dept_buckets[actual_dept] = []
            extra_departments.append(actual_dept)

        dept_buckets[actual_dept].append(
            {
                "id": f"user:{user}",
                "name": user,
                "type": "user",
                "status": status,
                "department": actual_dept,
                "expected_department": expected_dept,
                "permissions": [policy_name(p) for p in permissions],
                "permission_arns": permissions,
            }
        )

    children = []
    for dept in dept_order + extra_departments:
        children.append(
            {
                "id": f"dept:{dept}",
                "name": dept,
                "type": "department",
                "children": sorted(dept_buckets[dept], key=lambda item: item["name"]),
            }
        )

    tree = {
        "id": "root",
        "name": expected["company"],
        "type": "root",
        "children": children,
    }

    return {
        "meta": {
            "company": expected["company"],
            "mode": mode,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "test_case": selected_case_payload(expected),
            "counts": {
                "users": total_users,
                "mismatches": mismatch_count,
                "missing": missing_count,
                "departments": len(dept_order),
            },
            "changes": changes,
        },
        "tree": tree,
    }


def build_corrected_tree(expected: dict, current: dict, mode: str) -> dict:
    dept_order = list(expected["departments"].keys())
    dept_buckets: dict[str, list] = {dept: [] for dept in dept_order}

    for user, expected_dept in expected["user_to_dept"].items():
        state = current.get(user, {"missing": True})
        if state.get("missing"):
            status = "missing"
        else:
            actual_dept_candidates = [
                expected["group_to_dept"][group]
                for group in state["groups"]
                if group in expected["group_to_dept"]
            ]
            if len(actual_dept_candidates) == 1 and actual_dept_candidates[0] == expected_dept:
                status = "ok"
            else:
                status = "corrected"

        expected_permissions = set(
            expected["departments"][expected_dept].get("policies", [])
        )
        expected_permissions.update(expected["user_extra_policies"].get(user, set()))

        dept_buckets[expected_dept].append(
            {
                "id": f"user:{user}",
                "name": user,
                "type": "user",
                "status": status,
                "department": expected_dept,
                "expected_department": expected_dept,
                "permissions": [policy_name(p) for p in sorted(expected_permissions)],
                "permission_arns": sorted(expected_permissions),
            }
        )

    children = []
    for dept in dept_order:
        children.append(
            {
                "id": f"dept:{dept}",
                "name": dept,
                "type": "department",
                "children": sorted(dept_buckets[dept], key=lambda item: item["name"]),
            }
        )

    tree = {
        "id": "root",
        "name": expected["company"],
        "type": "root",
        "children": children,
    }

    return {
        "meta": {
            "company": expected["company"],
            "mode": mode,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "test_case": selected_case_payload(expected),
        },
        "tree": tree,
    }


def export_artifacts(expected: dict, current: dict, out_dir: Path, mode: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    current_tree = build_current_tree(expected, current, mode=mode)
    corrected_tree = build_corrected_tree(expected, current, mode=mode)
    runtime_manifest = build_runtime_manifest(expected, mode=mode)

    with (out_dir / "hierarchy_current.json").open("w", encoding="utf-8") as handle:
        json.dump(current_tree, handle, indent=2)

    with (out_dir / "hierarchy_corrected.json").open("w", encoding="utf-8") as handle:
        json.dump(corrected_tree, handle, indent=2)

    with (out_dir / "runtime.json").open("w", encoding="utf-8") as handle:
        json.dump(runtime_manifest, handle, indent=2)


def print_plan(plan: dict, expected: dict) -> None:
    actions = plan["actions"]
    issues = plan["issues"]

    print(f"Test case: {expected['selected_test_case_name']}")
    print("Plan summary")
    print(f"- Group adds: {len(actions['add_group'])}")
    print(f"- Group removals: {len(actions['remove_group'])}")
    print(f"- Policy attaches: {len(actions['attach_policy'])}")
    print(f"- Policy detaches: {len(actions['detach_policy'])}")

    if expected["unknown_override_users"] or expected["unknown_seed_users"]:
        print("Warnings")
        for user in expected["unknown_override_users"]:
            print(f"- user_overrides for unknown user: {user}")
        for user in expected["unknown_seed_users"]:
            print(f"- seed_overrides for unknown user: {user}")

    if issues:
        print("Issues")
        for issue in issues:
            print(f"- {issue}")


def print_cases(test_cases: dict) -> None:
    print("Available test cases")
    for case in test_cases["cases"].values():
        print(f"- {case['name']}: {case['title']}")
        if case["description"]:
            print(f"  {case['description']}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Audit and correct IAM user access.")
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG),
        help="Path to hierarchy YAML.",
    )
    parser.add_argument(
        "--cases-config",
        default=str(DEFAULT_CASES_CONFIG),
        help="Path to named test case YAML.",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list-cases", help="List the available named test cases.")

    plan_parser = subparsers.add_parser("plan", help="Show mismatches and planned fixes.")
    plan_parser.add_argument(
        "--test-case",
        help="Active test case name for UI metadata and warnings.",
    )

    apply_parser = subparsers.add_parser("apply", help="Apply fixes to IAM.")
    apply_parser.add_argument(
        "--execute",
        action="store_true",
        help="Apply changes instead of dry-run.",
    )
    apply_parser.add_argument(
        "--test-case",
        help="Active test case name for UI metadata and warnings.",
    )

    export_parser = subparsers.add_parser("export", help="Write JSON for the UI.")
    export_parser.add_argument(
        "--out-dir",
        default=str(DEFAULT_ARTIFACTS),
        help="Output directory for JSON artifacts.",
    )
    export_parser.add_argument(
        "--offline",
        action="store_true",
        help="Build UI artifacts from local config only, without calling AWS.",
    )
    export_parser.add_argument(
        "--demo-drift",
        action="store_true",
        help="When used with --offline, seed the selected named test case into the JSON output.",
    )
    export_parser.add_argument(
        "--test-case",
        help="Named test case from the cases config.",
    )

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        base_config = normalize_config(load_config(Path(args.config)))
        test_cases = normalize_test_cases(load_config(Path(args.cases_config)), base_config)
        config = attach_test_case(
            base_config,
            test_cases,
            selected_case_name=getattr(args, "test_case", None),
        )
    except (FileNotFoundError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if args.command == "list-cases":
        print_cases(test_cases)
        return 0

    iam = None
    current = None

    if args.command == "export" and args.offline:
        current = build_offline_state(config, demo_drift=args.demo_drift)
    else:
        try:
            iam = make_iam_client()
            current = fetch_current_state(iam, config)
        except (NoCredentialsError, PartialCredentialsError):
            print(
                "AWS credentials not found. Set AWS_PROFILE or access key credentials.",
                file=sys.stderr,
            )
            return 2
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "Unknown")
            print(f"AWS IAM request failed: {code}", file=sys.stderr)
            return 2

    if args.command == "plan":
        plan = build_plan(config, current)
        print_plan(plan, config)
        return 0

    if args.command == "apply":
        plan = build_plan(config, current)
        print_plan(plan, config)
        apply_plan(iam, plan, execute=args.execute)
        return 0

    if args.command == "export":
        out_dir = Path(args.out_dir)
        mode = "offline" if args.offline else "live"
        export_artifacts(config, current, out_dir, mode=mode)
        print(f"Wrote artifacts to {out_dir}")
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
