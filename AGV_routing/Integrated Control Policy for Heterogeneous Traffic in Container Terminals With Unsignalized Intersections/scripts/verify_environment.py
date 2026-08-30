"""Verify the exact local runtime selected for reconstructed experiments."""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
from hashlib import sha256
from importlib import metadata
from pathlib import Path

EXPECTED_PYTHON = (3, 13, 13)
EXPECTED_PACKAGES = {
    "eclipse-sumo": "1.27.1",
    "sumo-data": "1.27.1",
    "sumolib": "1.27.1",
    "traci": "1.27.1",
}
EXPECTED_PLATFORM = ("Windows", "AMD64")
EXPECTED_SUMO_VERSION = "1.27.1"
EXPECTED_UV_VERSION = "0.11.16"
SUMO_APPLICATIONS = ("sumo", "sumo-gui", "netconvert", "netgenerate")


def _application_version(
    application: str,
    bin_directory: Path,
    sumo_home: Path,
) -> tuple[Path, str]:
    suffix = ".exe" if os.name == "nt" else ""
    executable = (bin_directory / f"{application}{suffix}").resolve()
    if not executable.is_file():
        raise RuntimeError(f"missing SUMO application: {executable}")
    environment = os.environ.copy()
    environment["SUMO_HOME"] = str(sumo_home)
    environment["PATH"] = f"{bin_directory}{os.pathsep}{environment.get('PATH', '')}"
    completed = subprocess.run(
        [str(executable), "--version"],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
        env=environment,
    )
    output = "\n".join(
        part.strip() for part in (completed.stdout, completed.stderr) if part.strip()
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"{application} --version failed with code {completed.returncode}: {output}"
        )
    first_line = output.splitlines()[0] if output else ""
    if not (
        first_line.startswith("Eclipse SUMO ") and first_line.endswith(f" {EXPECTED_SUMO_VERSION}")
    ):
        raise RuntimeError(f"{application} does not report SUMO {EXPECTED_SUMO_VERSION}: {output}")
    return executable, output


def _uv_provenance() -> dict[str, str]:
    executable_name = shutil.which("uv")
    if executable_name is None:
        raise RuntimeError("uv is not available on PATH")
    executable = Path(executable_name).resolve()
    completed = subprocess.run(
        [str(executable), "--version"],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    output = "\n".join(
        part.strip() for part in (completed.stdout, completed.stderr) if part.strip()
    )
    fields = output.split()
    if completed.returncode != 0 or fields[:2] != ["uv", EXPECTED_UV_VERSION]:
        raise RuntimeError(f"uv {EXPECTED_UV_VERSION} required; command reported: {output}")
    return {"version": EXPECTED_UV_VERSION, "executable": str(executable)}


def verify_environment() -> dict[str, object]:
    """Return provenance if every runtime component matches the pin."""

    if sys.version_info[:3] != EXPECTED_PYTHON:
        actual = ".".join(str(part) for part in sys.version_info[:3])
        expected = ".".join(str(part) for part in EXPECTED_PYTHON)
        raise RuntimeError(f"Python {expected} required; found {actual}")

    actual_platform = (platform.system(), platform.machine())
    if actual_platform != EXPECTED_PLATFORM:
        raise RuntimeError(f"platform {EXPECTED_PLATFORM!r} required; found {actual_platform!r}")

    project_root = Path(__file__).resolve().parents[1]
    lock_path = project_root / "uv.lock"
    if not lock_path.is_file():
        raise RuntimeError(f"missing lock file: {lock_path}")

    package_records: dict[str, dict[str, str]] = {}
    for package_name, expected_version in EXPECTED_PACKAGES.items():
        actual_version = metadata.version(package_name)
        if actual_version != expected_version:
            raise RuntimeError(
                f"{package_name} {expected_version} required; found {actual_version}"
            )
        distribution = metadata.distribution(package_name)
        package_records[package_name] = {
            "version": actual_version,
            "location": str(distribution.locate_file("").resolve()),
        }

    configured_sumo_home = os.environ.get("SUMO_HOME")

    import sumolib
    import traci

    imported_modules = {"sumolib": sumolib, "traci": traci}
    import_paths: dict[str, str] = {}
    for package_name, module in imported_modules.items():
        actual_path = Path(module.__file__).resolve()
        expected_path = Path(
            metadata.distribution(package_name).locate_file(f"{package_name}/__init__.py")
        ).resolve()
        if actual_path != expected_path:
            raise RuntimeError(
                f"{package_name} imported from {actual_path}, not pinned "
                f"distribution {expected_path}"
            )
        import_paths[package_name] = str(actual_path)

    sumo_home = Path(metadata.distribution("eclipse-sumo").locate_file("sumo")).resolve()
    bin_directory = sumo_home / "bin"
    if configured_sumo_home:
        configured = Path(configured_sumo_home).resolve()
        if configured != sumo_home:
            raise RuntimeError(f"SUMO_HOME points to {configured}, not pinned wheel {sumo_home}")

    applications: dict[str, dict[str, str]] = {}
    for application in SUMO_APPLICATIONS:
        executable, output = _application_version(
            application,
            bin_directory,
            sumo_home,
        )
        applications[application] = {
            "executable": str(executable),
            "version_output": output,
        }

    return {
        "python": {
            "version": platform.python_version(),
            "executable": str(Path(sys.executable).resolve()),
            "implementation": platform.python_implementation(),
        },
        "uv": _uv_provenance(),
        "uv_lock": {
            "path": str(lock_path),
            "sha256": sha256(lock_path.read_bytes()).hexdigest(),
        },
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
        },
        "packages": package_records,
        "imports": import_paths,
        "sumo_home": str(sumo_home),
        "configured_sumo_home": configured_sumo_home,
        "applications": applications,
    }


def main() -> int:
    """Print machine-readable environment provenance."""

    try:
        report = verify_environment()
    except (ImportError, metadata.PackageNotFoundError, RuntimeError) as exc:
        print(f"environment verification failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
