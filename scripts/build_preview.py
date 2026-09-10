"""Export an auditable source preview from committed Git content only."""

import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import subprocess
import tarfile
import zipfile


INCLUDE = ["backend", "ui", "LICENSE", "NOTICE", "THIRD_PARTY_NOTICES.md",
           "README.md", "ROADMAP.md", "scripts/run_preview.py", "scripts/serve_preview_ui.py", "scripts/verify_installed_runtime.py", "docs/本地预览指南.md",
           "docs/数据备份与恢复指南.md", "docs/存储迁移指南.md", "docs/独立Worker部署指南.md"]


def build(root, output):
    root, output = Path(root), Path(output)
    if not output.is_absolute() or output.exists():
        raise ValueError("Output must be an absolute, nonexistent ZIP path")
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    archive = subprocess.check_output(["git", "archive", "--format=tar", revision, *INCLUDE], cwd=root)
    files = {}
    with tarfile.open(fileobj=io.BytesIO(archive)) as source:
        for entry in source:
            if entry.isdir():
                continue
            path = PurePosixPath(entry.name)
            if not entry.isfile() or path.is_absolute() or ".." in path.parts:
                raise ValueError("Unsupported archive entry")
            if (path.name.startswith(".env") and path.name != ".env.example") or path.suffix in (".db", ".sqlite", ".sqlite3"):
                raise ValueError("Runtime data or local configuration is tracked; refusing bundle")
            files[entry.name] = source.extractfile(entry).read()
    manifest = {"format": 1, "source_commit": revision, "kind": "source-preview",
                "files": {name: hashlib.sha256(content).hexdigest() for name, content in files.items()}}
    output.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation avoids overwriting a previously delivered bundle.
    with output.open("xb") as stream, zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as target:
        for name, content in files.items():
            target.writestr("deep-thesis/" + name, content)
        target.writestr("deep-thesis/preview-manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    return manifest


def main():
    parser = argparse.ArgumentParser(description="Build a committed Deep Thesis source preview ZIP")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    manifest = build(Path(__file__).resolve().parents[1], Path(args.output))
    print(f"Preview built from {manifest['source_commit']}: {args.output}")


if __name__ == "__main__":
    main()
