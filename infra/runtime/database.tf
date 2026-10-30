resource "aws_db_subnet_group" "main" {
  name       = local.name
  subnet_ids = aws_subnet.db[*].id
}
resource "aws_db_instance" "main" {
  identifier                  = local.name
  engine                      = "postgres"
  engine_version              = var.db_engine_version
  instance_class              = var.db_instance_class
  allocated_storage           = 20
  storage_type                = "gp3"
  storage_encrypted           = true
  db_name                     = "stayhub"
  username                    = "stayhub_admin"
  manage_master_user_password = true
  db_subnet_group_name        = aws_db_subnet_group.main.name
  vpc_security_group_ids      = [aws_security_group.db.id]
  publicly_accessible         = false
  multi_az                    = false
  backup_retention_period     = 7
  auto_minor_version_upgrade  = true
  deletion_protection         = var.deletion_protection
  skip_final_snapshot         = false
  final_snapshot_identifier   = "${local.name}-final"
}
# Password rotation is explicit: deployments fetch fresh credentials. Automated
# rotation without container refresh would eventually break new DB connections.
resource "aws_secretsmanager_secret_rotation" "database" {
  secret_id        = aws_db_instance.main.master_user_secret[0].secret_arn
  rotation_enabled = false
}
