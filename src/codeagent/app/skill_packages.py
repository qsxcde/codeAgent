"""Skill Package discovery, installation and registry persistence.

The first package runtime is intentionally content-only: package manifests and
``skills/**/SKILL.md`` are read, while harness-specific executable extensions
remain inert.  The module has no dependency on the model or TUI layers so it
can be used by both CLI and interactive commands.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

PACKAGE_MANIFEST_FILE = "codeagent-package.json"
PACKAGE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

__all__ = [
    "PACKAGE_MANIFEST_FILE",
    "PackageDiagnostic",
    "PackageManager",
    "PackageManifest",
    "PackageRecord",
    "PackageRegistry",
    "PackageValidationError",
    "parse_package_manifest",
]


class PackageValidationError(ValueError):
    """Raised when a package cannot be safely loaded."""


@dataclass(frozen=True)
class PackageDiagnostic:
    code: str
    message: str
    path: str = ""


@dataclass(frozen=True)
class PackageManifest:
    package_id: str
    name: str
    version: str
    root: Path
    skills_dir: Path
    bootstrap: str | None = None
    tool_mapping: str | None = None


@dataclass(frozen=True)
class PackageRecord:
    package_id: str
    name: str
    source: str
    scope: str
    version: str
    revision: str
    root: Path
    skills_dir: Path
    status: str = "installed"
    bootstrap: str | None = None
    tool_mapping: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.package_id,
            "name": self.name,
            "source": self.source,
            "scope": self.scope,
            "version": self.version,
            "revision": self.revision,
            "root": str(self.root),
            "skills": str(self.skills_dir),
            "status": self.status,
            "bootstrap": self.bootstrap,
            "toolMapping": self.tool_mapping,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "PackageRecord":
        package_id = str(value.get("id") or "").strip()
        root_text = value.get("root")
        skills_text = value.get("skills")
        if (
            not package_id
            or not isinstance(root_text, str)
            or not root_text.strip()
            or not isinstance(skills_text, str)
            or not skills_text.strip()
        ):
            raise PackageValidationError("Package 注册记录缺少 id、root 或 skills")
        root = Path(root_text).expanduser()
        skills_dir = Path(skills_text).expanduser()
        if not PACKAGE_ID_RE.fullmatch(package_id):
            raise PackageValidationError(f"非法 Package id: {package_id}")
        if not _inside(root.resolve(), skills_dir.resolve()):
            raise PackageValidationError(f"Package Skill 根目录越界: {skills_dir}")
        scope = str(value.get("scope") or "user")
        if scope not in {"user", "project"}:
            raise PackageValidationError(f"非法 Package 作用域: {scope}")
        return cls(
            package_id=package_id,
            name=str(value.get("name") or package_id),
            source=str(value.get("source") or ""),
            scope=scope,
            version=str(value.get("version") or ""),
            revision=str(value.get("revision") or ""),
            root=root,
            skills_dir=skills_dir,
            status=str(value.get("status") or "installed"),
            bootstrap=_optional_string(value.get("bootstrap")),
            tool_mapping=_optional_string(value.get("toolMapping")),
        )


def _optional_string(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _inside(root: Path, candidate: Path) -> bool:
    try:
        candidate.relative_to(root)
        return True
    except ValueError:
        return False


def _validate_package_id(package_id: str) -> str:
    package_id = package_id.strip()
    if not PACKAGE_ID_RE.fullmatch(package_id):
        raise PackageValidationError(f"非法 Package id: {package_id or '(空)'}")
    return package_id


def _validate_package_tree(root: Path) -> None:
    """Reject symlinked package entries before copying or loading content."""
    for current, directories, files in os.walk(root, followlinks=False):
        for name in (*directories, *files):
            candidate = Path(current) / name
            if candidate.is_symlink():
                raise PackageValidationError(f"Package 包含非法链接: {candidate}")


def parse_package_manifest(root: str | Path) -> PackageManifest:
    """Read a package manifest and validate its skill root.

    A missing manifest is supported for Git repositories such as Superpowers;
    the conventional ``skills/`` directory and repository directory name are
    used in that case.
    """

    package_root = Path(root).expanduser().resolve()
    if not package_root.is_dir():
        raise PackageValidationError(f"Package 根目录不存在: {package_root}")

    manifest_path = package_root / PACKAGE_MANIFEST_FILE
    raw: dict[str, Any] = {}
    if manifest_path.exists():
        try:
            loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise PackageValidationError(f"Package 清单解析失败: {manifest_path}") from exc
        if not isinstance(loaded, dict):
            raise PackageValidationError(f"Package 清单必须是 JSON 对象: {manifest_path}")
        raw = loaded

    package_id = _validate_package_id(str(raw.get("id") or package_root.name))
    name = str(raw.get("name") or package_id).strip()
    version = str(raw.get("version") or "").strip()
    skills_value = raw.get("skills") or "skills"
    if not isinstance(skills_value, str) or not skills_value.strip():
        raise PackageValidationError(f"Package Skill 根目录无效: {manifest_path}")
    skills_dir = (package_root / skills_value).resolve()
    if not _inside(package_root, skills_dir) or not skills_dir.is_dir():
        raise PackageValidationError(f"Skill 根目录不存在或越界: {skills_dir}")

    bootstrap = _optional_string(raw.get("bootstrap"))
    tool_mapping = _optional_string(raw.get("toolMapping"))
    if tool_mapping is not None:
        mapping_path = (package_root / tool_mapping).resolve()
        if not _inside(package_root, mapping_path):
            raise PackageValidationError(f"工具映射路径越界: {mapping_path}")
    return PackageManifest(
        package_id=package_id,
        name=name,
        version=version,
        root=package_root,
        skills_dir=skills_dir,
        bootstrap=bootstrap,
        tool_mapping=tool_mapping,
    )


class PackageRegistry:
    """JSON registry wrapper with non-fatal corruption diagnostics."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def load(self) -> tuple[list[dict[str, Any]], list[PackageDiagnostic]]:
        if not self.path.exists():
            return [], []
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return [], [
                PackageDiagnostic("registry_parse_failed", f"Package 注册表解析失败: {self.path}", str(self.path))
            ]
        if not isinstance(raw, list):
            return [], [
                PackageDiagnostic("registry_invalid", f"Package 注册表必须是数组: {self.path}", str(self.path))
            ]
        records: list[dict[str, Any]] = []
        diagnostics: list[PackageDiagnostic] = []
        seen_ids: set[str] = set()
        for index, item in enumerate(raw):
            if not isinstance(item, dict):
                diagnostics.append(PackageDiagnostic("registry_invalid", f"第 {index + 1} 条 Package 记录无效", str(self.path)))
                continue
            try:
                record = PackageRecord.from_dict(item)
            except PackageValidationError as exc:
                diagnostics.append(PackageDiagnostic("registry_invalid", str(exc), str(self.path)))
                continue
            if record.package_id in seen_ids:
                diagnostics.append(
                    PackageDiagnostic(
                        "duplicate_id",
                        f"重复 Package id: {record.package_id}",
                        str(self.path),
                    )
                )
                continue
            seen_ids.add(record.package_id)
            records.append(record.to_dict())
        return records, diagnostics

    def save(self, records: Iterable[PackageRecord | dict[str, Any]]) -> None:
        normalized = [
            item.to_dict() if isinstance(item, PackageRecord) else PackageRecord.from_dict(item).to_dict()
            for item in records
        ]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(normalized, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(self.path)


def _restore_bytes(path: Path, content: bytes | None) -> None:
    """Restore an atomic metadata file snapshot after a failed install."""
    if content is None:
        path.unlink(missing_ok=True)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)


