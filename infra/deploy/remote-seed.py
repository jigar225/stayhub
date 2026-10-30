"""Explicit operator command; uses SSO and never places credentials in SSM parameters."""

import json
import os
import subprocess
import time

variables = json.loads(
    subprocess.check_output(
        ["terraform", "-chdir=infra/runtime", "output", "-json", "github_variables"],
        text=True,
        env=os.environ | {"AWS_PROFILE": "stayhub"},
    )
)
base = ["aws", "--profile", "stayhub", "--region", "us-east-1", "ssm"]
parameters = {"commands": ["set -eu", "bash /opt/stayhub/current/deploy/seed.sh"]}
command = subprocess.check_output(
    base
    + [
        "send-command",
        "--instance-ids",
        variables["EC2_INSTANCE_ID"],
        "--document-name",
        "AWS-RunShellScript",
        "--parameters",
        json.dumps(parameters),
        "--query",
        "Command.CommandId",
        "--output",
        "text",
    ],
    text=True,
).strip()
print("Explicit seed command:", command)
for _attempt in range(120):
    result = subprocess.run(
        base
        + [
            "get-command-invocation",
            "--command-id",
            command,
            "--instance-id",
            variables["EC2_INSTANCE_ID"],
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        status = json.loads(result.stdout)
        if status["Status"] == "Success":
            print(status.get("StandardOutputContent", ""))
            break
        if status["Status"] in {"Failed", "Cancelled", "TimedOut"}:
            raise SystemExit(
                "Seed failed; inspect SSM output. Existing demo edits are not reset."
            )
    time.sleep(15)
else:
    raise SystemExit("Seed wait timed out; inspect the command before retrying.")
