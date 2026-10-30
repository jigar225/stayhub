terraform {
  required_version = ">= 1.10, < 2.0"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 6.0" }
  }
  backend "s3" {
    bucket       = "stayhub-762079300828-us-east-1-state"
    key          = "runtime/terraform.tfstate"
    region       = "us-east-1"
    encrypt      = true
    use_lockfile = true
  }
}
provider "aws" {
  region              = "us-east-1"
  allowed_account_ids = ["762079300828"]
  default_tags {
    tags = { Project = "stayhub", Environment = "sandbox", ManagedBy = "terraform" }
  }
}
locals {
  account = "762079300828"
  region  = "us-east-1"
  name    = "stayhub-sandbox"
  ecr     = "${local.account}.dkr.ecr.${local.region}.amazonaws.com/stayhub/backend"
}
data "aws_availability_zones" "available" { state = "available" }
data "aws_ssm_parameter" "ami" { name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64" }
