"""User-run: send nonsecret Terraform deployment configuration through SSM."""

import base64
import json
import os
import subprocess

env = os.environ | {"AWS_PROFILE": "stayhub"}


def output(name):
    return json.loads(
        subprocess.check_output(
            ["terraform", "-chdir=infra/runtime", "output", "-json", name],
            env=env,
            text=True,
        )
    )


config = output("release_config")
variables = output("github_variables")
encoded = base64.b64encode(json.dumps(config).encode()).decode()
commands = [
    "set -eu",
    "cloud-init status --wait",
    "install -d -m 700 /opt/stayhub",
    f"printf '%s' '{encoded}' | base64 -d > /opt/stayhub/config.json",
    "chmod 600 /opt/stayhub/config.json",
]
result = subprocess.check_output(
    [
        "aws",
        "ssm",
        "send-command",
        "--profile",
        "stayhub",
        "--region",
        "us-east-1",
        "--instance-ids",
        variables["EC2_INSTANCE_ID"],
        "--document-name",
        "AWS-RunShellScript",
        "--parameters",
        json.dumps({"commands": commands}),
        "--query",
        "Command.CommandId",
        "--output",
        "text",
    ],
    text=True,
).strip()
print("Configuration upload command:", result)
subprocess.run(
    [
        "aws",
        "ssm",
        "wait",
        "command-executed",
        "--profile",
        "stayhub",
        "--region",
        "us-east-1",
        "--command-id",
        result,
        "--instance-id",
        variables["EC2_INSTANCE_ID"],
    ],
    check=True,
)
print("EC2 configuration ready. No secrets were printed.")
