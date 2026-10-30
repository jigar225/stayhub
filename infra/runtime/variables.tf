variable "certificate_email" {
  type        = string
  description = "Contact email for Let's Encrypt; not a credential."
  validation {
    condition     = can(regex("^[^@ ]+@[^@ ]+\\.[^@ ]+$", var.certificate_email))
    error_message = "Supply a valid certificate contact email."
  }
}
variable "instance_type" { default = "t3.small" }
variable "db_instance_class" { default = "db.t4g.micro" }
variable "db_engine_version" { default = "18" }
variable "deletion_protection" { default = true }
