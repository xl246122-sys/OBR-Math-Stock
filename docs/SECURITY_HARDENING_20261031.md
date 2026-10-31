# 服务器安全加固验收 — 2026-10-31

用户选择保留公网 HTTPS，未采用 VPN。本次完成主机与应用入口加固，不代表不可入侵、正式渗透测试或 CIS 合规认证。

## 已完成并验证

- Ubuntu 已安装当前可用软件包更新，apt 当前无待更新包。重启后内核由 7.0.0-30 升为 7.0.0-42，无待重启标记。
- SSH 禁止 root、密码和交互式密码登录，仅允许 ubuntu 公钥认证。限制尝试次数、会话和未认证连接；关闭 X11、代理和 TCP 转发。专用密钥新连接验证成功。
- UFW 开机启用，默认拒绝入站，仅开放 TCP 22/80/443，保留出站行情和证书访问。保留腾讯云原有防护规则与代理。
- Fail2ban 启用 sshd 和 obr-api 两个监狱。SSH 10 分钟 5 次失败、API 10 分钟 12 次 401 后封禁 1 小时；API 规则用实际 401 日志验证匹配，正常 200 不匹配。
- HTTPS 仅 TLS1.2/1.3，关闭会话票据；限制每 IP 连接数、请求速率、请求体及慢连接超时。只代理当前项目页面、静态资源和已定义 API，非必要方法 405，敏感和未知路径 404。
- Nginx 新访问日志不记录 Authorization 或查询参数。保留原日志，不通过清理日志掩盖历史记录。
- 应用继续非 root 运行、只读系统目录、独立临时目录。新增清空 capabilities、保护内核与控制组、禁止提权相关操作和命名空间创建等 systemd 限制。systemd-analyze 给出 3.0，不能据此推断整体系统绝对安全。
- 开启配置文件与 SSH 授权密钥修改审计；journald 持久化并限制 200MB / 30 天。auditd 重启后运行正常，lost=0。
- 修复自动更新源：原配置把 security 源注释掉，本次显式启用安全源，并保留每天自动更新；自动重启关闭，须在维护窗口执行。
- 项目、Certbot 和审计工具三个 Python 环境的 pip 从 25.1.1 升级到 26.2.2。扫描返回 12 条漏洞记录（含重复编号），修复后三个环境均未发现扫描源已知漏洞；不等同于不存在未知漏洞。
- 环境文件和 TLS 私钥均为 root 0600。访问令牌没有写入代码或报告，也没有更换，以保持现有 App 登录。

## 验收结果

- 后端回归测试 79 项通过。
- 重启后 9 个 API 鉴权访问均 200；缺少令牌 401；非法 POST 405；/.env、/docs 返回 404。
- 真实 TLS 证书校验开启；行情 CONNECTED，规则已核验，仍为 WATCH_ONLY。
- SQLite integrity_check 返回 ok。安全定时器与服务自启动均通过检查。
- 证据：`docs/evidence/security-verification-20261031.json`。

## 恢复与维护

- 修改前配置及数据库备份位于服务器 `/root/obr-security-20261031T021610Z`（root 私有）。访问控制变更前设置过 10 分钟自动回滚，新 SSH/HTTPS 验证后已取消。
- SSH 私钥为本机 `C:/Users/xl246/.ssh/obr_math_ed25519`。密码 SSH 登录已禁用；不要丢失私钥。腾讯云控制台仍是失联后的恢复通道。
- 误封可从可用管理连接/腾讯云控制台执行 `sudo fail2ban-client set obr-api unbanip <你的公网IP>`，SSH 误封使用 sshd 监狱名。
- 服务隔离位于 `/etc/systemd/system/obr-math.service.d/security.conf`，后续部署不应覆盖或删除此目录。
- 新 API/写入操作将需要同步审阅 Nginx 白名单和方法限制。
- IP 证书续期仍由 obr-certbot-renew.timer 管理，80 端口保留给 ACME HTTP 验证。不要在未替换验证方案前关闭 80。

## 明确保留的边界

公网 443、证书验证 80 和仅密钥 SSH 22 仍然可被扫描。没有固定管理出口 IP，因此未设置会导致锁死的 SSH IP 白名单。保留单一监控 Bearer 令牌鉴权，尚无每设备令牌撤销或 MFA；管理密钥拥有既有 sudo 权限。
本次未购买或配置腾讯云 WAF/高防，不能保证抵御大流量 DDoS；也未执行破坏性攻击测试、完整取证或外部异地备份。当前配置备份仍在同一台服务器，不能替代异地恢复副本。

参考官方依据：
https://ubuntu.com/server/docs/how-to/security/openssh-server/
https://documentation.ubuntu.com/security/security-updates/
