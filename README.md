# Securtias IAM Hierarchy Demo

Securtias is a Terraform and Python demo for provisioning IAM department hierarchies, seeding intentional access drift, and visualizing remediation paths in a browser.
<img width="2207" height="1029" alt="image" src="https://github.com/user-attachments/assets/76dd5a0c-3f29-4b63-8170-6b63c8454e8d" />

## What it does
- Creates IAM users, groups, and managed policy attachments with Terraform.
- Seeds named drift scenarios such as wrong-department placement or extra direct policy attachments.
- Audits live IAM state with boto3 and computes the corrections needed to match the intended hierarchy.
- Renders both the live hierarchy and an offline simulation view that animates user moves.

## Project layout
- `config/hierarchy.yaml`: source of truth for departments, users, and expected policy assignments.
- `config/test_cases.yaml`: named drift scenarios (`test1`, `test2`, `test3`).
- `app.py`: audit, export, and remediation CLI.
- `web/index.html`: live hierarchy UI.
- `web/simulation.html`: offline explainer and simulation UI.
- `run_test_case.ps1`: one-command scenario runner for AWS.
- `start_local.ps1`: local web launcher for the UI.

## Requirements
- Python 3.11+
- Terraform 1.5+
- AWS credentials with IAM management permissions

## Setup
```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Create a local `.env` from `.env.example` and point it at an AWS profile or access key set. Do not commit `.env`.

## List and run scenarios
```powershell
python app.py list-cases
.\run_test_case.ps1 -Case test1
```

`run_test_case.ps1`:
- applies the selected Terraform scenario to AWS
- refreshes the live UI artifacts in `artifacts`
- refreshes the offline simulation artifacts in `artifacts\offline`
- starts a local web server and prints the URLs

## Audit and remediate
```powershell
python app.py plan --test-case test1
python app.py apply --test-case test1 --execute
python app.py export --test-case test1
```

## Local UI
```powershell
.\start_local.ps1 -Live -TestCase test1
```

The live view is `web/index.html`. The offline explainer is `web/simulation.html`.

## Security notes
- Keep credentials in `.env` or your AWS shared config, never in source control.
- `.gitignore` excludes `.env`, Terraform state, local artifacts, and virtualenv files.
- Review IAM permissions before using this outside a demo account.
