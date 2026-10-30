"""Build a deterministic, allowlisted release with licensed demo assets."""

import argparse
import gzip
import hashlib
import io
import json
import tarfile
from pathlib import Path


def package(project, output):
    assets = project / "demo/assets"
    manifest = json.loads((assets / "manifest.json").read_text())
    selected = [(project / "infra/deploy", "deploy")]
    files = {}
    for directory, prefix in selected:
        for path in directory.rglob("*"):
            if (
                path.is_file()
                and "__pycache__" not in path.parts
                and path.suffix != ".pyc"
                and path.name != "receive-bootstrap-v1.py"
            ):
                if path.is_symlink():
                    raise ValueError("No symbolic links in releases")
                files[f"{prefix}/{path.relative_to(directory)}"] = path
    files["demo/assets/manifest.json"] = assets / "manifest.json"
    for asset in manifest["assets"]:
        path = assets / asset["file"]
        if (
            not path.resolve().is_relative_to(assets.resolve())
            or path.is_symlink()
            or not asset.get("license")
            or not asset.get("license_url")
            or path.stat().st_size != asset["bytes"]
            or hashlib.sha256(path.read_bytes()).hexdigest() != asset["sha256"]
        ):
            raise ValueError("Licensed demo asset verification failed")
        files[f"demo/assets/{asset['file']}"] = path
    with (
        output.open("wb") as target,
        gzip.GzipFile(fileobj=target, mode="wb", mtime=0, filename="") as zipped,
    ):
        with tarfile.open(fileobj=zipped, mode="w") as archive:
            metadata = json.dumps(
                {"format": "stayhub-backend", "version": 2}, sort_keys=True
            ).encode()
            info = tarfile.TarInfo("release.json")
            info.size, info.mode, info.mtime = len(metadata), 0o644, 0
            archive.addfile(info, io.BytesIO(metadata))
            for name, path in sorted(files.items()):
                data = path.read_bytes()
                info = tarfile.TarInfo(name)
                info.size, info.mode, info.mtime = len(data), 0o644, 0
                archive.addfile(info, io.BytesIO(data))
    return hashlib.sha256(output.read_bytes()).hexdigest()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(package(Path(__file__).resolve().parents[2], args.output))
