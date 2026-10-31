"""Run the explicit review demo import via SSM; defaults to a rolled-back preview."""

import argparse
import json
import os
import subprocess
import time

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--apply", action="store_true")
args = parser.parse_args()
variables = json.loads(
    subprocess.check_output(
        ["terraform", "-chdir=infra/runtime", "output", "-json", "github_variables"],
        text=True,
        env=os.environ | {"AWS_PROFILE": "stayhub"},
    )
)
base = ["aws", "--profile", "stayhub", "--region", "us-east-1", "ssm"]
parameters = {
    "commands": [
        "set -eu",
        "bash /opt/stayhub/current/deploy/demo-history.sh"
        + (" --apply" if args.apply else ""),
    ]
}
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
print("Review demo import command:", command)
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
                "Import failed; inspect SSM output. The import transaction is atomic."
            )
    time.sleep(15)
else:
    raise SystemExit("Import wait timed out; inspect the command before retrying.")
