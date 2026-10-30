"""Fresh-volume local verification; never mutates either existing stack.

Run stages in the order documented in docs/m61-evidence.md. Private configuration
is .env.m61.local; stdout/evidence never contain credentials or session tokens.
"""

import json
import os
import secrets
import shlex
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evidence/m61"
PROJECT = "stayhub-m61-cold-20261030"
DC = [
    "docker",
    "compose",
    "--env-file",
    ".env.m61.local",
    "-p",
    PROJECT,
    "-f",
    "compose.yaml",
    "-f",
    "compose.m61-cold.yaml",
]
EXISTING = {
    "main": ["docker", "compose"],
    "review": [
        "docker",
        "compose",
        "-p",
        "stayhub-m5-review",
        "-f",
        "compose.yaml",
        "-f",
        "compose.m5-review.yaml",
    ],
}
SNAPSHOT = """import hashlib, json
from sqlalchemy import inspect, text
from app.db import get_engine
from app.config import get_settings
from app.storage import s3_client
engine = get_engine()
with engine.connect() as connection:
    tables = {name: sorted(hashlib.sha256(row.encode()).hexdigest()
        for row in connection.execute(text('SELECT row_to_json(t)::text FROM "' + name + '" t')).scalars())
        for name in inspect(engine).get_table_names()}
    offset = connection.scalar(text('SELECT offset_seconds FROM app_clock WHERE id=1'))
objects = sorted(hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()
    for page in s3_client().get_paginator('list_objects_v2').paginate(Bucket=get_settings().s3_bucket)
    for obj in page.get('Contents', []))
print(json.dumps({'tables': tables, 'objects': objects, 'offset_seconds': offset}))
"""


def run(name, args, *, private_output=False, cwd=ROOT, env=None):
    """Log exact argument invocation; only config JSON has secret output suppressed."""
    start = time.monotonic()
    result = subprocess.run(args, cwd=cwd, env=env, text=True, capture_output=True)
    log = OUT / "checks" / f"{name}.log"
    attempt = 1
    while log.exists():
        attempt += 1
        log = OUT / "checks" / f"{name}-{attempt}.log"
    log.write_text(
        (
            "Configuration parsed privately; no values logged.\n"
            if private_output
            else result.stdout
        )
        + result.stderr
    )
    record = {
        "name": name,
        "cwd": str(cwd),
        "command": shlex.join(args),
        "exit": result.returncode,
        "seconds": round(time.monotonic() - start, 2),
        "log": str(log.relative_to(ROOT)),
    }
    journal = OUT / "commands.json"
    rows = json.loads(journal.read_text()) if journal.exists() else []
    rows.append(record)
    journal.write_text(json.dumps(rows, indent=2) + "\n")
    print(f"{name}: exit {result.returncode} ({record['seconds']}s)", flush=True)
    result.check_returncode()
    return result.stdout


def snapshot(name, dc):
    return json.loads(
        run(
            name,
            dc
            + ["exec", "-T", "api", "uv", "run", "--frozen", "python", "-c", SNAPSHOT],
        )
    )


def preflight():
    run("config-quiet", DC + ["config", "--quiet"])
    config = json.loads(
        run("config-private", DC + ["config", "--format", "json"], private_output=True)
    )
    assert config["name"] == PROJECT
    expected = {
        "api": (8020, "8000"),
        "frontend": (5193, "5173"),
        "storage": (9020, "9000"),
    }
    for service, (published, target) in expected.items():
        ports = config["services"][service]["ports"]
        assert len(ports) == 1 and int(ports[0]["published"]) == published
        assert str(ports[0]["target"]) == target and ports[0]["host_ip"] == "127.0.0.1"
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", published))
    volumes = [v["name"] for v in config["volumes"].values()]
    assert all(v.startswith(PROJECT + "_") for v in volumes)
    assert not run(
        "existing-cold-volumes",
        [
            "docker",
            "volume",
            "ls",
            "-q",
            "--filter",
            f"label=com.docker.compose.project={PROJECT}",
        ],
    ).strip()
    assert not run("existing-cold-containers", DC + ["ps", "-aq"]).strip()
    all_volumes = run("volume-inventory", ["docker", "volume", "ls", "-q"]).splitlines()
    assert not set(volumes) & set(all_volumes)
    buckets = {"stayhub-m61-cold-photos", "stayhub-m61-cold-photos-test"}
    for service in ["api", "expiry-worker"]:
        settings = config["services"][service]["environment"]
        assert (
            settings["S3_BUCKET"] in buckets and settings["TEST_S3_BUCKET"] in buckets
        )
        assert settings["S3_BUCKET"] != settings["TEST_S3_BUCKET"]
        assert settings["S3_ENDPOINT_URL"] == "http://storage:9000"
        assert settings["S3_PUBLIC_ENDPOINT_URL"] == "http://localhost:9020"
        assert "@db:5432/" in settings["DATABASE_URL"]
        assert str(settings["DEMO_MODE"]).lower() == "true"
        for dc in EXISTING.values():
            other = json.loads(
                run(
                    f"{service}-other-config-{dc[-1]}",
                    dc + ["config", "--format", "json"],
                    private_output=True,
                )
            )
            assert settings["S3_BUCKET"] != other["services"]["api"]["environment"].get(
                "S3_BUCKET", "stayhub-photos"
            )
    for service in config["services"].values():
        assert not service.get("container_name")
        for volume in service.get("volumes", []):
            if volume["type"] == "volume":
                assert volume["source"] in config["volumes"]
            else:
                assert volume["type"] == "bind" and volume["read_only"]
                assert Path(volume["source"]) == ROOT / "demo"
    assert not any(v.get("external") for v in config["volumes"].values())
    assert not any(v.get("external") for v in config["networks"].values())
    (OUT / "isolation.json").write_text(
        json.dumps(
            {
                "project": PROJECT,
                "ports": expected,
                "fresh_volumes": volumes,
                "buckets": sorted(buckets),
                "preexisting_containers": 0,
                "preexisting_project_volumes": 0,
                "ports_available": True,
                "no_external_mounts_or_networks": True,
                "private_env_mode": oct(
                    (ROOT / ".env.m61.local").stat().st_mode & 0o777
                ),
            },
            indent=2,
        )
        + "\n"
    )


