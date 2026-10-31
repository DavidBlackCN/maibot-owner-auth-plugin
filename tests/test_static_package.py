from pathlib import Path
import ast
import hashlib
import json

from maiidentity import API_MAJOR, CONFIG_VERSION, DB_SCHEMA, PLUGIN_ID, PLUGIN_VERSION

ROOT = Path(__file__).resolve().parents[1]


def test_versions_minimal_capabilities_single_entry_license_and_domain_boundaries():
    manifest = json.loads((ROOT/"_manifest.json").read_text(encoding="utf-8"))
    assert manifest["id"] == PLUGIN_ID and manifest["version"] == PLUGIN_VERSION == "3.4.0"
    assert (CONFIG_VERSION, DB_SCHEMA, API_MAJOR) == ("4", 1, "1")
    assert set(manifest["capabilities"]) == {"message.get_by_id", "chat.get_all_streams", "component.list_loaded_plugins", "send.text"}
    # Git and Windows checkouts may use different line endings for the same license.
    license_bytes = (ROOT/"LICENSE").read_bytes().replace(b"\r\n", b"\n")
    assert hashlib.sha256(license_bytes).hexdigest() == "3972dc9744f6499f0f9b2dbf76696f2ae7ad8af9b23dde66d6af86c9dfb36986"
    assert "风花叶" in (ROOT/"plugin.py").read_text(encoding="utf-8")
    for path in (ROOT/"maiidentity").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        assert not any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "create_plugin" for n in ast.walk(tree))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.startswith("src"), path
                if "host" not in path.relative_to(ROOT/"maiidentity").parts:
                    assert not node.module.startswith("maibot_sdk"), path


def test_package_allowlist_excludes_internal_documents_data_and_tests():
    from tools.package import files
    names = [p.relative_to(ROOT).as_posix() for p in files()]
    assert not any(n.startswith(("tests/", "integration_tests/", ".integration/", "evidence/")) for n in names)
    assert not any(n.endswith((".db", ".log", "CODEX_PROMPT.md", "MAIIDENTITY_ARCHITECTURE.md", "IDENTITY_POLICY_SPEC.md", "RELATION_INTEGRITY_SPEC.md", "CODEX_IMPLEMENTATION_PLAN.md")) for n in names)
    assert "config.toml" not in names


def test_package_refuses_stale_acceptance(monkeypatch):
    import pytest
    from tools import package
    # Force a different candidate without trusting the checked-in report.
    monkeypatch.setattr(package, 'fingerprint', lambda: {'changed.py': 'different'})
    with pytest.raises(AssertionError, match='stale acceptance'):
        package.verify_acceptance()
