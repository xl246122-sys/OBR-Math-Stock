# 当前观察系统运维（V0.2）

服务：obr-math.service；专用用户：obr-math；监听：127.0.0.1:8765。

当前源码：/opt/obr-math/releases/v02-20261031T010743Z；共享venv：/opt/obr-math/.venv。
监控配置：/etc/obr-math/obr.env；行情Key：/etc/obr-math/binance.env（均root可读，后者仅API Key，不含Secret）。
数据库、报告、备份：/var/lib/obr-math/obr.db、reports/、backups/。日志：journald。

```sh
sudo systemctl status obr-math
sudo systemctl restart obr-math
sudo journalctl -u obr-math --since '1 hour ago'
curl http://127.0.0.1:8765/healthz
```

首次部署脚本scripts/deploy_stage_a.sh仅允许全新目录。增量发布用scripts/deploy_release.py，先测试，再切换systemd工作目录；健康检查失败自动回滚。凭据通过stdin传入，禁止命令行参数或源码硬编码。

访问使用SSH隧道：`ssh -N -L 8765:127.0.0.1:8765 ubuntu@43.163.203.127`，然后浏览器打开http://127.0.0.1:8765。输入服务器监控配置中的OBR_API_TOKEN（不是Binance Key）。令牌不在对话或仓库输出；浏览器仅保存在内存。公开healthz只证明进程存活，不证明行情或策略可用。

停止：`sudo systemctl stop obr-math.service`。禁用自启：`sudo systemctl disable obr-math.service`。
版本回滚：当前发布对应的上一份配置为/etc/obr-math/v02-20261031T010743Z.previous.env及.previous.service；停服务后恢复到各自原路径，保留0600配置权限，再daemon-reload并启动。数据库不要盲目用旧备份覆盖；先复制到新路径完整性检查。当前schema v2为新增表，旧观察版不依赖这些新增表。

数据库已接入常驻服务；`AuditStore.backup(new_path)`使用SQLite在线备份并检查完整性。按纽约日期每天保留一份，不自动删除关键审计记录。性能历史保留90天；备份留存清理和大规模归档仍待完成，磁盘余量低于25%会告警。

日报：纽约16:15生成，启动时按时点补当前或前一日报。首日为PARTIAL_OBSERVATION；延迟是最近窗口，消息计数是进程级，不冒充全日统计。
重启后行情重新连接，历史指标/日报/候选保留；未完成的后验研究恢复，重启缺口的极值标为PARTIAL_AFTER_RESTART。
当前没有配置自动模拟交易账户；PaperAccount恢复功能已单测，不代表服务器已经运行自动交易。


## 2026-10-31 手机 HTTPS 接入

公网入口：https://43.163.203.127，Nginx 443 转发到原有 127.0.0.1:8765。HTTP 80 仅提供 ACME 验证并重定向 HTTPS。用户已在腾讯云放行 443。
证书位于 /etc/letsencrypt/live/obr-math-ip/，由 /opt/obr-certbot/bin/certbot 5.9 管理；IP 证书有效期约 6 天。
obr-certbot-renew.timer 每天 00/12 点（服务器时区）加随机延迟检查续期，Persistent=true；部署钩子先 nginx -t 再 reload。发行版 certbot 4.0 的旧 timer 已停用，防止使用不支持 IP 的客户端。
配置模板：scripts/nginx-obr-math.conf、scripts/obr-certbot-renew.service、scripts/obr-certbot-renew.timer。
公网验证：8 类监控 API 带令牌 200，未认证 401。令牌不写入 APK、源码、日志或此文档。
`n续期验收：certbot renew --dry-run --no-random-sleep-on-renew 成功；最终 Android 0.3.1 APK 签名核验通过。


## 2026-10-31 安全基线更新

当前SSH仅ubuntu公钥登录，禁用密码/root/TCP转发；旧SSH隧道访问说明已不适用，App继续通过公网HTTPS访问。安全更新、UFW、Fail2ban、审计与systemd隔离已启用，并完成重启验收。详细规则、恢复方式及限制见 SECURITY_HARDENING_20261031.md。
