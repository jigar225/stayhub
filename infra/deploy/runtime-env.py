"""Run on EC2; write runtime secrets to a root-only file, never stdout."""

import json
import os
import subprocess
from pathlib import Path
from urllib.parse import quote

root = Path(os.environ.get("STAYHUB_ROOT", "/opt/stayhub"))
config = json.loads((root / "config.json").read_text())


def secret(arn):
    result = subprocess.run(
        [
            "aws",
            "secretsmanager",
            "get-secret-value",
            "--region",
            "us-east-1",
            "--secret-id",
            arn,
            "--query",
            "SecretString",
            "--output",
            "text",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


db = secret(config["db_secret"])
app = secret(config["app_secret"])
assert len(app["JWT_SECRET"]) >= 32, "JWT_SECRET must have at least 32 characters"
values = {
    "DATABASE_URL": f"postgresql+psycopg://{quote(db['username'], safe='')}:{quote(db['password'], safe='')}@{config['db_host']}:5432/stayhub?sslmode=require",
    "JWT_SECRET": app["JWT_SECRET"],
    "TRUSTED_ORIGINS": f"https://{config['ip']}",
    "COOKIE_SECURE": "true",
    "DEMO_MODE": "false",
    "S3_USE_IAM_ROLE": "true",
    "S3_ENDPOINT_URL": "https://s3.us-east-1.amazonaws.com",
    "S3_PUBLIC_ENDPOINT_URL": "https://s3.us-east-1.amazonaws.com",
    "S3_REGION": "us-east-1",
    "S3_BUCKET": config["photos"],
    "AWS_DEFAULT_REGION": "us-east-1",
}
# Explicit seeding may use these credentials; normal deployment never seeds.
for key, value in app.items():
    if key.startswith("SEED_"):
        values[key] = value
for key, value in values.items():
    if any(c in str(value) for c in "\r\n\x00"):
        raise ValueError(f"Invalid multiline runtime value: {key}")
path = root / "runtime.env"
fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
with os.fdopen(fd, "w") as stream:
    stream.write("".join(f"{key}={value}\n" for key, value in values.items()))
