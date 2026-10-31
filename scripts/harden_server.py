"""Root-only security baseline for the authorized OBR host. No secrets in source."""
from pathlib import Path
import subprocess, shutil, datetime, os, sqlite3

def run(*args):
    subprocess.run(args,check=True)
def write(path,text,mode=0o644):
    p=Path(path);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text);p.chmod(mode)

stamp=datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
backup=Path("/root/obr-security-"+stamp);backup.mkdir(mode=0o700)
for src in ("/etc/ssh","/etc/nginx","/etc/ufw","/etc/obr-math","/etc/systemd/system/obr-math.service"):
    p=Path(src);target=backup/p.name
    if p.is_dir():shutil.copytree(p,target,symlinks=True)
    else:shutil.copy2(p,target)
with sqlite3.connect("/var/lib/obr-math/obr.db") as source,sqlite3.connect(backup/"obr.db") as dest:source.backup(dest)
(backup/"obr.db").chmod(0o600)
# Temporary recovery is armed before touching access controls.
rollback=backup/"rollback-access.sh"
rollback.write_text("#!/bin/sh\nrm -f /etc/ssh/sshd_config.d/00-obr-hardening.conf\n/usr/sbin/sshd -t && /usr/bin/systemctl reload ssh\n/usr/sbin/ufw --force disable\n")
rollback.chmod(0o700)
run("systemd-run","--unit=obr-security-rollback","--on-active=10m",str(rollback))
write("/etc/ssh/sshd_config.d/00-obr-hardening.conf", """PermitRootLogin no
PasswordAuthentication no
KbdInteractiveAuthentication no
PubkeyAuthentication yes
AuthenticationMethods publickey
PermitEmptyPasswords no
AllowUsers ubuntu
MaxAuthTries 3
MaxSessions 4
MaxStartups 10:30:30
LoginGraceTime 30
ClientAliveInterval 120
ClientAliveCountMax 2
X11Forwarding no
AllowAgentForwarding no
AllowTcpForwarding no
PermitTunnel no
PermitUserEnvironment no
LogLevel VERBOSE
""")
run("sshd","-t")
run("systemctl","reload","ssh")
run("ufw","default","deny","incoming")
run("ufw","default","allow","outgoing")
for port in ("22/tcp","80/tcp","443/tcp"):run("ufw","allow",port)
run("ufw","logging","low")
run("ufw","--force","enable")
write("/etc/fail2ban/filter.d/obr-api.conf",r"""[Definition]
failregex = ^<HOST> - \[.*\] "(?:GET|HEAD) /api/v1/[^"]*" 401\b
ignoreregex =
""")
write("/etc/fail2ban/jail.d/obr-hardening.local","""[DEFAULT]
bantime = 1h
findtime = 10m
maxretry = 5
banaction = ufw
ignoreip = 127.0.0.1/8 ::1
[sshd]
enabled = true
backend = systemd
[obr-api]
enabled = true
backend = auto
port = 443
filter = obr-api
logpath = /var/log/nginx/obr-access.log
maxretry = 12
""")
# Keep all security-origin updates automatic; reboot is deliberately controlled.
write("/etc/apt/apt.conf.d/20auto-upgrades",'APT::Periodic::Update-Package-Lists "1";\nAPT::Periodic::Unattended-Upgrade "1";\n')
write("/etc/apt/apt.conf.d/52obr-security",'Unattended-Upgrade::Allowed-Origins { "${distro_id}:${distro_codename}-security"; "${distro_id}ESMApps:${distro_codename}-apps-security"; "${distro_id}ESM:${distro_codename}-infra-security"; };\nUnattended-Upgrade::Automatic-Reboot "false";\n')
write("/etc/sysctl.d/60-obr-security.conf","""kernel.kptr_restrict=2
kernel.dmesg_restrict=1
kernel.yama.ptrace_scope=1
kernel.unprivileged_bpf_disabled=1
net.ipv4.conf.all.accept_redirects=0
net.ipv4.conf.default.accept_redirects=0
net.ipv4.conf.all.send_redirects=0
net.ipv4.conf.default.send_redirects=0
net.ipv4.conf.all.accept_source_route=0
net.ipv4.conf.default.accept_source_route=0
net.ipv4.tcp_syncookies=1
net.ipv6.conf.all.accept_redirects=0
net.ipv6.conf.default.accept_redirects=0
""")
run("sysctl","-p","/etc/sysctl.d/60-obr-security.conf")
write("/etc/systemd/system/obr-math.service.d/security.conf","""[Service]
CapabilityBoundingSet=
AmbientCapabilities=
PrivateDevices=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectKernelLogs=true
ProtectControlGroups=true
RestrictSUIDSGID=true
RestrictRealtime=true
LockPersonality=true
RestrictNamespaces=true
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
ProtectClock=true
SystemCallArchitectures=native
""")
write("/etc/systemd/journald.conf.d/obr-retention.conf","""[Journal]
Storage=persistent
SystemMaxUse=200M
MaxRetentionSec=30day
""")
write("/etc/audit/rules.d/obr-security.rules","""-w /etc/ssh/ -p wa -k ssh_config
-w /etc/nginx/ -p wa -k web_config
-w /etc/obr-math/ -p wa -k obr_secrets
-w /etc/systemd/system/obr-math.service -p wa -k obr_service
-w /home/ubuntu/.ssh/authorized_keys -p wa -k ssh_keys
""",0o600)
run("augenrules","--load")
run("systemctl","daemon-reload")
run("systemctl","restart","systemd-journald")
run("systemctl","restart","obr-math")
print("BACKUP="+str(backup))
print("Access rollback armed for 10 minutes; cancel only after new SSH and HTTPS validation.")
