"""Explicit operator-only setup. Preserve JWT and existing seed fields; never print secrets."""

import getpass
import json
import os
import subprocess
import tempfile

config = json.loads(
    subprocess.check_output(
        ["terraform", "-chdir=infra/runtime", "output", "-json", "release_config"],
        text=True,
        env=os.environ | {"AWS_PROFILE": "stayhub"},
    )
)
base = ["aws", "--profile", "stayhub", "--region", "us-east-1", "secretsmanager"]
values = json.loads(
    subprocess.check_output(
        base
        + [
            "get-secret-value",
            "--secret-id",
            config["app_secret"],
            "--query",
            "SecretString",
            "--output",
            "text",
        ],
        text=True,
    )
)
for role in ["GUEST", "HOST", "ADMIN"]:
    for field in ["NAME", "EMAIL", "PASSWORD"]:
        key = f"SEED_{role}_{field}"
        if key in values:
            continue
        value = getpass.getpass(f"{key} (hidden): ")
        if not value or any(c in value for c in "\r\n\x00"):
            raise SystemExit("Invalid empty/multiline value; secret unchanged.")
        values[key] = value
payload = json.dumps(
    {"SecretId": config["app_secret"], "SecretString": json.dumps(values)}
)
# NamedTemporaryFile creates mode 0600 and removes the file on success/failure.
with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".json") as source:
    source.write(payload)
    source.flush()
    result = subprocess.run(
        base + ["put-secret-value"] + ["--cli-input-json", "file://" + source.name],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        # CLI diagnostics can include input data; do not echo them.
        raise SystemExit(
            "Secret write failed; verify AWS session and permissions. No secret values displayed."
        )

print("Demo secret fields prepared; existing values preserved. Seeding has NOT run.")
