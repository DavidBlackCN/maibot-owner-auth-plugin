from pathlib import Path
import hashlib
import json
import os
import shutil
import importlib.metadata
import sys

ROOT = Path(__file__).resolve().parents[1]
HOST = ROOT/".integration/host"
PLUGIN_ID = "davidblackcn.maibot-maiidentity-plugin"
CONSUMER = "maiidentity.test.consumer"


def verify_source():
    lock = json.loads((ROOT/"tests/fixtures/source-lock.json").read_text(encoding="utf-8"))
    for relative, expected in lock["host_files"].items():
        path = HOST/relative
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError("Host fixture changed: "+relative)
    import maibot_sdk
    assert importlib.metadata.version("maibot-plugin-sdk") == lock["sdk_version"]
    installed = Path(maibot_sdk.__file__).parent.parent
    for relative, expected in lock["sdk_files"].items():
        assert hashlib.sha256((installed/relative).read_bytes()).hexdigest() == expected, "SDK fixture changed: "+relative
    return lock


def run_process(command, *, work, timeout=65):
    """Own the child tree and terminate it on a failed/expired smoke run."""
    import subprocess
    process = subprocess.Popen(command, cwd=work, env=environment(work), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    try:
        stdout, stderr = process.communicate(timeout=timeout)
        return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
    except BaseException:
        if process.poll() is None:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True)
            else:
                process.kill()
            process.wait()
        raise


def environment(work, **extra):
    env = {k: v for k, v in os.environ.items() if k.upper() in ("SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "NUMBER_OF_PROCESSORS")}
    env.update(PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1", PYTHONUNBUFFERED="1", PYTHONPATH=os.pathsep.join((str(ROOT), str(HOST))),
               MAIBOT_INSTANCE_DIR=str(work), TEMP=str(work), TMP=str(work), USERPROFILE=str(work))
    env.update(extra)
    return env


def stage(work, *, consumer=True):
    import tomli_w
    plugin = work/"plugins/candidate"
    plugin.mkdir(parents=True)
    for name in ("plugin.py", "_manifest.json"):
        shutil.copyfile(ROOT/name, plugin/name)
    shutil.copytree(ROOT/"maiidentity", plugin/"maiidentity", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    cfg = {"plugin": {"enabled": True, "config_version": "4"},
           "identity": {"adapter_namespace": "adapter", "route_scope": "route",
                        "people": [{"qq":"10001", "nickname":"妈妈", "prompt_template":"自然亲近"}]},
           "management": {"admin_accounts": ["10001"]}}
    (plugin/"config.toml").write_text(tomli_w.dumps(cfg), encoding="utf-8")
    if consumer:
        directory = work/"plugins/consumer"
        directory.mkdir()
        manifest = json.loads((ROOT/"_manifest.json").read_text(encoding="utf-8"))
        manifest.update(id=CONSUMER, name="Synthetic MaiIdentity consumer", capabilities=["api.call"])
        (directory/"_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        shutil.copyfile(ROOT/"integration_tests/consumer.py", directory/"plugin.py")
    return plugin


def raw_message(account="10001", mid="message-A", stream="test-stream", name="ordinary"):
    return {"platform": "qq", "account_id": "99999", "scope": "route", "session_id": stream, "message_id": mid, "message_info": {"user_info": {
        "user_id": account, "user_nickname": name}, "group_info": None}}


def projection(text):
    return text.split("[MaiIdentity context v1]\n")[-1].split("\n", 1)[1].rsplit("\n[/MaiIdentity context v1]", 1)[0]
