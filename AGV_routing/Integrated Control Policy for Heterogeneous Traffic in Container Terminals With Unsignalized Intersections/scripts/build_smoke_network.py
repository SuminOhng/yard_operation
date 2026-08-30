"""Build the deterministic one-intersection SUMO smoke network."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path
from tempfile import TemporaryDirectory
from xml.etree import ElementTree

PROJECT_ROOT = Path(__file__).resolve().parents[1]
NETWORK_DIR = PROJECT_ROOT / "sumo" / "networks" / "smoke_intersection"
SOURCE_FILES = (
    "smoke.nod.xml",
    "smoke.edg.xml",
    "smoke.con.xml",
    "smoke.tll.xml",
)
OUTPUT_FILE = "smoke.net.xml"
EXPECTED_CONTROLLED_LINKS = {
    ("w_in", "e_out", 0),
    ("s_in", "n_out", 1),
}
EXPECTED_SUMO_VERSION = "1.27.1"


def _wheel_sumo_home() -> Path:
    try:
        installed = distribution("eclipse-sumo")
    except PackageNotFoundError as error:
        raise RuntimeError(
            "eclipse-sumo is not installed; run `uv sync --frozen --extra dev`"
        ) from error
    if installed.version != EXPECTED_SUMO_VERSION:
        raise RuntimeError(
            f"eclipse-sumo {EXPECTED_SUMO_VERSION} required; found {installed.version}"
        )
    package_root = Path(installed.locate_file("sumo")).resolve()
    if not package_root.is_dir():
        raise RuntimeError(f"eclipse-sumo distribution has no SUMO directory: {package_root}")
    return package_root


def _run_netconvert(output_path: Path) -> None:
    missing = [name for name in SOURCE_FILES if not (NETWORK_DIR / name).is_file()]
    if missing:
        joined = ", ".join(missing)
        raise RuntimeError(f"missing smoke network source file(s): {joined}")

    sumo_home = _wheel_sumo_home()
    binary_name = "netconvert.exe" if os.name == "nt" else "netconvert"
    netconvert = sumo_home / "bin" / binary_name
    if not netconvert.is_file():
        raise RuntimeError(f"wheel-bundled netconvert not found: {netconvert}")

    output_argument = (
        OUTPUT_FILE if output_path.parent.resolve() == NETWORK_DIR.resolve() else str(output_path)
    )
    command = [
        str(netconvert),
        "--node-files",
        SOURCE_FILES[0],
        "--edge-files",
        SOURCE_FILES[1],
        "--connection-files",
        SOURCE_FILES[2],
        "--tllogic-files",
        SOURCE_FILES[3],
        "--output-file",
        output_argument,
        "--no-turnarounds",
        "true",
        "--junctions.corner-detail",
        "0",
    ]
    child_env = os.environ.copy()
    child_env["SUMO_HOME"] = str(sumo_home)
    child_env["PATH"] = os.pathsep.join((str(sumo_home / "bin"), child_env.get("PATH", "")))

    completed = subprocess.run(
        command,
        cwd=NETWORK_DIR,
        env=child_env,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        rendered = subprocess.list2cmdline(command)
        details = "\n".join(
            part.strip() for part in (completed.stdout, completed.stderr) if part.strip()
        )
        raise RuntimeError(
            f"netconvert failed with exit code {completed.returncode}\n"
            f"command: {rendered}\n{details}"
        )

    if not output_path.is_file() or output_path.stat().st_size == 0:
        raise RuntimeError(f"netconvert did not create a usable file: {output_path}")


def _parse_network(path: Path) -> ElementTree.Element:
    try:
        return ElementTree.parse(path).getroot()
    except (OSError, ElementTree.ParseError) as error:
        raise RuntimeError(f"cannot parse generated SUMO network: {path}") from error


def _structural_signature(element: ElementTree.Element) -> tuple[object, ...]:
    """Ignore comments, formatting, and attribute order in generated XML."""

    return (
        element.tag,
        tuple(sorted(element.attrib.items())),
        (element.text or "").strip(),
        tuple(_structural_signature(child) for child in element),
    )


def _validate_controlled_links(root: ElementTree.Element, path: Path) -> None:
    controlled_links = [
        (
            connection.get("from", ""),
            connection.get("to", ""),
            int(connection.get("linkIndex", "-1")),
        )
        for connection in root.findall("connection")
        if connection.get("tl") == "junction"
    ]
    if len(controlled_links) != 2 or set(controlled_links) != EXPECTED_CONTROLLED_LINKS:
        raise RuntimeError(
            f"unexpected junction controlled-link mapping in {path}: {controlled_links!r}"
        )


def build_network() -> Path:
    output_path = NETWORK_DIR / OUTPUT_FILE
    _run_netconvert(output_path)
    _validate_controlled_links(_parse_network(output_path), output_path)
    print(f"built {output_path}")
    return output_path


def check_network() -> Path:
    committed_path = NETWORK_DIR / OUTPUT_FILE
    if not committed_path.is_file():
        raise RuntimeError(f"committed network is missing; run the build command: {committed_path}")

    committed_root = _parse_network(committed_path)
    _validate_controlled_links(committed_root, committed_path)
    with TemporaryDirectory(prefix="irbp-smoke-network-") as temporary_dir:
        rebuilt_path = Path(temporary_dir) / OUTPUT_FILE
        _run_netconvert(rebuilt_path)
        rebuilt_root = _parse_network(rebuilt_path)
        _validate_controlled_links(rebuilt_root, rebuilt_path)
        if _structural_signature(committed_root) != _structural_signature(rebuilt_root):
            raise RuntimeError(
                "committed smoke.net.xml differs from its PlainXML sources; "
                "run `python scripts/build_smoke_network.py`"
            )

    print(f"checked {committed_path}")
    return committed_path


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify the committed network without rewriting repository files",
    )
    return parser.parse_args()


if __name__ == "__main__":
    try:
        arguments = _parse_args()
        check_network() if arguments.check else build_network()
    except RuntimeError as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1) from error
