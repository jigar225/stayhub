"""Affected application checks against disposable Postgres/S3, never dev services."""

import subprocess
import time
import uuid
from pathlib import Path

project = Path(__file__).resolve().parents[2]
name = "stayhub-readiness-" + uuid.uuid4().hex[:10]
containers = []


def docker(*args, **kwargs):
    return subprocess.run(["docker", *args], check=True, **kwargs)


docker("network", "create", name, stdout=subprocess.DEVNULL)
try:
    db, storage = name + "-db", name + "-storage"
    containers.extend([db, storage])
    docker(
        "run",
        "-d",
        "--name",
        db,
        "--network",
        name,
        "--network-alias",
        "db",
        "--tmpfs",
        "/var/lib/postgresql",
        "-e",
        "POSTGRES_USER=stayhub_test",
        "-e",
        "POSTGRES_PASSWORD=isolated-test",
        "-e",
        "POSTGRES_DB=stayhub_test",
        "postgres:18.6-alpine",
        stdout=subprocess.DEVNULL,
    )
    docker(
        "run",
        "-d",
        "--name",
        storage,
        "--network",
        name,
        "--network-alias",
        "storage",
        "--tmpfs",
        "/data",
        "-e",
        "RUSTFS_ACCESS_KEY=test-key",
        "-e",
        "RUSTFS_SECRET_KEY=test-secret-123456",
        "-e",
        "RUSTFS_CONSOLE_ENABLE=false",
        "--user",
        "0",
        "rustfs/rustfs:1.0.3-glibc",
        "/data",
        stdout=subprocess.DEVNULL,
    )
    for _attempt in range(60):
        db_ok = (
            subprocess.run(
                [
                    "docker",
                    "exec",
                    db,
                    "pg_isready",
                    "-U",
                    "stayhub_test",
                    "-d",
                    "stayhub_test",
                ],
                check=False,
                capture_output=True,
            ).returncode
            == 0
        )
        s3_ok = (
            subprocess.run(
                [
                    "docker",
                    "exec",
                    storage,
                    "curl",
                    "--fail",
                    "--silent",
                    "http://localhost:9000/health/ready",
                ],
                check=False,
                capture_output=True,
            ).returncode
            == 0
        )
        if db_ok and s3_ok:
            break
        time.sleep(2)
    else:
        raise RuntimeError("Disposable test services failed readiness")
    docker(
        "run",
        "--rm",
        "--network",
        name,
        "-v",
        f"{project}/backend:/source:ro",
        "-w",
        "/source",
        "-e",
        "PYTHONPATH=/source",
        "-e",
        "TEST_DATABASE_URL=postgresql+psycopg://stayhub_test:isolated-test@db:5432/stayhub_test",
        "-e",
        "TEST_S3_BUCKET=readiness-test",
        "-e",
        "S3_BUCKET=unused-development",
        "-e",
        "S3_ENDPOINT_URL=http://storage:9000",
        "-e",
        "S3_ACCESS_KEY=test-key",
        "-e",
        "S3_SECRET_KEY=test-secret-123456",
        "--entrypoint",
        "/app/.venv/bin/pytest",
        "stayhub-api:latest",
        "-p",
        "no:cacheprovider",
        "tests/test_auth.py",
        "tests/test_storage_isolation.py",
        "tests/test_discovery.py::test_content_import_partial_resume_rerun_and_preserve_host_edits",
        "-q",
    )
finally:
    for container in containers:
        subprocess.run(
            ["docker", "rm", "-f", container],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    subprocess.run(
        ["docker", "network", "rm", name], check=False, stdout=subprocess.DEVNULL
    )
