# Optional: a single small instance that runs the whole Docker Compose stack.
# Off by default (create_monitoring_host = false) so `terraform apply` costs nothing extra.

data "aws_ami" "ubuntu" {
  count       = var.create_monitoring_host ? 1 : 0
  most_recent = true
  owners      = ["099720109477"] # Canonical

  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64-server-*"]
  }
}

data "aws_vpc" "default" {
  count   = var.create_monitoring_host ? 1 : 0
  default = true
}

resource "aws_security_group" "monitoring" {
  count       = var.create_monitoring_host ? 1 : 0
  name        = "${var.project_name}-monitoring"
  description = "Grafana access for the FinOps monitoring host"
  vpc_id      = data.aws_vpc.default[0].id

  ingress {
    description = "Grafana"
    from_port   = 3000
    to_port     = 3000
    protocol    = "tcp"
    cidr_blocks = [var.allowed_cidr]
  }

  egress {
    description = "Outbound for AWS APIs, package installs and image pulls"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_instance" "monitoring" {
  count                  = var.create_monitoring_host ? 1 : 0
  ami                    = data.aws_ami.ubuntu[0].id
  instance_type          = var.instance_type
  iam_instance_profile   = aws_iam_instance_profile.exporter.name
  vpc_security_group_ids = [aws_security_group.monitoring[0].id]

  # IMDSv2 only. Hop limit 2 lets the exporter container (one network hop
  # behind Docker's bridge) fetch the instance-profile credentials.
  metadata_options {
    http_tokens                 = "required"
    http_put_response_hop_limit = 2
  }

  root_block_device {
    volume_size = 20
    volume_type = "gp3"
    encrypted   = true
  }

  user_data = templatefile("${path.module}/user_data.sh.tftpl", {
    repo_url           = var.repo_url
    aws_region         = var.aws_region
    monthly_budget_usd = var.monthly_budget_usd
  })

  tags = {
    Name = "${var.project_name}-monitoring"
  }
}
