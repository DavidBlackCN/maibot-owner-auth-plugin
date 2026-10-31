"""Publish a minimal verification summary only when all current gates agree."""
from pathlib import Path
import hashlib
import json
import sys
from datetime import datetime, timezone, timedelta

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.workspace_paths import EVIDENCE
from tools.package import fingerprint


if __name__ == "__main__":
    reports = {name: json.loads((EVIDENCE/(name+".json")).read_text(encoding="utf-8"))
               for name in ("unit", "runner", "host")}
    candidate = fingerprint()
    assert all(report["passed"] is True for report in reports.values())
    assert all(reports[name]["candidate_files"] == candidate for name in ("unit", "runner", "host"))
    lock = json.loads((ROOT/"tests/fixtures/source-lock.json").read_text(encoding="utf-8"))
    version = json.loads((ROOT/"_manifest.json").read_text(encoding="utf-8"))["version"]
    report = {"date": datetime.now(timezone(timedelta(hours=8))).date().isoformat(), "timezone": "Asia/Shanghai", "plugin_version": version, "config_version": "4",
              "db_schema": 1, "api_major": "1", "production_approved": False, "host_commit": lock["host_commit"],
              "sdk_version": "2.15.0", "maivita_reference_commit": lock["maivita_commit"],
              "maivita_reference_scope": "historical contract reference only; not a joint runtime acceptance", "candidate_files": candidate,
              "T0": {k: reports["unit"][k] for k in ("tests", "failures", "skipped", "python", "command", "passed")},
              "T1": {k: reports["runner"][k] for k in ("cases", "business_ports", "command", "passed")},
              "T2": {k: reports["host"][k] for k in ("cases", "scope", "full_bot_cli", "module_replacements", "command", "passed")},
              "platform_sends": 0, "model_requests": 0,
              "permission_source": "operator_admin_config",
              "local_command_adapter":"official Host command entry; full joint cases recorded separately",
              "not_executed": ["full_bot_cli_WebUI", "real_platform", "paid_model", "MaiVita_policy_joint_acceptance", "long_term_observation"],
              "validation_files": {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for directory in ("tools", "tests", "integration_tests") for p in (ROOT/directory).rglob("*.py")}}
    target = EVIDENCE/'acceptance.json'
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8", newline="\n")
    print(json.dumps({"T0": report["T0"]["tests"], "T1": len(report["T1"]["cases"]), "T2": len(report["T2"]["cases"]), "matching_runtime_files": len(candidate)}, indent=2))
