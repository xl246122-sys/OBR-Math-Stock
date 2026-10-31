# OBR Math V0.5 交付与验收报告

日期：2026-10-31（北京时间）。**可供手机实测的版本已上线；整个项目仍未全部完成，实盘不可用。**

服务器发布：`/opt/obr-math/releases/v05-20261031T085742Z`。完成部署、Nginx 更新、私有接口与 APK 公网下载验证、模拟开关切换、同值预算保存及服务重启持久化验证。没有提交真实订单、撤单或资金划转。

| 项目 | 状态与证据 |
|---|---|
| 连接与系统 | 已通过固定主机密钥 SSH 发布；服务为 obr-math 非 root 用户，回环端口 8765；原 systemd 安全限制保留 |
| 官方行情 API | exchangeInfo 核验成功；3 路 WS 连接成功；休市无 quote/kline 新消息，不作为开市验收 |
| 原生 App | Kotlin/Compose；预算编辑、互斥模式控制、股票池、持仓、手续费、日报、告警、独立合成回放与权益曲线 |
| 控制权限 | 监控 Bearer 只读；模式和预算 POST 另需操作令牌，错误操作令牌 403；其余路径写入 405 |
| 模拟执行 | 信号到开仓/部分成交/退出/记账/重启恢复测试通过；线上核验条件未满足，保持 WATCH_ONLY |
| 账户预算 | SQLite 与审计事务保存；需关闭模式且空仓无订单；已建立账户初始资金锁定，不能重置余额 |
| 回放 | GET /api/v1/demo 使用隔离临时数据库和合成行情/假设费用；止盈、止损、日亏损样例已在线验证，不写生产账户 |
| 数据库 | 发布前 SQLite backup + integrity_check；旧版及配置保留；新配置与模式重启持久化通过 |
| 性能 | 10/50/100/200/300 标的离线合成负载通过，含 Runtime、审计队列和 SQLite；真实 WS 规模/开市负载 NOT_TESTED |
| Android 构建 | Debug/Release 构建、5 项 JVM 测试、两种 lint 通过；正式包 RSA 3072 专用签名，非 debuggable，minSdk26 |
| 后端测试 | 本地和服务器各 128 项通过；1 条已有 Starlette/httpx 弃用提示 |
| 手机与通知 | 无连接手机或 AVD，真机界面、生命周期及后台通知送达 NOT_TESTED，需用户手机实测 |
| 安全 | HTTPS 证书验证通过；11 个私有 GET 200、无令牌401、无操作权限403；UFW/Nginx/Fail2ban/auditd active |
| 实盘 | NOT_DONE：执行器、真实账户对账、签名交易、订单生命周期与回报未接通；开关禁用，不能将其视为已开发完成 |

## 交付文件

- 正式签名版：`artifacts/OBR-Math-0.5.0.apk`；手机 URL `https://43.163.203.127/downloads/OBR-Math-0.5.0.apk`。
- 覆盖旧调试版：`artifacts/OBR-Math-0.5.0-debug.apk`；手机 URL `https://43.163.203.127/downloads/OBR-Math-0.5.0-debug.apk`。
- 后端发布包及校验：`artifacts/OBR-Math-0.5.0-backend.tar.gz`、`artifacts/v05-manifest.json`。
- 登录和操作令牌：`D:/Key Store/OBR-Math/手机实测访问信息.txt`，仅本机用户权限，未进入源码/APK/公开下载目录。
- 正式签名材料：`D:/Key Store/OBR-Math/AndroidSigning`，用户私密权限；后续正式版必须沿用，切勿丢失。
- 手机安装与测试：`docs/PHONE_TEST_V05.md`。两种签名不兼容；已有调试版可选择调试升级包，正式版需先卸载旧调试版。

## 未完成项与实际限制

1. 实盘完整开发与验收 NOT_DONE。已固定 MAIN/USDC 买入、CARD 卖出结算、不自动划转、只限美国上市股票/ETF且禁止代币化；范围校验不是可运行的实盘执行器。
2. 账户适用官方手续费、权威资产类型证据、真实开市量能及至少 10 个同进度有效历史日仍未满足。不得用样例费率或人为批准替代。
3. 动态分层订阅 NOT_DONE：生产固定关注 9 标的详细行情；479 个候选的全池价格观察不等于完整盘口/K线覆盖。离线 300 标的结果不能授权放大实际 WS 订阅。
4. 录制真实市场数据的完整回放、样本外校准、长期稳定性与手机真机验收仍待完成。本版合成样例可用于功能演示，不构成上述验收。

## 运维与证据

发布前备份：`/root/v05-20261031T085742Z-backup/obr.db`，Nginx 备份同目录 `nginx.conf`。
旧 unit/env：`/etc/obr-math/v05-20261031T085742Z.previous.service` 与 `.previous.env`。回滚须恢复 unit/env 和 Nginx 并测试配置后重启/重载；数据库为新增表兼容迁移，不应盲目覆盖发布后产生的新审计数据。
服务日志 `journalctl -u obr-math`；私有配置不得输出至工单或聊天。APK 下载目录只放安装包。

证据：`evidence/v05-production.json`、`evidence/v05-delivery.json`、`evidence/v05-server-pipeline-load.json`、`evidence/v05-pipeline-load.json`。

上线脚本最后打印中文私密文件路径时遇到本机 cp1252 编码错误；该错误发生在服务发布、Nginx 验证及令牌私密落盘之后。已修正本机打印代码，未重跑发布，独立线上验证通过。
