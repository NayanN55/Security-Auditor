variable "aws_region" {
  type        = string
  description = "AWS region for IAM operations (IAM is global but region is still required)."
  default     = "us-east-1"
}

variable "aws_profile" {
  type        = string
  description = "AWS CLI profile name. Leave null to use the default credential chain."
  default     = null
}

variable "seed_test_drift" {
  type        = bool
  description = "When true, Terraform provisions the intentional drift declared for the selected named test case."
  default     = true
}

variable "test_case_name" {
  type        = string
  description = "Named scenario from config/test_cases.yaml to seed into AWS."
  default     = null
}
