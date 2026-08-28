"""Skill Package 清单、注册记录和 JSON Registry。"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

PACKAGE_MANIFEST_FILE = "codeagent-package.json"
PACKAGE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
PACKAGE_GIT_TIMEOUT_S = 120


class PackageValidationError(ValueError):
    """Package 无法安全加载或安装。"""


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
        root_text, skills_text = value.get("root"), value.get("skills")
        if not package_id or not isinstance(root_text, str) or not root_text.strip() or not isinstance(skills_text, str) or not skills_text.strip():
            raise PackageValidationError("Package 注册记录缺少 id、root 或 skills")
        root, skills_dir = Path(root_text).expanduser(), Path(skills_text).expanduser()
        if not PACKAGE_ID_RE.fullmatch(package_id):
            raise PackageValidationError(f"非法 Package id: {package_id}")
        if not inside(root.resolve(), skills_dir.resolve()):
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
            bootstrap=optional_string(value.get("bootstrap")),
            tool_mapping=optional_string(value.get("toolMapping")),
        )


def optional_string(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def inside(root: Path, candidate: Path) -> bool:
    try:
        candidate.relative_to(root)
        return True
    except ValueError:
        return False


def validate_package_id(package_id: str) -> str:
    package_id = package_id.strip()
    if not PACKAGE_ID_RE.fullmatch(package_id):
        raise PackageValidationError(f"非法 Package id: {package_id or '(空)'}")
    return package_id


def validate_package_tree(root: Path) -> None:
    for current, directories, file_names in os.walk(root, followlinks=False):
        for name in (*directories, *file_names):
            candidate = Path(current) / name
            if candidate.is_symlink():
                raise PackageValidationError(f"Package 包含非法链接: {candidate}")


def parse_package_manifest(root: str | Path) -> PackageManifest:
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
    package_id = validate_package_id(str(raw.get("id") or package_root.name))
    name = str(raw.get("name") or package_id).strip()
    version = str(raw.get("version") or "").strip()
    skills_value = raw.get("skills") or "skills"
    if not isinstance(skills_value, str) or not skills_value.strip():
        raise PackageValidationError(f"Package Skill 根目录无效: {manifest_path}")
    skills_dir = (package_root / skills_value).resolve()
    if not inside(package_root, skills_dir) or not skills_dir.is_dir():
        raise PackageValidationError(f"Skill 根目录不存在或越界: {skills_dir}")
    bootstrap, tool_mapping = optional_string(raw.get("bootstrap")), optional_string(raw.get("toolMapping"))
    if tool_mapping is not None and not inside(package_root, (package_root / tool_mapping).resolve()):
        raise PackageValidationError(f"工具映射路径越界: {(package_root / tool_mapping).resolve()}")
    return PackageManifest(package_id, name, version, package_root, skills_dir, bootstrap, tool_mapping)


class PackageRegistry:
    """带非致命损坏诊断的 JSON registry。"""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def load(self) -> tuple[list[dict[str, Any]], list[PackageDiagnostic]]:
        if not self.path.exists():
            return [], []
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return [], [PackageDiagnostic("registry_parse_failed", f"Package 注册表解析失败: {self.path}", str(self.path))]
        if not isinstance(raw, list):
            return [], [PackageDiagnostic("registry_invalid", f"Package 注册表必须是数组: {self.path}", str(self.path))]
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
                diagnostics.append(PackageDiagnostic("duplicate_id", f"重复 Package id: {record.package_id}", str(self.path)))
                continue
            seen_ids.add(record.package_id)
            records.append(record.to_dict())
        return records, diagnostics

    def save(self, records: Iterable[PackageRecord | dict[str, Any]]) -> None:
        normalized = [item.to_dict() if isinstance(item, PackageRecord) else PackageRecord.from_dict(item).to_dict() for item in records]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(normalized, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(self.path)
