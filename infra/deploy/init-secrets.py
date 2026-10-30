"""User-run initializer: no secret values in arguments, Terraform state, or stdout."""

import json
import secrets
import subprocess
import sys

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
# Value is sent through stdin, not shell arguments or files.
payload = json.dumps(
    {
        "SecretId": config["app_secret"],
        "SecretString": json.dumps({"JWT_SECRET": secrets.token_urlsafe(48)}),
    }
)
subprocess.run(
    [
        "aws",
        "secretsmanager",
        "put-secret-value",
        "--profile",
        profile,
        "--region",
        "us-east-1",
        "--cli-input-json",
        "file:///dev/stdin",
    ],
    input=payload,
    text=True,
    check=True,
    stdout=subprocess.DEVNULL,
)
print("Application JWT secret initialized. No demo accounts were created.")
