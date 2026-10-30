"""Publish a checked frontend; retain assets and release snapshots for rollback."""

import argparse
import hashlib
import json
import re
import subprocess
import tempfile
from pathlib import Path


def aws(*args):
    return subprocess.check_output(["aws", *args], text=True).strip()


def publish(frontend, release, bucket, distribution):
    if not re.fullmatch(r"[a-f0-9]{40}", release):
        raise ValueError("release must be the full commit SHA")
    index = frontend / "index.html"
    if not index.is_file() or not (frontend / "assets").is_dir():
        raise ValueError("Expected built frontend with assets")
    # Reusing a release with different bytes would make rollback ambiguous.
    digest = hashlib.sha256(index.read_bytes()).hexdigest()
    snapshot = f"s3://{bucket}/releases/{release}/{digest}/"
    manifest = {"release": release, "index_sha256": digest, "files": {}}
    # No --delete: old pages and in-flight browser sessions still need old hashes.
    for path in sorted(frontend.rglob("*")):
        if not path.is_file():
            continue
        if path.is_symlink():
            raise ValueError("No frontend symlinks")
        name = path.relative_to(frontend).as_posix()
        manifest["files"][name] = hashlib.sha256(path.read_bytes()).hexdigest()
        aws(
            "s3",
            "cp",
            str(path),
            snapshot + name,
            "--cache-control",
            "no-cache",
            "--only-show-errors",
        )
        if name == "index.html":
            continue
        immutable = name.startswith("assets/") and re.search(
            r"-[A-Za-z0-9_-]{8,}\.", path.name
        )
        cache = "public,max-age=31536000,immutable" if immutable else "no-cache"
        aws(
            "s3",
            "cp",
            str(path),
            f"s3://{bucket}/{name}",
            "--cache-control",
            cache,
            "--only-show-errors",
        )
    with tempfile.TemporaryDirectory() as tmp:
        receipt = Path(tmp) / "frontend-release.json"
        receipt.write_text(json.dumps(manifest, sort_keys=True))
        aws(
            "s3",
            "cp",
            str(receipt),
            snapshot + "frontend-release.json",
            "--only-show-errors",
        )
    # Commit point: every referenced asset has been uploaded successfully.
    aws(
        "s3",
        "cp",
        str(index),
        f"s3://{bucket}/index.html",
        "--cache-control",
        "no-cache,max-age=0,must-revalidate",
        "--content-type",
        "text/html",
        "--only-show-errors",
    )
    invalidation = json.loads(
        aws(
            "cloudfront",
            "create-invalidation",
            "--distribution-id",
            distribution,
            "--paths",
            "/*",
        )
    )["Invalidation"]["Id"]
    aws(
        "cloudfront",
        "wait",
        "invalidation-completed",
        "--distribution-id",
        distribution,
        "--id",
        invalidation,
    )
    print(
        json.dumps(
            {
                "release": release,
                "index_sha256": digest,
                "snapshot": snapshot,
                "invalidation": invalidation,
            }
        )
    )


def rollback(snapshot, bucket, distribution):
    if not re.fullmatch(
        r"s3://" + re.escape(bucket) + r"/releases/[a-f0-9]{40}/[a-f0-9]{64}/", snapshot
    ):
        raise ValueError("Supply the exact release snapshot URL printed by publish")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        receipt = root / "receipt.json"
        aws(
            "s3",
            "cp",
            snapshot + "frontend-release.json",
            str(receipt),
            "--only-show-errors",
        )
        manifest = json.loads(receipt.read_text())
        if (
            snapshot
            != f"s3://{bucket}/releases/{manifest['release']}/{manifest['index_sha256']}/"
        ):
            raise ValueError("Snapshot identity mismatch")
        frontend = root / "frontend"
        frontend.mkdir()
        for name, digest in manifest["files"].items():
            target = frontend / name
            if not target.resolve().is_relative_to(
                frontend.resolve()
            ) or name.startswith("/"):
                raise ValueError("Invalid release path")
            target.parent.mkdir(exist_ok=True, parents=True)
            aws("s3", "cp", snapshot + name, str(target), "--only-show-errors")
            if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
                raise ValueError("Release file checksum mismatch")
        if (
            hashlib.sha256((frontend / "index.html").read_bytes()).hexdigest()
            != manifest["index_sha256"]
        ):
            raise ValueError("Index checksum mismatch")
        publish(frontend, manifest["release"], bucket, distribution)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--frontend", type=Path)
    mode.add_argument("--rollback-snapshot")
    p.add_argument("--release")
    p.add_argument("--bucket", required=True)
    p.add_argument("--distribution", required=True)
    a = p.parse_args()
    if a.rollback_snapshot:
        rollback(a.rollback_snapshot, a.bucket, a.distribution)
    else:
        if not a.release:
            p.error("--release is required with --frontend")
        publish(a.frontend, a.release, a.bucket, a.distribution)
