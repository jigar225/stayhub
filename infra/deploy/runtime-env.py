"""Run on EC2; write runtime secrets to a root-only file, never stdout."""

import json
import os
import re
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
    "TRUSTED_ORIGINS": ",".join(
        filter(None, [f"https://{config['ip']}", config.get("cdn_origin")])
    ),
    "COOKIE_SECURE": "true",
    "DEMO_MODE": "false",
    "S3_USE_IAM_ROLE": "true",
    "S3_ENDPOINT_URL": "https://s3.us-east-1.amazonaws.com",
    "S3_PUBLIC_ENDPOINT_URL": "https://s3.us-east-1.amazonaws.com",
    "S3_REGION": "us-east-1",
    "S3_BUCKET": config["photos"],
    "AWS_DEFAULT_REGION": "us-east-1",
}
# Only this allowlisted provider configuration reaches the backend. Never pass
# application-secret fields wholesale to frontend build or runtime configuration.
provider_key = app.get("GEOAPIFY_API_KEY", "")
if not isinstance(provider_key, str) or len(provider_key) > 512:
    raise ValueError("Invalid GEOAPIFY_API_KEY configuration")
budget = app.get("GEOAPIFY_DAILY_BUDGET", 2800)
if isinstance(budget, bool) or not re.fullmatch(r"[0-9]{1,4}", str(budget)):
    raise ValueError("Invalid GEOAPIFY_DAILY_BUDGET configuration")
if not 1 <= int(budget) <= 3000:
    raise ValueError("Invalid GEOAPIFY_DAILY_BUDGET configuration")
values["GEOAPIFY_API_KEY"] = provider_key
values["GEOAPIFY_DAILY_BUDGET"] = str(int(budget))
# Explicit seeding may use these credentials; normal deployment never seeds.
for key, value in app.items():
    if key.startswith("SEED_"):
        values[key] = value
for key, value in values.items():
    if any(c in str(value) for c in "\r\n\x00"):
        raise ValueError(f"Invalid multiline runtime value: {key}")
path = root / "runtime.env"
fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
os.fchmod(fd, 0o600)
with os.fdopen(fd, "w") as stream:
    stream.write("".join(f"{key}={value}\n" for key, value in values.items()))
