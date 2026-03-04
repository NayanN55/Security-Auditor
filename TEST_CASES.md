# Test Case Runner

Named drift scenarios live in `config/test_cases.yaml`.

## Available cases
- `test1`: Cross-department drift with Jameson and Priya in the wrong department and Alex in both groups.
- `test2`: Policy spillover with direct user-attached policies that should not exist.
- `test3`: Conflicting reporting lines with dual memberships that must be untangled.

## Create a case in AWS
```powershell
.\run_test_case.ps1 -Case test1
```

What it does:
- runs `terraform apply` with `test_case_name=test1`
- creates or updates the IAM users and groups in AWS
- exports live UI artifacts into `artifacts`
- exports offline simulation artifacts into `artifacts\offline`
- starts the local web server

## Start the UI without changing AWS
```powershell
.\start_local.ps1 -Live -TestCase test1
```

## Offline simulation only
```powershell
python app.py export --offline --demo-drift --test-case test1 --out-dir artifacts/offline
```

The live UI is `web/index.html`.
The offline explainer UI is `web/simulation.html`.
