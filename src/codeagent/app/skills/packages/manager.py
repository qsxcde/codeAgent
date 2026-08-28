"""Skill Package 安装、更新、删除和作用域查询。"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from .registry import (
    PACKAGE_GIT_TIMEOUT_S,
    PackageDiagnostic,
    PackageRecord,
    PackageRegistry,
    PackageValidationError,
    parse_package_manifest,
    inside,
    validate_package_tree,
)


def _restore_bytes(path: Path, content: bytes | None) -> None:
    if content is None:
        path.unlink(missing_ok=True)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)


def _remove_path(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)


class PackageManager:
    """安装和管理只包含内容的 Skill Package。"""

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
        with tempfile.TemporaryDirectory(prefix="codeagent-package-") as temp_name:
            checkout = self._stage_source(str(source), Path(temp_name))
            return self._commit_install(checkout, str(source), scope, store, registry_path, lock_path)

    def _stage_source(self, source_text: str, staging_parent: Path) -> Path:
        is_git = source_text.startswith("git:") or source_text.startswith(
            ("https://", "http://", "ssh://", "git@", "file://")
        )
        if not is_git:
            source = Path(source_text).expanduser().resolve()
            if not source.is_dir():
                raise PackageValidationError(f"本地 Package 目录不存在: {source}")
            validate_package_tree(source)
            checkout = staging_parent / source.name
            shutil.copytree(source, checkout)
            return checkout
        git_source = source_text[4:] if source_text.startswith("git:") else source_text
        checkout_name = git_source.rstrip("/\\").rsplit("/", 1)[-1] or "package"
        checkout_name = Path(checkout_name).name.removesuffix(".git") or "package"
        checkout = staging_parent / checkout_name
        try:
            result = subprocess.run(
                ["git", "clone", "--depth", "1", git_source, str(checkout)],
                capture_output=True,
                text=True,
                check=False,
                timeout=PACKAGE_GIT_TIMEOUT_S,
            )
        except subprocess.TimeoutExpired as exc:
            raise PackageValidationError(
                f"Git Package 下载超时({PACKAGE_GIT_TIMEOUT_S}s): {git_source}"
            ) from exc
        if result.returncode != 0:
            raise PackageValidationError(f"Git Package 下载失败: {result.stderr.strip() or git_source}")
        return checkout

    def _commit_install(
        self,
        checkout: Path,
        source_text: str,
        scope: str,
        store: Path,
        registry_path: Path,
        lock_path: Path,
    ) -> PackageRecord:
        validate_package_tree(checkout)
        manifest = parse_package_manifest(checkout)
        revision = self._revision(checkout)
        target = (store / manifest.package_id).resolve()
        if not inside(store.resolve(), target):
            raise PackageValidationError(f"Package 安装路径越界: {target}")
        old_registry = registry_path.read_bytes() if registry_path.exists() else None
        old_lock = lock_path.read_bytes() if lock_path.exists() else None
        backup = checkout.parent / "previous"
        try:
            if target.exists():
                shutil.move(str(target), str(backup))
            shutil.move(str(checkout), str(target))
            installed = parse_package_manifest(target)
            record = PackageRecord(
                installed.package_id,
                installed.name,
                source_text if source_text.startswith(("git:", "https://", "http://", "ssh://", "git@", "file://")) else f"local:{Path(source_text).expanduser().resolve()}",
                scope,
                installed.version,
                revision,
                target,
                installed.skills_dir,
                bootstrap=installed.bootstrap,
                tool_mapping=installed.tool_mapping,
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

    @staticmethod
    def _revision(checkout: Path) -> str:
        if not (checkout / ".git").is_dir():
            return ""
        result = subprocess.run(
            ["git", "-C", str(checkout), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        return result.stdout.strip() if result.returncode == 0 else ""

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
        if not inside(store.resolve(), target):
            raise PackageValidationError(f"Package 安装路径越界: {target}")
        old_registry = registry_path.read_bytes() if registry_path.exists() else None
        old_lock = lock_path.read_bytes() if lock_path.exists() else None
        backup = store.parent / f".{package_id}.remove-backup"
        try:
            if target.exists():
                if backup.exists():
                    _remove_path(backup)
                shutil.move(str(target), str(backup))
            remaining = [item for item in records if item.package_id != package_id]
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
        return self.list()
