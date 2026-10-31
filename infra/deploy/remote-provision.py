"""Explicit operator command; runs one-time provisioning on the host via SSM.

That run writes a private credentials file on the host; fetch it separately with
`aws ssm ... cat /opt/stayhub/provisioned-credentials.txt` and keep it out of logs.
"""

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
parameters = {"commands": ["set -eu", "bash /opt/stayhub/current/deploy/provision.sh"]}
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
print("Explicit provisioning command:", command)
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
            print(
                "Fetch credentials with:\n"
                "  aws ssm send-command --instance-ids "
                + variables["EC2_INSTANCE_ID"]
                + " --document-name AWS-RunShellScript "
                '--parameters commands="cat /opt/stayhub/provisioned-credentials.txt"'
            )
            break
        if status["Status"] in {"Failed", "Cancelled", "TimedOut"}:
            raise SystemExit(
                "Provisioning failed; inspect SSM output. Existing content is not reset."
            )
    time.sleep(15)
else:
    raise SystemExit("Provisioning wait timed out; inspect the command before retrying.")