def _remove_path(path: Path) -> None:
    """Remove an exact package path without following a malicious symlink."""
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)


class PackageManager:
    """Install and manage content-only Skill Packages."""

    def __init__(self, config_dir: str | Path, cwd: str | Path) -> None:
        self.config_dir = Path(config_dir).expanduser().resolve()
        self.cwd = Path(cwd).expanduser().resolve()

    def _paths(self, scope: str) -> tuple[Path, Path, Path]:
        if scope not in {"user", "project"}:
            raise ValueError("Package scope 必须是 user 或 project")
        base = self.config_dir if scope == "user" else self.cwd / ".codeagent"
        return base / "packages", base / "registry.json", base / "skills.lock.json"

    def _records(self, scope: str) -> list[PackageRecord]:
        _, registry_path, _ = self._paths(scope)
        raw, _ = PackageRegistry(registry_path).load()
        records: list[PackageRecord] = []
        for item in raw:
            try:
                records.append(PackageRecord.from_dict(item))
            except PackageValidationError:
                continue
        return records

    def list(self, scope: str | None = None) -> list[PackageRecord]:
        scopes = [scope] if scope else ["user", "project"]
        records = [record for selected in scopes for record in self._records(selected)]
        return sorted(records, key=lambda item: (item.scope, item.package_id))

    def diagnostics(self, scope: str | None = None) -> list[PackageDiagnostic]:
        """Return registry diagnostics without preventing valid records from loading."""
        scopes = [scope] if scope else ["user", "project"]
        diagnostics: list[PackageDiagnostic] = []
        for selected in scopes:
            _, registry_path, _ = self._paths(selected)
            _, current = PackageRegistry(registry_path).load()
            diagnostics.extend(current)
        return diagnostics

    def install(self, source: str | Path, *, scope: str = "user") -> PackageRecord:
        store, registry_path, lock_path = self._paths(scope)
        store.mkdir(parents=True, exist_ok=True)
        source_text = str(source)
        is_git = source_text.startswith("git:") or source_text.startswith(
            ("https://", "http://", "ssh://", "git@", "file://")
        )
        source_path: Path | None = None
        if not is_git:
            source_path = Path(source).expanduser().resolve()
            if not source_path.is_dir():
                raise PackageValidationError(f"本地 Package 目录不存在: {source_path}")
            _validate_package_tree(source_path)

        with tempfile.TemporaryDirectory(prefix="codeagent-package-") as temp_name:
            staging_parent = Path(temp_name)
            if is_git:
                git_source_name = source_text[4:] if source_text.startswith("git:") else source_text
                checkout_name = git_source_name.rstrip("/\\").rsplit("/", 1)[-1] or "package"
                checkout_name = Path(checkout_name).name or "package"
                checkout_name = checkout_name.removesuffix(".git") or "package"
            else:
                checkout_name = source_path.name if source_path is not None else "package"
            checkout = staging_parent / checkout_name
            if is_git:
                git_source = source_text[4:] if source_text.startswith("git:") else source_text
                result = subprocess.run(
                    ["git", "clone", "--depth", "1", git_source, str(checkout)],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if result.returncode != 0:
                    raise PackageValidationError(f"Git Package 下载失败: {result.stderr.strip() or git_source}")
            else:
                shutil.copytree(source_path, checkout)

            _validate_package_tree(checkout)
            manifest = parse_package_manifest(checkout)
            revision = ""
            if (checkout / ".git").is_dir():
                result = subprocess.run(
                    ["git", "-C", str(checkout), "rev-parse", "HEAD"],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if result.returncode == 0:
                    revision = result.stdout.strip()

            target = (store / manifest.package_id).resolve()
            if not _inside(store.resolve(), target):
                raise PackageValidationError(f"Package 安装路径越界: {target}")
            old_registry = registry_path.read_bytes() if registry_path.exists() else None
            old_lock = lock_path.read_bytes() if lock_path.exists() else None
            backup = staging_parent / "previous"
            had_target = target.exists()
            try:
                if had_target:
                    shutil.move(str(target), str(backup))
                shutil.move(str(checkout), str(target))
                installed_manifest = parse_package_manifest(target)
                record = PackageRecord(
                    package_id=installed_manifest.package_id,
                    name=installed_manifest.name,
                    source=(source_text if is_git else f"local:{source_path}"),
                    scope=scope,
                    version=installed_manifest.version,
                    revision=revision,
                    root=target,
                    skills_dir=installed_manifest.skills_dir,
                    bootstrap=installed_manifest.bootstrap,
                    tool_mapping=installed_manifest.tool_mapping,
                )
                records = [item for item in self._records(scope) if item.package_id != record.package_id]
                records.append(record)
                PackageRegistry(registry_path).save(records)
                PackageRegistry(lock_path).save(records)
            except BaseException:
                if target.exists():
                    _remove_path(target)
                if backup.exists():
                    shutil.move(str(backup), str(target))
                _restore_bytes(registry_path, old_registry)
                _restore_bytes(lock_path, old_lock)
                raise
            return record

    def update(self, package_id: str, *, scope: str = "user") -> PackageRecord:
        current = next((item for item in self._records(scope) if item.package_id == package_id), None)
        if current is None:
            raise KeyError(f"Package 不存在: {package_id}")
        source = current.source[6:] if current.source.startswith("local:") else current.source
        return self.install(source, scope=scope)

    def remove(self, package_id: str, *, scope: str = "user") -> None:
        store, registry_path, lock_path = self._paths(scope)
        records = self._records(scope)
        current = next((item for item in records if item.package_id == package_id), None)
        if current is None:
            raise KeyError(f"Package 不存在: {package_id}")
        target = current.root.resolve()
        remaining = [item for item in records if item.package_id != package_id]
        if not _inside(store.resolve(), target):
            raise PackageValidationError(f"Package 安装路径越界: {target}")
        old_registry = registry_path.read_bytes() if registry_path.exists() else None
        old_lock = lock_path.read_bytes() if lock_path.exists() else None
        backup = store.parent / f".{package_id}.remove-backup"
        try:
            if target.exists():
                if backup.exists():
                    _remove_path(backup)
                shutil.move(str(target), str(backup))
            PackageRegistry(registry_path).save(remaining)
            PackageRegistry(lock_path).save(remaining)
        except BaseException:
            if backup.exists() and not target.exists():
                shutil.move(str(backup), str(target))
            _restore_bytes(registry_path, old_registry)
            _restore_bytes(lock_path, old_lock)
            raise
        if backup.exists():
            _remove_path(backup)

    def reload(self) -> list[PackageRecord]:
        """Return the current records; callers rebuild their Skill Registry."""

        return self.list()
