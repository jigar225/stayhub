"""Explicit operator-only provider setup; no values in arguments or diagnostics."""

import getpass
import json
import os
import re
import subprocess
import tempfile


def captured(args, **kwargs):
    result = subprocess.run(args, capture_output=True, text=True, check=False, **kwargs)
    if result.returncode:
        # AWS diagnostics may contain input values. Never echo stdout/stderr.
        raise ValueError("Configuration command failed")
    return result.stdout


def main():
    config = json.loads(
        captured(
            ["terraform", "-chdir=infra/runtime", "output", "-json", "release_config"],
            env=os.environ | {"AWS_PROFILE": "stayhub"},
        )
    )
    base = ["aws", "--profile", "stayhub", "--region", "us-east-1", "secretsmanager"]
    values = json.loads(
        captured(
            base
            + [
                "get-secret-value",
                "--secret-id",
                config["app_secret"],
                "--query",
                "SecretString",
                "--output",
                "text",
            ]
        )
    )
    if not isinstance(values, dict) or not isinstance(values.get("JWT_SECRET"), str):
        raise ValueError("Existing initialized application secret required")
    key = getpass.getpass("Geoapify API key (hidden; blank preserves existing): ")
    if not key:
        print("Provider secret left unchanged. No deployment performed.")
        return
    if len(key) > 512 or any(c in key for c in "\r\n\x00"):
        raise ValueError("Invalid provider key")
    budget = getpass.getpass(
        "Daily request budget 1–3000 (blank preserves/defaults 2800): "
    )
    budget = budget or str(values.get("GEOAPIFY_DAILY_BUDGET", 2800))
    if not re.fullmatch(r"[0-9]{1,4}", budget) or not 1 <= int(budget) <= 3000:
        raise ValueError("Invalid provider budget")
    values.update(GEOAPIFY_API_KEY=key, GEOAPIFY_DAILY_BUDGET=int(budget))
    payload = json.dumps(
        {"SecretId": config["app_secret"], "SecretString": json.dumps(values)}
    )
    # Private input file avoids credential-bearing process arguments and stdout.
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", suffix=".json"
    ) as source:
        source.write(payload)
        source.flush()
        captured(
            base + ["put-secret-value", "--cli-input-json", "file://" + source.name]
        )
    print("Server-only provider configuration saved. No deployment performed.")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, TypeError, EOFError, KeyboardInterrupt):
        raise SystemExit(
            "Provider setup failed; verify the private input and operator session. No secret values displayed."
        ) from None
