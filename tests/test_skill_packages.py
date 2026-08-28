"""Skill Package 数据模型、注册表和安装生命周期测试。"""

import json
import subprocess
from pathlib import Path

import pytest

from codeagent.app.skill_packages import (
    PackageManager,
    PackageRegistry,
    PackageValidationError,
    parse_package_manifest,
)


def _write_package(root: Path, *, package_id: str = "demo", with_manifest: bool = True) -> Path:
    (root / "skills" / "fmt").mkdir(parents=True)
    (root / "skills" / "fmt" / "SKILL.md").write_text(
        "---\nname: fmt\ndescription: 格式化\n---\n正文", encoding="utf-8"
    )
    if with_manifest:
        (root / "codeagent-package.json").write_text(
            json.dumps(
                {
                    "id": package_id,
                    "name": "Demo Package",
                    "version": "1.2.3",
                    "skills": "skills",
                    "bootstrap": "using-superpowers",
                    "toolMapping": "references/codeagent-tools.md",
                }
            ),
            encoding="utf-8",
        )
    return root


def test_parse_package_manifest_reads_metadata_and_defaults(tmp_path):
    root = _write_package(tmp_path / "pkg")

    manifest = parse_package_manifest(root)

    assert manifest.package_id == "demo"
    assert manifest.name == "Demo Package"
    assert manifest.version == "1.2.3"
    assert manifest.skills_dir == (root / "skills").resolve()
    assert manifest.bootstrap == "using-superpowers"


def test_parse_package_manifest_rejects_missing_skill_root(tmp_path):
    root = tmp_path / "pkg"
    root.mkdir()
    (root / "codeagent-package.json").write_text(
        json.dumps({"id": "broken", "skills": "missing"}), encoding="utf-8"
    )

    with pytest.raises(PackageValidationError, match="Skill 根目录"):
        parse_package_manifest(root)


def test_package_registry_roundtrip_and_corrupt_diagnostic(tmp_path):
    registry_path = tmp_path / "registry.json"
    registry = PackageRegistry(registry_path)
    package = {
        "id": "demo",
        "name": "Demo",
        "source": "local:/demo",
        "scope": "user",
        "version": "1.0.0",
        "revision": "abc",
        "root": str(tmp_path / "pkg"),
        "skills": str(tmp_path / "pkg" / "skills"),
    }
    registry.save([package])

    loaded, diagnostics = registry.load()
    assert diagnostics == []
    assert loaded[0]["id"] == "demo"

    registry_path.write_text("{broken", encoding="utf-8")
    loaded, diagnostics = registry.load()
    assert loaded == []
    assert diagnostics and diagnostics[0].code == "registry_parse_failed"


def test_package_manager_installs_local_package_and_persists_lock(tmp_path):
    source = _write_package(tmp_path / "source")
    config_dir = tmp_path / "home"
    cwd = tmp_path / "project"

    manager = PackageManager(config_dir=config_dir, cwd=cwd)
    record = manager.install(source, scope="user")

    assert record.package_id == "demo"
    assert record.scope == "user"
    assert record.skills_dir.is_dir()
    assert (config_dir / "packages" / "demo").is_dir()
    assert (config_dir / "registry.json").exists()
    assert (config_dir / "skills.lock.json").exists()
    assert manager.list(scope="user")[0].package_id == "demo"


def test_package_manager_failed_install_keeps_existing_registry(tmp_path):
    source = _write_package(tmp_path / "source")
    config_dir = tmp_path / "home"
    manager = PackageManager(config_dir=config_dir, cwd=tmp_path / "project")
    manager.install(source, scope="user")

    broken = tmp_path / "broken"
    broken.mkdir()
    with pytest.raises(PackageValidationError):
        manager.install(broken, scope="user")

    assert [item.package_id for item in manager.list(scope="user")] == ["demo"]


def test_package_manager_remove_unknown_is_explicit(tmp_path):
    manager = PackageManager(config_dir=tmp_path / "home", cwd=tmp_path / "project")

    with pytest.raises(KeyError, match="unknown"):
        manager.remove("unknown", scope="user")


def test_registry_reports_duplicate_package_ids(tmp_path):
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(
        json.dumps([
            {"id": "same", "root": str(tmp_path / "a"), "skills": str(tmp_path / "a" / "skills")},
            {"id": "same", "root": str(tmp_path / "b"), "skills": str(tmp_path / "b" / "skills")},
        ]),
        encoding="utf-8",
    )

    loaded, diagnostics = PackageRegistry(registry_path).load()

    assert [item["id"] for item in loaded] == ["same"]
    assert any(item.code == "duplicate_id" for item in diagnostics)


def test_package_manager_rejects_symlinked_package_entries(tmp_path):
    source = _write_package(tmp_path / "source")
    outside = tmp_path / "outside.txt"
    outside.write_text("not a skill", encoding="utf-8")
    link = source / "skills" / "escape.md"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("当前环境不支持创建符号链接")

    with pytest.raises(PackageValidationError, match="链接"):
        PackageManager(tmp_path / "home", tmp_path / "project").install(source)


def test_package_manager_git_source_records_revision_and_repository_name(tmp_path):
    source = tmp_path / "git-superpowers"
    (source / "skills" / "using-superpowers").mkdir(parents=True)
    (source / "skills" / "using-superpowers" / "SKILL.md").write_text(
        "---\ndescription: bootstrap\n---\n正文", encoding="utf-8"
    )
    subprocess.run(["git", "init", str(source)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(source), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(source), "config", "user.name", "Test"], check=True)
    subprocess.run(["git", "-C", str(source), "add", "."], check=True)
    subprocess.run(["git", "-C", str(source), "commit", "-m", "initial"], check=True, capture_output=True)
    expected_revision = subprocess.run(
        ["git", "-C", str(source), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    record = PackageManager(tmp_path / "home", tmp_path / "project").install(
        f"git:{source}", scope="user"
    )

    assert record.package_id == "git-superpowers"
    assert record.revision == expected_revision


def test_package_manager_git_source_has_a_bounded_download(monkeypatch, tmp_path):
    def timeout(*args, **kwargs):
        assert kwargs["timeout"] == 120
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])

    monkeypatch.setattr(subprocess, "run", timeout)

    with pytest.raises(PackageValidationError, match="下载超时"):
        PackageManager(tmp_path / "home", tmp_path / "project").install(
            "https://example.invalid/package.git"
        )