def prepare():
    private = ROOT / ".env.m61.local"
    if private.exists():
        raise RuntimeError("Retained private configuration exists; never replace it")
    values = dict(
        line.split("=", 1)
        for line in (ROOT / ".env.example").read_text().splitlines()
        if line and not line.startswith("#") and "=" in line
    )
    values.update(
        POSTGRES_PASSWORD=secrets.token_urlsafe(32),
        JWT_SECRET=secrets.token_urlsafe(48),
        S3_ACCESS_KEY=secrets.token_hex(12),
        S3_SECRET_KEY=secrets.token_urlsafe(32),
        TRUSTED_ORIGINS="http://localhost:5193",
        S3_PUBLIC_ENDPOINT_URL="http://localhost:9020",
        S3_BUCKET="stayhub-m61-cold-photos",
        TEST_S3_BUCKET="stayhub-m61-cold-photos-test",
        DEMO_MODE="true",
    )
    for role in ["GUEST", "HOST", "ADMIN"]:
        values.update(
            {
                f"SEED_{role}_EMAIL": f"m61-{role.lower()}@example.com",
                f"SEED_{role}_PASSWORD": secrets.token_urlsafe(24),
                f"SEED_{role}_NAME": f"M61 Cold {role.title()}",
            }
        )
    fd = os.open(private, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as target:
        target.write(
            "\n".join(key + "=" + value for key, value in values.items()) + "\n"
        )
    print("Created private configuration from .env.example; no values logged.")


def browser(stage):
    values = dict(
        line.split("=", 1)
        for line in (ROOT / ".env.m61.local").read_text().splitlines()
        if "=" in line
    )
    env = os.environ.copy()
    env.update({key: value for key, value in values.items() if key.startswith("SEED_")})
    env.update(
        SMOKE_BASE_URL="http://localhost:5193",
        PLAYWRIGHT_JSON_OUTPUT_NAME=f"../evidence/m61/{stage}.json",
    )
    run(
        stage,
        [
            "npx",
            "playwright",
            "test",
            "e2e/cold-start.spec.ts",
            "-g",
            "fresh-volume" if stage == "browser-initial" else "seed reruns",
        ],
        cwd=ROOT / "frontend",
        env=env,
    )


def main():
    (OUT / "checks").mkdir(parents=True, exist_ok=True)
    stage = sys.argv[1]
    if stage == "prepare":
        prepare()
    elif stage in {"browser-initial", "browser-after"}:
        browser(stage)
    elif stage == "ledger":
        code = (ROOT / "scripts/m61-ledger.py").read_text()
        value = json.loads(
            run(
                "ledger",
                DC
                + ["exec", "-T", "api", "uv", "run", "--frozen", "python", "-c", code],
            )
        )
        (OUT / "ledger.json").write_text(json.dumps(value, indent=2) + "\n")
    elif stage == "quality":
        run(
            "sync-browser-source",
            DC
            + [
                "cp",
                "frontend/e2e/cold-start.spec.ts",
                "frontend:/app/e2e/cold-start.spec.ts",
            ],
        )
        for script in ["lint", "format-check", "typecheck"]:
            run(
                "quality-" + script,
                DC + ["exec", "-T", "frontend", "npm", "run", script],
            )
    elif stage == "preflight":
        preflight()
    elif stage in {"baseline", "preservation"}:
        values = {
            name: snapshot(f"{stage}-{name}", dc) for name, dc in EXISTING.items()
        }
        (OUT / f"{stage}.json").write_text(json.dumps(values, indent=2) + "\n")
        if stage == "preservation":
            before = json.loads((OUT / "baseline.json").read_text())
            result = {
                name: {
                    "all_table_hashes_identical": before[name]["tables"]
                    == value["tables"],
                    "all_object_hashes_identical": before[name]["objects"]
                    == value["objects"],
                    "clock_before": before[name]["offset_seconds"],
                    "clock_after": value["offset_seconds"],
                }
                for name, value in values.items()
            }
            (OUT / "preservation-result.json").write_text(
                json.dumps(result, indent=2) + "\n"
            )
            assert all(
                v["all_table_hashes_identical"]
                and v["all_object_hashes_identical"]
                and v["clock_before"] == v["clock_after"]
                for v in result.values()
            )
    elif stage == "setup":
        assert (OUT / "isolation.json").exists() and (OUT / "baseline.json").exists()
        run("dev-up", DC + ["up", "-d", "--build", "--wait"])
        # Prove the database and object store are initially empty before migration/seed.
        empty = """import json
from sqlalchemy import inspect
from app.db import get_engine
from app.storage import s3_client
names = inspect(get_engine()).get_table_names()
buckets = s3_client().list_buckets()['Buckets']
assert not names and not buckets
print(json.dumps({'application_tables': names, 'storage_buckets': buckets}))"""
        run(
            "empty-stores",
            DC + ["exec", "-T", "api", "uv", "run", "--frozen", "python", "-c", empty],
        )
        run(
            "migrate",
            DC
            + [
                "exec",
                "-T",
                "api",
                "uv",
                "run",
                "--frozen",
                "alembic",
                "upgrade",
                "head",
            ],
        )
        run(
            "storage-init",
            DC
            + [
                "exec",
                "-T",
                "api",
                "uv",
                "run",
                "--frozen",
                "python",
                "-m",
                "app.storage_setup",
            ],
        )
        run(
            "seed-demo",
            DC
            + [
                "exec",
                "-T",
                "api",
                "uv",
                "run",
                "--frozen",
                "python",
                "-m",
                "app.seed",
            ],
        )
        run(
            "seed-content",
            DC
            + [
                "exec",
                "-T",
                "api",
                "uv",
                "run",
                "--frozen",
                "python",
                "-m",
                "app.seed_content",
            ],
        )
        run("build-frontend", DC + ["exec", "-T", "frontend", "npm", "run", "build"])
        run(
            "build-backend",
            DC
            + [
                "exec",
                "-T",
                "api",
                "uv",
                "run",
                "--frozen",
                "python",
                "-c",
                "from app.main import app; assert app.openapi()['paths']; print('Backend imports/configuration/OpenAPI validated')",
            ],
        )
    elif stage == "repeat-restart":
        before = snapshot("cold-before-repeat", DC)
        for label, module in [
            ("storage-init-repeat", "app.storage_setup"),
            ("seed-demo-repeat", "app.seed"),
            ("seed-content-repeat", "app.seed_content"),
            ("seed-content-repeat2", "app.seed_content"),
        ]:
            run(
                label,
                DC
                + [
                    "exec",
                    "-T",
                    "api",
                    "uv",
                    "run",
                    "--frozen",
                    "python",
                    "-m",
                    module,
                ],
            )
        repeated = snapshot("cold-after-repeat", DC)
        # Content import performs a real seed-Host login on each invocation.
        auth_tables = {"sessions", "refresh_tokens"}
        for table in before["tables"]:
            if table in auth_tables:
                assert set(before["tables"][table]) <= set(repeated["tables"][table])
                assert (
                    len(repeated["tables"][table]) == len(before["tables"][table]) + 2
                )
            else:
                assert before["tables"][table] == repeated["tables"][table], table
        assert before["objects"] == repeated["objects"]
        assert before["offset_seconds"] == repeated["offset_seconds"]
        run(
            "restart",
            DC + ["restart", "db", "storage", "api", "frontend", "expiry-worker"],
        )
        run("wait-restart", DC + ["up", "-d", "--wait", "--no-build"])
        after = snapshot("cold-after-restart", DC)
        assert repeated == after, "Restart changed persisted rows/objects/clock"
        (OUT / "cold-persistence.json").write_text(
            json.dumps(
                {
                    "seed_business_rows_objects_clock_identical": True,
                    "expected_import_login_sessions_added": 2,
                    "restart_identical": True,
                    "snapshot": after,
                },
                indent=2,
            )
            + "\n"
        )
    else:
        raise ValueError(stage)


if __name__ == "__main__":
    main()
