#!/usr/bin/env python3
"""Build, inspect, install, and smoke-test a distributable package."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import tomllib
from email.parser import Parser
from pathlib import Path
from tarfile import ReadError, open as open_tar
from typing import Any, Iterable
from zipfile import BadZipFile, ZipFile


REQUIRED_RESOURCES = (
    "codeagent/resources/prompts/system.md",
    "codeagent/resources/skills/commit-message/SKILL.md",
    "codeagent/resources/skills/dependency-audit/SKILL.md",
)
SENSITIVE_NAMES = {".env", ".envrc", "credentials.json", "secrets.json"}
class PackageInspectionError(RuntimeError):
    """Raised when a distribution is not safe or complete enough to publish."""


def _normalise_name(value: str) -> str:
    return value.replace("-", "_").lower()


def _is_sensitive(member: str) -> bool:
    parts = {part.lower() for part in Path(member).parts}
    basename = Path(member).name.lower()
    return bool(parts & SENSITIVE_NAMES) or basename in SENSITIVE_NAMES or basename.endswith(
        (".pem", ".key")
    )


def _read_zip_members(path: Path) -> tuple[list[str], dict[str, bytes]]:
    try:
        with ZipFile(path) as archive:
            names = archive.namelist()
            return names, {name: archive.read(name) for name in names if not name.endswith("/")}
    except (OSError, BadZipFile) as exc:
        raise PackageInspectionError(f"cannot read wheel: {path.name}") from exc


def _read_tar_members(path: Path) -> tuple[list[str], dict[str, bytes]]:
    try:
        with open_tar(path, "r:gz") as archive:
            members = [member for member in archive.getmembers() if member.isfile()]
            contents: dict[str, bytes] = {}
            for member in members:
                extracted = archive.extractfile(member)
                if extracted is not None:
                    contents[member.name] = extracted.read()
            return [member.name for member in members], contents
    except (OSError, ReadError) as exc:
        raise PackageInspectionError(f"cannot read source distribution: {path.name}") from exc


def _archive_contents(path: Path) -> tuple[list[str], dict[str, bytes]]:
    if path.suffix == ".whl":
        return _read_zip_members(path)
    if path.name.endswith(".tar.gz"):
        return _read_tar_members(path)
    raise PackageInspectionError(f"unsupported distribution: {path.name}")


def _metadata(contents: dict[str, bytes]) -> tuple[str | None, str | None]:
    metadata_path = next((name for name in contents if name.endswith(".dist-info/METADATA")), None)
    if metadata_path is not None:
        message = Parser().parsestr(contents[metadata_path].decode("utf-8"))
        return message.get("Name"), message.get("Version")

    pyproject_path = next((name for name in contents if name.endswith("/pyproject.toml")), None)
    if pyproject_path is not None:
        project = tomllib.loads(contents[pyproject_path].decode("utf-8")).get("project", {})
        if isinstance(project, dict):
            return project.get("name"), project.get("version")
    return None, None


def _resource_present(member_names: Iterable[str], resource: str, *, sdist: bool) -> bool:
    if not sdist:
        return resource in member_names
    return any(name.endswith(f"/src/{resource}") for name in member_names)


def inspect_distribution(
    path: Path, *, expected_name: str, expected_version: str
) -> dict[str, Any]:
    """Inspect one wheel or sdist and return a safe, serialisable report."""
    members, contents = _archive_contents(path)
    if any(_is_sensitive(name) for name in members):
        raise PackageInspectionError(f"sensitive file found in {path.name}")

    package_name, package_version = _metadata(contents)
    if _normalise_name(package_name or "") != _normalise_name(expected_name):
        raise PackageInspectionError(f"package name mismatch in {path.name}")
    if package_version != expected_version:
        raise PackageInspectionError(f"package version mismatch in {path.name}")

    is_sdist = path.name.endswith(".tar.gz")
    missing = [
        resource
        for resource in REQUIRED_RESOURCES
        if not _resource_present(members, resource, sdist=is_sdist)
    ]
    if missing:
        raise PackageInspectionError(f"required resources missing from {path.name}: {missing}")

    return {
        "status": "passed",
        "name": package_name,
        "version": package_version,
        "filename": path.name,
        "format": "sdist" if is_sdist else "wheel",
        "member_count": len(members),
        "required_resources": len(REQUIRED_RESOURCES),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def _run(command: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )


def _venv_python(path: Path) -> Path:
    executable = "python.exe" if os.name == "nt" else "python"
    relative = Path("Scripts") if os.name == "nt" else Path("bin")
    return path / relative / executable


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def run_release_check(*, root: Path, dist_dir: Path, report_path: Path) -> dict[str, Any]:
    """Run the complete release check and write its machine-readable report."""
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="codeagent-release-check-") as temporary:
        temporary_root = Path(temporary)
        build = _run(["uv", "build", "--out-dir", str(dist_dir)], cwd=root)
        _write_text(report_path.parent / "release-build.stdout.log", build.stdout)
        _write_text(report_path.parent / "release-build.stderr.log", build.stderr)
        if build.returncode != 0:
            raise RuntimeError(f"uv build failed with exit code {build.returncode}")

        distributions = sorted(dist_dir.glob("*.whl")) + sorted(dist_dir.glob("*.tar.gz"))
        if not distributions:
            raise RuntimeError("uv build produced no wheel or source distribution")
        with (root / "pyproject.toml").open("rb") as stream:
            project = tomllib.load(stream)["project"]
        inspections = [
            inspect_distribution(
                path,
                expected_name=str(project["name"]),
                expected_version=str(project["version"]),
            )
            for path in distributions
        ]
        _write_text(
            report_path.parent / "checksums.sha256",
            "".join(f"{item['sha256']}  {item['filename']}\n" for item in inspections),
        )

        venv = temporary_root / "venv"
        venv_result = _run(["uv", "venv", str(venv)], cwd=root)
        if venv_result.returncode != 0:
            raise RuntimeError(f"uv venv failed with exit code {venv_result.returncode}")
        python = _venv_python(venv)
        wheel = next(path for path in distributions if path.suffix == ".whl")
        install = _run(["uv", "pip", "install", "--python", str(python), str(wheel)], cwd=root)
        _write_text(report_path.parent / "release-install.stdout.log", install.stdout)
        _write_text(report_path.parent / "release-install.stderr.log", install.stderr)
        if install.returncode != 0:
            raise RuntimeError(f"wheel install failed with exit code {install.returncode}")

        smoke_result_path = report_path.parent / "package-smoke.json"
        smoke_environment = os.environ.copy()
        smoke_environment.update({"LLM_PROVIDER": "fake"})
        for key in ("DEEPSEEK_API_KEY", "OPENAI_API_KEY", "PYTHONPATH"):
            smoke_environment.pop(key, None)
        smoke = _run(
            [str(python), str(root / "scripts" / "package_smoke.py"), "--output", str(smoke_result_path)],
            cwd=temporary_root,
            env=smoke_environment,
        )
        _write_text(report_path.parent / "package-smoke.stdout.log", smoke.stdout)
        _write_text(report_path.parent / "package-smoke.stderr.log", smoke.stderr)
        if smoke.returncode != 0:
            raise RuntimeError(f"package smoke failed with exit code {smoke.returncode}")
        smoke_payload = json.loads(smoke_result_path.read_text(encoding="utf-8"))

    return {
        "schema_version": 1,
        "status": "passed",
        "project": project["name"],
        "version": project["version"],
        "python": sys.version.split()[0],
        "platform": sys.platform,
        "checks": {
            "build": "passed",
            "distribution_contents": "passed",
            "clean_install": "passed",
            "package_smoke": "passed",
        },
        "distributions": inspections,
        "smoke": smoke_payload,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist-dir", type=Path, default=Path("artifacts/dist"))
    parser.add_argument("--output", type=Path, default=Path("artifacts/release-check.json"))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    try:
        report = run_release_check(root=root, dist_dir=args.dist_dir.resolve(), report_path=args.output.resolve())
    except (
        OSError,
        RuntimeError,
        StopIteration,
        PackageInspectionError,
        json.JSONDecodeError,
        subprocess.SubprocessError,
    ) as exc:
        report = {"schema_version": 1, "status": "failed", "error": str(exc)}
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
