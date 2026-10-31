#!/bin/sh
# Run as root, only for a new installation from a reviewed staging directory.
set -eu
staging="$1"
test ! -e /opt/obr-math
test ! -e /etc/obr-math
test ! -e /etc/systemd/system/obr-math.service
if ! id obr-math >/dev/null 2>&1; then
    useradd --system --home-dir /var/lib/obr-math --shell /usr/sbin/nologin obr-math
fi
install -d -m 0755 /opt/obr-math
cp -R "$staging/app" "$staging/tests" "$staging/pyproject.toml" /opt/obr-math/
python3 -m venv /opt/obr-math/.venv
/opt/obr-math/.venv/bin/python -m pip install '/opt/obr-math[test]'
cd /opt/obr-math
/opt/obr-math/.venv/bin/python -m pytest -q
/opt/obr-math/.venv/bin/python -m pip freeze > requirements.deployed.txt
install -d -m 0750 -o root -g obr-math /etc/obr-math
install -d -m 0700 -o obr-math -g obr-math /var/lib/obr-math
python3 - <<'PY'
import os, secrets
path = '/etc/obr-math/obr.env'
fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, 'w') as f:
    f.write('PAPER_MODE=true\nLIVE_TRADING_ENABLED=false\nOBR_API_TOKEN=' + secrets.token_urlsafe(48) + '\n')
PY
install -m 0644 "$staging/scripts/obr-math.service" /etc/systemd/system/obr-math.service
systemctl daemon-reload
systemctl enable --now obr-math.service
systemctl is-active obr-math.service
