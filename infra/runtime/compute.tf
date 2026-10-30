resource "aws_instance" "app" {
  ami                         = data.aws_ssm_parameter.ami.value
  instance_type               = var.instance_type
  subnet_id                   = aws_subnet.public.id
  associate_public_ip_address = true
  vpc_security_group_ids      = [aws_security_group.app.id]
  iam_instance_profile        = aws_iam_instance_profile.app.name
  user_data = join("\n", [
    file("${path.module}/../deploy/bootstrap.sh"),
    "printf '%s' '${base64encode(file("${path.module}/../deploy/receive-bootstrap-v1.py"))}' | base64 -d > /opt/stayhub/receive.py",
    "chmod 700 /opt/stayhub/receive.py"
  ])
  user_data_replace_on_change = true
  metadata_options {
    http_tokens                 = "required"
    http_put_response_hop_limit = 2
  }
  credit_specification { cpu_credits = "standard" }
  root_block_device {
    volume_size = 20
    volume_type = "gp3"
    encrypted   = true
  }
  tags       = { Name = local.name }
  depends_on = [aws_route_table_association.public]
}
resource "aws_eip" "app" {
  domain     = "vpc"
  instance   = aws_instance.app.id
  depends_on = [aws_internet_gateway.main]
}
resource "aws_ssm_document" "deploy" {
  name          = "${local.name}-deploy"
  document_type = "Command"
  content = jsonencode({ schemaVersion = "2.2", description = "Deploy an immutable StayHub release"
    parameters = {
      Release = { type = "String", allowedPattern = "^[a-f0-9]{40}$", interpolationType = "ENV_VAR" }
      Sha256  = { type = "String", allowedPattern = "^[a-f0-9]{64}$", interpolationType = "ENV_VAR" }
    }
    mainSteps = [{ action = "aws:runShellScript", name = "deploy", inputs = {
      timeoutSeconds = "1800"
      runCommand = [
        "set -eu",
        "cloud-init status --wait",
        "python3 /opt/stayhub/receive.py $SSM_Release $SSM_Sha256 ${aws_s3_bucket.main["releases"].id}"
      ]
    } }]
  })
}
