locals {
  api_hostname = "jigar-stayhub-api.${replace(aws_eip.app.public_ip, ".", "-")}.sslip.io"
}
resource "aws_s3_bucket" "frontend" {
  bucket        = "${local.name}-${local.account}-frontend"
  force_destroy = false
}
resource "aws_s3_bucket_public_access_block" "frontend" {
  bucket                  = aws_s3_bucket.frontend.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
resource "aws_s3_bucket_server_side_encryption_configuration" "frontend" {
  bucket = aws_s3_bucket.frontend.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
  }
}
resource "aws_s3_bucket_versioning" "frontend" {
  bucket = aws_s3_bucket.frontend.id
  versioning_configuration { status = "Enabled" }
}
resource "aws_cloudfront_origin_access_control" "frontend" {
  name                              = "${local.name}-frontend"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}
data "aws_cloudfront_cache_policy" "disabled" { name = "Managed-CachingDisabled" }
data "aws_cloudfront_origin_request_policy" "api" { name = "Managed-AllViewerExceptHostHeader" }
resource "aws_cloudfront_function" "navigation" {
  name    = "${local.name}-navigation"
  runtime = "cloudfront-js-2.0"
  comment = "Rewrite only known SPA navigation routes; preserve API/static errors"
  publish = true
  code    = file("${path.module}/../deploy/navigation.js")
}
resource "aws_cloudfront_distribution" "frontend" {
  enabled             = true
  is_ipv6_enabled     = true
  comment             = "${local.name}-frontend"
  default_root_object = "index.html"
  price_class         = "PriceClass_100"
  wait_for_deployment = true
  origin {
    origin_id                = "frontend"
    domain_name              = aws_s3_bucket.frontend.bucket_regional_domain_name
    origin_access_control_id = aws_cloudfront_origin_access_control.frontend.id
  }
  origin {
    origin_id   = "api"
    domain_name = local.api_hostname
    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = "https-only"
      origin_ssl_protocols   = ["TLSv1.2"]
    }
  }
  default_cache_behavior {
    target_origin_id       = "frontend"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]
    compress               = true
    # Min TTL zero: index.html must revalidate even after a navigation rewrite.
    cache_policy_id = aws_cloudfront_cache_policy.frontend.id
    function_association {
      event_type   = "viewer-request"
      function_arn = aws_cloudfront_function.navigation.arn
    }
  }
  dynamic "ordered_cache_behavior" {
    for_each = ["/api", "/api/*"]
    content {
      path_pattern             = ordered_cache_behavior.value
      target_origin_id         = "api"
      viewer_protocol_policy   = "https-only"
      allowed_methods          = ["DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"]
      cached_methods           = ["GET", "HEAD"]
      cache_policy_id          = data.aws_cloudfront_cache_policy.disabled.id
      origin_request_policy_id = data.aws_cloudfront_origin_request_policy.api.id
      compress                 = true
    }
  }
  dynamic "custom_error_response" {
    for_each = toset([400, 403, 404, 405, 414, 416, 500, 501, 502, 503, 504])
    content {
      error_code            = custom_error_response.value
      error_caching_min_ttl = 0
    }
  }
  restrictions {
    geo_restriction { restriction_type = "none" }
  }
  viewer_certificate { cloudfront_default_certificate = true }
  tags = { Name = "${local.name}-frontend" }
}
resource "aws_cloudfront_cache_policy" "frontend" {
  name        = "${local.name}-frontend"
  min_ttl     = 0
  default_ttl = 0
  max_ttl     = 31536000
  parameters_in_cache_key_and_forwarded_to_origin {
    enable_accept_encoding_gzip   = true
    enable_accept_encoding_brotli = true
    cookies_config { cookie_behavior = "none" }
    headers_config { header_behavior = "none" }
    query_strings_config { query_string_behavior = "none" }
  }
}
resource "aws_s3_bucket_policy" "frontend" {
  bucket = aws_s3_bucket.frontend.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    {
      Sid       = "DistributionRead", Effect = "Allow", Principal = { Service = "cloudfront.amazonaws.com" }
      Action    = "s3:GetObject", Resource = "${aws_s3_bucket.frontend.arn}/*"
      Condition = { StringEquals = { "AWS:SourceArn" = aws_cloudfront_distribution.frontend.arn } }
    },
    {
      Sid       = "TLSOnly", Effect = "Deny", Principal = "*", Action = "s3:*"
      Resource  = [aws_s3_bucket.frontend.arn, "${aws_s3_bucket.frontend.arn}/*"]
      Condition = { Bool = { "aws:SecureTransport" = "false" } }
    }
  ] })
}
resource "aws_iam_role_policy" "frontend_deploy" {
  name = "${local.name}-frontend-deploy"
  role = aws_iam_role.github.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["s3:PutObject", "s3:GetObject"], Resource = "${aws_s3_bucket.frontend.arn}/*" },
    { Effect = "Allow", Action = ["cloudfront:CreateInvalidation", "cloudfront:GetInvalidation"], Resource = aws_cloudfront_distribution.frontend.arn }
  ] })
}
output "cdn_url" { value = "https://${aws_cloudfront_distribution.frontend.domain_name}" }
output "frontend_bucket" { value = aws_s3_bucket.frontend.id }
output "distribution_id" { value = aws_cloudfront_distribution.frontend.id }
output "api_hostname" { value = local.api_hostname }
