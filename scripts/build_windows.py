"""Build an offline Windows installer from committed source and a private Python runtime.

Run with a Windows x64 Python 3.13 build environment. End users do not run pip.
The supplied Python embeddable archive must be obtained from python.org.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import zipfile

from build_preview import build


def unpack(archive_path, destination):
    with zipfile.ZipFile(archive_path) as archive:
        for name in archive.namelist():
            path = (destination / name).resolve()
            if not path.is_relative_to(destination.resolve()):
                raise ValueError("Archive contains an unsafe path")
        archive.extractall(destination)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--python-zip", type=Path, required=True)
    parser.add_argument("--python-sha256", required=True)
    parser.add_argument("--iscc", type=Path, required=True)
    args = parser.parse_args()
    if sys.platform != "win32" or sys.version_info[:2] != (3, 13) or platform.machine().lower() not in ("amd64", "x86_64"):
        parser.error("Build with Windows x64 Python 3.13")
    output = args.output_dir
    if not output.is_absolute() or output.exists():
        parser.error("--output-dir must be an absolute, nonexistent directory")
    if hashlib.sha256(args.python_zip.read_bytes()).hexdigest() != args.python_sha256.lower():
        parser.error("Python archive checksum mismatch")
    if not args.iscc.is_file():
        parser.error("Inno Setup compiler not found")
    compiler = Path(os.environ["WINDIR"]) / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"
    if not compiler.is_file():
        parser.error("The .NET Framework C# compiler is required on the build machine")
    root = Path(__file__).resolve().parents[1]
    output.mkdir(parents=True)
    source_zip = output / "source.zip"
    source = build(root, source_zip)
    unpack(source_zip, output / "source")
    snapshot = output / "source/deep-thesis"
    bundle = output / "bundle"
    bundle.mkdir()
    shutil.move(str(snapshot), bundle / "app")
    app = bundle / "app"
    runtime = bundle / "runtime"
    unpack(args.python_zip, runtime)
    # Isolated paths: never load the user's Python packages or the source checkout.
    (runtime / "python313._pth").write_text("python313.zip\n.\nLib/site-packages\nimport site\n", encoding="utf-8")
    environment = dict(os.environ, PYTHONIOENCODING="utf-8", PIP_DISABLE_PIP_VERSION_CHECK="1")
    subprocess.run([
        sys.executable, "-m", "pip", "--isolated", "install", "--no-compile",
        "--index-url", "https://pypi.org/simple",
        "--extra-index-url", "https://download.pytorch.org/whl/cpu",
        "--target", str(runtime / "Lib/site-packages"),
        "--report", str(output / "dependency-report.json"),
        "torch==2.8.0+cpu", "pip==25.2", str(app / "backend"),
    ], check=True, env=environment)
    subprocess.run([str(compiler), "/nologo", "/target:winexe", "/platform:x64",
                    "/reference:System.Windows.Forms.dll", "/reference:System.Drawing.dll",
                    "/reference:System.Web.Extensions.dll", "/out:" + str(bundle / "DeepThesis.exe"),
                    str(app / "packaging/windows/Launcher.cs")], check=True)
    # Run the existing installed-distribution check with the shipped interpreter.
    clean_environment = {key: value for key, value in environment.items()
                         if not key.startswith(("THESIS_", "DOCX_", "PYTHONPATH", "PYTHONHOME"))}
    subprocess.run([str(runtime / "python.exe"), str(app / "scripts/verify_installed_runtime.py"),
                    "--output-dir", str(output / "installed-check")],
                   cwd=output, env=clean_environment, check=True)
    manifest = {"kind": "windows-installer-beta", "source_commit": source["source_commit"],
                "python_archive_sha256": args.python_sha256.lower(), "signed": False,
                "files": {}}
    for path in sorted(bundle.rglob("*")):
        if path.is_file():
            with path.open("rb") as stream:
                manifest["files"][path.relative_to(bundle).as_posix()] = hashlib.file_digest(stream, "sha256").hexdigest()
    (bundle / "bundle-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    subprocess.run([str(args.iscc), "/DBundleDir=" + str(bundle), "/DOutputDir=" + str(output),
                    str(app / "packaging/windows/deep-thesis.iss")], check=True)
    installer = next(output.glob("*-setup.exe"))
    with installer.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    (output / "SHA256SUMS.txt").write_text(f"{digest}  {installer.name}\n", encoding="ascii")
    print(json.dumps({"installer": str(installer), "source_commit": source["source_commit"],
                      "sha256": digest}, ensure_ascii=False))


if __name__ == "__main__":
    main()
