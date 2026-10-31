"""Publish verified fee observations using the dedicated local SSH key."""
import json
from pathlib import Path
import shlex
import sys
import time
import paramiko

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.fee_watch import validate

observation=json.loads(Path("data/fee-observation.json").read_text(encoding="utf-8"))
validate(observation,time.time_ns()//1000000)
client=paramiko.SSHClient()
client.load_system_host_keys()
client.load_host_keys(str(Path(__file__).resolve().parent.parent/"var/ssh_known_hosts"))
client.set_missing_host_key_policy(paramiko.RejectPolicy())
client.connect("43.163.203.127",username="ubuntu",key_filename=str(Path.home()/".ssh/obr_math_ed25519"),look_for_keys=False,allow_agent=False,timeout=20)
code='''import json,sys,time
from pathlib import Path
unit=Path('/etc/systemd/system/obr-math.service').read_text()
release=next(x.split('=',1)[1] for x in unit.splitlines() if x.startswith('WorkingDirectory='))
sys.path.insert(0,release)
from app.fee_watch import update
state,changed=update(Path('/var/lib/obr-math/fee-watch.json'),json.load(sys.stdin),time.time_ns()//1000000)
print(json.dumps({'changed':changed,'checked_ms':state['observation']['checked_ms']}))
'''
try:
    stdin,stdout,stderr=client.exec_command("sudo -u obr-math /opt/obr-math/.venv/bin/python -c "+shlex.quote(code))
    stdin.write(json.dumps(observation));stdin.channel.shutdown_write()
    output=stdout.read().decode()
    if stdout.channel.recv_exit_status()!=0:
        raise RuntimeError("FEE_PUBLISH_FAILED")
    print(output)
finally:
    client.close()
