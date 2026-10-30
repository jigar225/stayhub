"""User-run initializer: no secret values in arguments, Terraform state, or stdout."""

import json
import secrets
import subprocess
import sys
import tempfile

profile = "stayhub"
config = json.loads(
    subprocess.check_output(
        ["terraform", "-chdir=infra/runtime", "output", "-json", "release_config"],
        text=True,
        env=__import__("os").environ | {"AWS_PROFILE": profile},
    )
)
result = subprocess.run(
    [
        "aws",
        "secretsmanager",
        "get-secret-value",
        "--profile",
        profile,
        "--region",
        "us-east-1",
        "--secret-id",
        config["app_secret"],
    ],
    check=False,
    capture_output=True,
    text=True,
)
if result.returncode == 0:
    print("Application secret already exists; left unchanged.")
    sys.exit(0)
if "ResourceNotFoundException" not in result.stderr:
    raise SystemExit(
        "Could not check secret; verify permissions/session. No value written."
    )
# AWS CLI on macOS may not read /dev/stdin; use a private temporary input file.
payload = json.dumps(
    {
        "SecretId": config["app_secret"],
        "SecretString": json.dumps({"JWT_SECRET": secrets.token_urlsafe(48)}),
    }
)
# NamedTemporaryFile creates mode 0600 and removes the file on success/failure.
with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".json") as source:
    source.write(payload)
    source.flush()
    result = subprocess.run(
        [
            "aws",
            "secretsmanager",
            "put-secret-value",
            "--profile",
            profile,
            "--region",
            "us-east-1",
        ]
        + ["--cli-input-json", "file://" + source.name],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        # CLI diagnostics can include input data; do not echo them.
        raise SystemExit(
            "Secret write failed; verify AWS session and permissions. No secret values displayed."
        )

print("Application JWT secret initialized. No demo accounts were created.")
