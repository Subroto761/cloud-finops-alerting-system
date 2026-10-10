# Least-privilege, read-only permissions for the exporter.
# It only needs to describe resources, read CPU metrics and read Cost Explorer.
data "aws_iam_policy_document" "finops_readonly" {
  statement {
    sid = "DescribeResources"
    actions = [
      "ec2:DescribeInstances",
      "ec2:DescribeVolumes",
      "ec2:DescribeAddresses",
    ]
    resources = ["*"]
  }

  statement {
    sid       = "ReadCpuMetrics"
    actions   = ["cloudwatch:GetMetricStatistics"]
    resources = ["*"]
  }

  statement {
    sid       = "ReadCosts"
    actions   = ["ce:GetCostAndUsage"]
    resources = ["*"]
  }
}

resource "aws_iam_policy" "finops_readonly" {
  name        = "${var.project_name}-readonly"
  description = "Read-only access for the FinOps exporter"
  policy      = data.aws_iam_policy_document.finops_readonly.json
}

data "aws_iam_policy_document" "ec2_assume_role" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

# Role used by the monitoring host, so no access keys are stored on the server
resource "aws_iam_role" "exporter" {
  name               = "${var.project_name}-exporter"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume_role.json
}

resource "aws_iam_role_policy_attachment" "exporter_readonly" {
  role       = aws_iam_role.exporter.name
  policy_arn = aws_iam_policy.finops_readonly.arn
}

resource "aws_iam_instance_profile" "exporter" {
  name = "${var.project_name}-exporter"
  role = aws_iam_role.exporter.name
}
