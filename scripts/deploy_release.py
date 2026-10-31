"""Run as root on the authorized VPS. API Key enters via stdin, never arguments."""
import json
import os
from pathlib import Path
import re
import shutil
import secrets
import subprocess
import sys
import time
import urllib.request


def private_write(path, content):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w") as output:
        output.write(content)


def main():
    staging, version = Path(sys.argv[1]).resolve(), sys.argv[2]
    if not re.fullmatch(r"v[0-9]+-[0-9TZ-]+", version):
        raise ValueError("INVALID_RELEASE_NAME")
    credential = json.load(sys.stdin)
    key = credential["api_key"]
    if not isinstance(key, str) or not key.isascii() or not key.isalnum():
        raise ValueError("INVALID_API_KEY_FORMAT")
    release = Path("/opt/obr-math/releases")/version
    release.mkdir(parents=True, exist_ok=False)
    for folder in ("app", "tests", "data", "scripts"):
        shutil.copytree(staging/folder, release/folder, ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy2(staging/"pyproject.toml", release/"pyproject.toml")
    # Code is readable by the service account regardless of the caller's umask.
    release.chmod(0o755)
    for path in release.rglob("*"):
        path.chmod(0o755 if path.is_dir() else 0o644)
    python = "/opt/obr-math/.venv/bin/python"
    subprocess.run([python,"-m","pytest","-q"],cwd=release,check=True)
    unit = Path("/etc/systemd/system/obr-math.service")
    env = Path("/etc/obr-math/obr.env")
    old_unit, old_env = unit.read_text(), env.read_text()
    private_write(Path("/etc/obr-math")/f"{version}.previous.env",old_env)
    (Path("/etc/obr-math")/f"{version}.previous.service").write_text(old_unit)
    values = dict(line.split("=",1) for line in old_env.splitlines() if "=" in line and not line.startswith("#"))
    if len(values.get("OBR_CONTROL_TOKEN",""))<32 or values.get("OBR_CONTROL_TOKEN")==values.get("OBR_API_TOKEN"):
        values["OBR_CONTROL_TOKEN"]=secrets.token_urlsafe(48)
    values.update(PAPER_MODE="true",LIVE_TRADING_ENABLED="false",OBR_RUNTIME_ENABLED="true",
                  OBR_LIVE_CONTROL_ENABLED="true",
                  OBR_DATA_DIR="/var/lib/obr-math",OBR_FOCUS_LIMIT="9",
                  OBR_UNIVERSE_FILE=str(release/"data/universe.json"),OBR_CALENDAR_FILE=str(release/"data/calendar.json"))
    private_write(env,"".join(f"{k}={v}\n" for k,v in values.items()))
    private_write(Path("/etc/obr-math/binance.env"),"BINANCE_API_KEY="+key+"\n")
    template = (staging/"scripts/obr-math.service").read_text()
    template = template.replace("WorkingDirectory=/opt/obr-math", "WorkingDirectory="+str(release))
    template = template.replace("EnvironmentFile=/etc/obr-math/obr.env", "EnvironmentFile=/etc/obr-math/obr.env\nEnvironmentFile=/etc/obr-math/binance.env")
    try:
        unit.write_text(template)
        subprocess.run(["systemctl","daemon-reload"],check=True)
        subprocess.run(["systemctl","restart","obr-math"],check=True)
        for attempt in range(20):
            try:
                request = urllib.request.Request("http://127.0.0.1:8765/api/v1/status",
                                                 headers={"Authorization":"Bearer "+values["OBR_API_TOKEN"]})
                with urllib.request.urlopen(request,timeout=2) as response:
                    status = json.load(response)
                if status.get("version") in {"0.5.0", "0.6.0", "0.7.0", "0.8.0", "0.9.0", "1.0.0"} and status.get("paper_mode") is True and status.get("live_trading_enabled") is False:
                    print(json.dumps({"release":str(release),"status":status}))
                    return
            except Exception:
                pass
            time.sleep(1)
        raise RuntimeError("NEW_RELEASE_HEALTH_CHECK_FAILED")
    except Exception:
        unit.write_text(old_unit)
        private_write(env,old_env)
        subprocess.run(["systemctl","daemon-reload"],check=True)
        subprocess.run(["systemctl","restart","obr-math"],check=True)
        raise


if __name__ == "__main__":
    main()
