"""Receiver v2: backend-only v2 and legacy v1; lock precedes network/staging."""

import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path, PurePosixPath

RECEIVER_VERSION = 2


def extract_verified(archive, destination):
    with tarfile.open(archive, "r:gz") as source:
        total = 0
        seen = set()
        for member in source:
            path = PurePosixPath(member.name)
            if (
                path.is_absolute()
                or ".." in path.parts
                or not path.parts
                or (
                    path.parts[0] not in {"frontend", "deploy", "demo"}
                    and member.name != "release.json"
                )
                or not (member.isdir() or member.isfile())
                or member.name in seen
            ):
                raise ValueError("Unsafe or duplicate archive member")
            seen.add(member.name)
            total += member.size
            if total > 256 * 1024 * 1024:
                raise ValueError("Release exceeds expanded size limit")
            target = destination.joinpath(*path.parts)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with (
                    source.extractfile(member) as incoming,
                    target.open("xb") as outgoing,
                ):
                    shutil.copyfileobj(incoming, outgoing)
        metadata = destination / "release.json"
        if metadata.exists():
            if json.loads(metadata.read_text()) != {
                "format": "stayhub-backend",
                "version": 2,
            }:
                raise ValueError("Unsupported release format")
            if any(name == "frontend" or name.startswith("frontend/") for name in seen):
                raise ValueError("Backend release contains frontend files")
        elif not (destination / "frontend/index.html").is_file():
            raise ValueError("Incomplete legacy release")
        for required in [
            "deploy/release.sh",
            "deploy/compose.yaml",
            "deploy/provision.sh",
            "demo/assets/manifest.json",
        ]:
            if not (destination / required).is_file():
                raise ValueError("Incomplete release")
    manifest = json.loads((destination / "demo/assets/manifest.json").read_text())
    for asset in manifest["assets"]:
        path = destination / "demo/assets" / asset["file"]
        if not path.resolve().is_relative_to((destination / "demo/assets").resolve()):
            raise ValueError("Asset path escapes manifest")
        if (
            not asset.get("license")
            or not asset.get("license_url")
            or path.stat().st_size != asset["bytes"]
            or hashlib.sha256(path.read_bytes()).hexdigest() != asset["sha256"]
        ):
            raise ValueError("Asset license/size/hash verification failed")


def receive(root, release, digest, bucket):
    if not re.fullmatch("[a-f0-9]{40}", release) or not re.fullmatch(
        "[a-f0-9]{64}", digest
    ):
        raise ValueError("Invalid release identity/digest")
    root.mkdir(parents=True, exist_ok=True)
    with (root / "deploy.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        releases = root / "releases"
        releases.mkdir(exist_ok=True)
        final = releases / release
        if final.exists():
            if (final / "artifact.sha256").read_text().strip() != digest:
                raise ValueError("Immutable release already exists with another digest")
            if (root / "current").resolve() == final.resolve():
                config = json.loads((root / "config.json").read_text())
                subprocess.run(
                    [
                        "python3",
                        str(final / "deploy/verify-https.py"),
                        "https://" + config["ip"],
                    ],
                    check=True,
                )
                print("Release already active; public API verified; no files changed")
                return
            # A retry never runs scripts that write inside an existing directory.
            raise ValueError(
                "Release directory already exists; use a new commit for redeployment"
            )
        with tempfile.TemporaryDirectory(prefix=".incoming-", dir=root) as staging:
            stage = Path(staging)
            archive = stage / "release.tar.gz"
            subprocess.run(
                [
                    "aws",
                    "s3",
                    "cp",
                    f"s3://{bucket}/releases/{release}/{digest}.tar.gz",
                    str(archive),
                    "--region",
                    "us-east-1",
                ],
                check=True,
            )
            if archive.stat().st_size > 128 * 1024 * 1024:
                raise ValueError("Compressed release exceeds size limit")
            if hashlib.sha256(archive.read_bytes()).hexdigest() != digest:
                raise ValueError("Artifact checksum mismatch")
            payload = stage / "payload"
            payload.mkdir()
            extract_verified(archive, payload)
            (payload / "artifact.sha256").write_text(digest + "\n")
            payload.rename(final)
        env = os.environ | {"STAYHUB_LOCK_FD": str(lock.fileno())}
        subprocess.run(
            ["bash", str(final / "deploy/release.sh"), release],
            env=env,
            pass_fds=(lock.fileno(),),
            check=True,
        )


if __name__ == "__main__":
    try:
        receive(
            Path(os.environ.get("STAYHUB_ROOT", "/opt/stayhub")),
            sys.argv[1],
            sys.argv[2],
            sys.argv[3],
        )
    except (ValueError, OSError, subprocess.CalledProcessError, tarfile.TarError):
        raise SystemExit(
            "Release rejected or deployment failed; active release was not overwritten."
        ) from None
