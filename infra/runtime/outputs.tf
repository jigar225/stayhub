output "github_variables" {
  value = {
    AWS_ROLE_ARN               = aws_iam_role.github.arn
    EC2_INSTANCE_ID            = aws_instance.app.id
    RELEASE_BUCKET             = aws_s3_bucket.main["releases"].id
    DEPLOY_DOCUMENT            = aws_ssm_document.deploy.name
    FRONTEND_BUCKET            = aws_s3_bucket.frontend.id
    CLOUDFRONT_DISTRIBUTION_ID = aws_cloudfront_distribution.frontend.id
  }
}
output "url" { value = "https://${aws_eip.app.public_ip}" }
output "release_config" {
  value = {
    ip         = aws_eip.app.public_ip
    cdn_origin = "https://${aws_cloudfront_distribution.frontend.domain_name}"
    email      = var.certificate_email
    db_host    = aws_db_instance.main.address
    db_secret  = aws_db_instance.main.master_user_secret[0].secret_arn
    app_secret = aws_secretsmanager_secret.app.arn
    photos     = aws_s3_bucket.main["photos"].id
    image      = local.ecr
  }
}
