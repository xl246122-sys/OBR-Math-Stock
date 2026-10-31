# OBR Math 项目总结与二次开发交接报告

**接收方：Antigravity + 4 Argon**  
**交接日期：2026-10-31（Asia/Shanghai）**  
**工作区：`D:/OBR-Math`**  
**线上版本：V0.5.0；Android versionCode：7**

> **先读结论：项目尚未全部完成。线上已经可以安装原生 APK，测试登录、行情观察、模拟盘开关、预算编辑、日报、告警及隔离合成回放；实盘执行器和真实账户对账没有完成，实盘不可用。线上自动模拟开仓也仍被手续费、成交量等核验条件阻断。不要把开关、离线请求构造器或合成回放当作已实现实盘。**
>
> 本报告依据工作区代码、V0.5 发布记录和已保存验收证据编写。本次交接整理没有重新连接服务器或重新运行全部测试。接手后请先重新核对实时状态。报告不包含密码、API Key、Secret、访问令牌或签名密码。

## 1. 用户已经确认的需求

1. 前端必须是 **Android 原生 Kotlin / Jetpack Compose**，不能改成 WebView、H5 或网页套壳。
2. 观察美国上市股票和 ETF，原始股票池为用户提供的 480 行 CSV，去重后 479 个代码。
3. 策略为 ORB 开盘区间突破和盘中趋势延续，使用闭合 5 分钟 K 线、历史同进度成交量、1/3/5 分钟动量及盘口质量条件。
4. 模拟参数支持用户自定义。默认初始资金 **600 美元**、单笔含费用上限 **300 美元**、同时持仓最多 **2 笔**。
5. 当前默认风控还有：每日最多 5 个不同标的、每标的每日一次尝试、总敞口 600 美元、日亏损 6 美元。以上是当前模拟实现默认值，不是已获确认的实盘资金授权。
6. 净止盈 **+1.75%**、净止损触发 **−0.80%**；收盘前 20 分钟停新仓、前 5 分钟发起退出；支持提前收盘日。不能保证实际成交正好在止损阈值内。
7. 实盘与模拟盘要互斥，各有开关；全部关闭应停止新开仓，不能顺带失去已有仓位的风险监控。
8. 用户已明确实盘资金与品种范围：
   - **MAIN 现货钱包的 USDC 买入**；
   - **卖出结算到 CARD，用户已经明确接受**；
   - **不自动划转**；
   - 只交易正规美国上市股票及 ETF，不做股票代币化，不交易其他产品。
9. 币安官方美股手续费每天检查 1 次，变化时弹窗提醒。公开费用表不等于账户实际适用费率。
10. 服务器保留公网 HTTPS，强化鉴权与主机防护，不采用强制 VPN。
11. 用户已授权开发、部署、服务重启和 APK 编译交付；但当前没有进行任何真实下单、真实撤单或资金划转。接手时不要将开发部署授权解释为立即开实盘。

**无需重复询问的钱包选择：MAIN / USDC 买入、CARD 卖出、不自动划转。** 实盘预算、真实余额和产品权限仍须独立核实，不能自动套用模拟 600 美元，更不能默认使用整个现货钱包余额。

## 2. 当前线上状态和安装入口

| 项目 | 当前记录 |
|---|---|
| 云服务器 | 腾讯云日本，`43.163.203.127` |
| 系统 | 安全加固记录为 Ubuntu 26.04.1 LTS、内核 7.0.0-42；接手时再核实更新情况 |
| SSH 用户 | `ubuntu`，使用专用公钥，具有既有 sudo 权限 |
| 服务账号 | `obr-math`，非 root |
| 线上版本目录 | `/opt/obr-math/releases/v05-20261031T085742Z` |
| systemd 服务 | `obr-math.service` |
| Python 环境 | `/opt/obr-math/.venv`；最近服务器测试 Python 3.14 |
| 后端监听 | `127.0.0.1:8765`，仅由 Nginx 代理 |
| 手机服务器地址 | `https://43.163.203.127`，APK 已默认填写 |
| 数据目录 | `/var/lib/obr-math` |
| 数据库 | `/var/lib/obr-math/obr.db` |
| 实际运行模式 | 最近验收为 `WATCH_ONLY`，`live_trading_enabled=false` |
| 模式开关状态 | 最近验收为 `PAPER`；不代表已经允许自动开仓 |
| 实盘状态 | `live_available=false`，执行器未接通 |
| 行情连接 | 3 路 WS 已连接；验收时为休市，不能视作真实开市报价/K线验收 |
| 配置 | 初始 600、单笔 300、最多 2 仓；模式和预算已通过重启持久化验证 |

APK 直接下载：

- 正式签名版：<https://43.163.203.127/downloads/OBR-Math-0.5.0.apk>
- 覆盖旧调试版：<https://43.163.203.127/downloads/OBR-Math-0.5.0-debug.apk>

正式签名与旧调试签名不同，不能直接覆盖。已装调试版的用户可以用调试升级包；改装正式版需先卸载旧调试版，手机保存的令牌和提醒设置会被清除，服务器数据不受影响。最低 Android 8.0（API 26）。

## 3. 交接必须带走的文件和凭据位置

### 3.1 源码与普通交付文件

请交接整个 `D:/OBR-Math` 的源码、配置示例、数据文件及文档，不要只交后端压缩包。

| 路径（相对工作区） | 用途 |
|---|---|
| `OBR-Math-V1.0-1.md` | 原开发方案；后续用户的原生 App、实盘范围等要求优先于旧方案 |
| `app/` | Python 后端、策略、模拟执行、API |
| `android/` | 原生 Android 项目、Gradle Wrapper |
| `tests/` | 后端自动化测试 |
| `data/` | 股票池、交易日历、模拟配置示例、费用观察数据 |
| `scripts/` | 部署、行情探测、基准测试、费用更新、安全配置模板 |
| `docs/` | 实施记录、说明、验收证据 |
| `artifacts/` | APK、后端发布包、SHA256 清单 |
| `var/` | 本机临时脚本与工作产物；检查后选择性保留，不应直接公开或整目录上传 |

**本次检查没有发现工作区 `.git` 目录。** 不能提供不存在的 Git commit SHA。接手后建议先做安全检查，再建立版本库和 V0.5 基线提交。`.gitignore` 存在，但没有 Git 就不会自动产生版本历史。不要将私密文件或运行数据库提交到仓库。

`artifacts/OBR-Math-0.5.0-backend.tar.gz` 包含 app/tests/data/scripts/pyproject，不含完整 Android 项目、签名密钥及所有交接文档；不是完整工程备份。

### 3.2 私密材料：只记录位置

| 位置 | 内容及注意事项 |
|---|---|
| `C:/Users/xl246/.ssh/obr_math_ed25519` | SSH 私钥；限制为本机用户访问，不能丢失或放进仓库 |
| 用户 SSH `known_hosts`；项目 `var/ssh_known_hosts` | 主机密钥固定记录。不要使用 AutoAddPolicy 或无条件跳过主机验证 |
| `D:/Key Store/OBR-Math/手机实测访问信息.txt` | 当前监控令牌、独立操作令牌、下载地址；Windows 文件 ACL 已限制 |
| `D:/Key Store/OBR-Math/AndroidSigning/obr-math-release.p12` | 正式 APK 签名密钥，后续正式版必须沿用 |
| `D:/Key Store/OBR-Math/AndroidSigning/signing.json` | 签名密码与 alias，禁止打印或提交 |
| `D:/Key Store/Stock-Quant-Math/Stock-Quant-Math-API-KEY.txt` | 用户原始币安凭据文件；不要直接输出内容 |
| `D:/Stock-Google/美股清单/美股股池-480.csv` | 原始股票清单 |
| `/etc/obr-math/obr.env` | 服务器运行环境及应用令牌，root 0600 |
| `/etc/obr-math/binance.env` | 当前服务器仅保存行情 API Key，root 0600；没有部署交易 Secret |

不要将旧聊天中出现过的密码作为正常 SSH 方式。SSH 密码登录及 root SSH 登录已经关闭。换开发工具不意味着授权把凭据上传到第三方聊天、日志或公共制品。

## 4. 架构与源码导航

```text
币安公开行情 WS / exchangeInfo（当前唯一带 Key 的外部 HTTP 为只读 GET）
  → MarketFeed 有界队列
  → Runtime 消息校验、日历、特征
  → OBRMathEngine 闭合 K 线决策
  → EventWriter / AuditStore 审计、后续表现追踪
  → CONFIRMED 信号 + PAPER 开关
  → PaperRuntime 独立风险循环（约 0.5 秒）
  → PaperAccount 原子账户操作
  → PaperBroker / paper_cycle 模拟订单、仓位、退出
  → SQLite 状态 + FastAPI
  → HTTPS Nginx
  → Android Repository → ViewModel/StateFlow → Compose
```

| 文件 | 主要职责 |
|---|---|
| `app/config.py` | 环境配置；当前明确拒绝 `PAPER_MODE=false` 或 `LIVE_TRADING_ENABLED=true` |
| `app/runtime.py` | 启停任务、消息路由、状态、规则刷新、模拟循环、模式和预算变更 |
| `app/feed.py` | 公开 WS；每连接本地上限 20 streams，有界队列、重连与缺口标记 |
| `app/market.py` | Quote/Bar 校验、源时间、重复/乱序/陈旧盘口控制 |
| `app/calendar.py` | 交易日、时区、夏令时、提前收盘 |
| `app/features.py` | 动量、历史同进度成交量、连续会话累计量和质量证据 |
| `app/strategy.py` | ORB 与盘中趋势延续，确认/拒绝原因、评分、幂等候选 ID |
| `app/execution.py` | PaperBroker；限价、预占、部分成交、费用快照、退出和恢复 |
| `app/paper_cycle.py` | 一轮模拟全生命周期、总敞口、日亏损熔断、独立退出 |
| `app/paper_account.py` | 序列化操作、整轮持久化、失败回滚和故障锁定 |
| `app/paper_runtime.py` | 模拟账户 worker 与费用/量能核验读取 |
| `app/paper_config.py` | 模拟预算及限额校验 |
| `app/trading_modes.py` | PAPER/OFF 持久化和版本控制；LIVE 当前始终拒绝 |
| `app/trading_state.py` | 可交易方向、停牌、未来生效状态与保护状态 |
| `app/live_scope.py` | 用户确认的实盘产品/钱包边界、资产证据检查 |
| `app/live_contract.py` | **仅离线构造实盘请求参数，不含签名、HTTP 或订单执行** |
| `app/storage.py` | SQLite WAL、审计、账户/模式/配置事务、备份 |
| `app/research.py` | 信号后 5/15/30/60 分钟及收盘表现追踪，不反馈策略 |
| `app/demo.py` | 隔离临时数据库中的固定合成回放，与生产账户无关 |
| `app/fee_watch.py` | 公开费用指纹、变更、规则生效时间、过期状态 |
| `app/api.py` | 监控 API、独立操作鉴权、模式/预算写接口 |
| `android/.../Data.kt` | HTTPS API 白名单、Repository、响应大小限制 |
| `android/.../MonitorViewModel.kt` | 会话、刷新/操作、取消和生命周期状态 |
| `android/.../MainActivity.kt` | 原生页面、模式开关、预算对话框、回放曲线 |
| `android/.../SessionStore.kt`、`FeeWorker.kt` | Keystore 可选凭据保存、WorkManager 费用通知 |

上表 Android 路径前缀为 `android/app/src/main/java/com/obrmath/monitor/`。

## 5. 已完成、部分完成、未完成

### 已完成并有测试/发布证据

- 公网 HTTPS、原生 App 默认服务器、监控鉴权、独立操作令牌。
- 479 候选代码处理、行情价格观察、固定 9 标的详细订阅、规则刷新。
- 闭合 K 线 ORB/延续策略、动量与同进度历史量特征、日历及质量降级。
- 模拟账户资金预占、限价、部分成交、超时、撤销、盘口去重、订单幂等、费用快照。
- 止盈、止损、日亏损熔断、收盘退出、未知订单保留资金、重启恢复。
- PAPER/OFF 开关互斥；关开仓后继续持仓保护；模式审计、revision 检查。
- App 内预算编辑；需 OFF、空仓、无未终结订单；已建立账户初始资金锁定。
- 状态、股票池、信号、持仓、费用、告警、日报、合成回放和权益曲线。
- 正式签名与调试升级 APK；公网下载与 SHA256 校验。
- 服务器非 root、UFW、Fail2ban、Nginx 限制、日志脱敏、auditd、证书续期。

### 部分完成

- 模拟闭环代码完整并通过合成测试，但**真实行情驱动的自动开仓未验收且当前未启用**。
- 费用公开规则观察/变更提醒已接入，但账户适用费率未核实。
- 资产范围检查有代码，但权威证券类型证据来源与自动加载未接通。
- 有核心与流水线离线负载测试，没有真实 WS 开市规模验收。
- Android 有编译/单元测试/lint，没有连接设备或 AVD 的真机 UI/通知验收。

### 未完成：必须继续开发，不能只“解锁开关”

1. **实盘执行器**：签名请求、真实订单状态机、成交回报、撤单确认、结果未知处理、限速/重试、启动对账。
2. **实盘账户**：真实可用 USDC、已有美股/ETF 仓位、未完成订单、账户权限与费用、独立账本和预算。
3. **权威元数据接入**：正规美国上市股票/ETF 的类别、资产形式、代码对应和有效时间。
4. **动态分层订阅**：目前详细行情固定 9 标的，不是 479 标的全覆盖。
5. **真实开市验证**：K线量能单位/累计规律/闭合标记、连续性、至少 10 个此前有效同进度历史日。
6. **研究回放**：录制真实行情的完整回放、样本外评估、参数比较与长期稳定性。
7. **外部依赖迁移**：手续费日检目前依赖 Codex 定时代理，迁到 Antigravity 后不能默认仍有人执行。
8. **真机验收和运维完善**：后台通知、省电/杀进程、网络恢复、每设备令牌撤销、异地备份等。

## 6. 为什么现在不会自动开仓

最近线上状态包含：

```text
mode = WATCH_ONLY
paper_pipeline_connected = true
paper_account_initialized = false
PAPER_VERIFICATION_REQUIRED
FEES_NOT_VERIFIED
VOLUME_NOT_VERIFIED
```

`PAPER` 是用户选择的通路；`WATCH_ONLY` 是条件未满足后的实际运行状态。不能用“模拟盘开关打开”判断账户已开始交易。

`app/paper_runtime.py::readiness` 读取运行目录的 `paper-verification.json`，要求：

- schema 1，检查时间不在未来，有效期最长 26 小时；
- 有真实 `evidence_reference`；
- `fee_fingerprint` 与最新费用观察一致；`active_rule_ids` 与当前生效规则一致；
- 当前费用观察未过期；
- 账户费用来源为官方，具有明确 `account_scope`；
- 当前只支持 `PROPORTIONAL_WITH_MINIMUM`，即买卖比例费率与最低收费；
- 明确已核验的 `volume_verified_symbols` 和 `verified_price_ticks`。

这只是现有人工证据入口，不能把填入文件当作核验本身。不要复制合成测试费用、随意填写 0 费率或勾选所有股票来解除阻断。如果实际费用包含阶梯、其他费用、币种转换或特殊舍入，应先扩展费用模型和测试。

`VolumeHistory` 仍独立检查至少 10 个此前会话同进度样本，不能使用当天或未来数据补足历史。

## 7. 实盘接线的正确起点与注意事项

当前是**三重未实现状态**，不是单个环境变量开关：

1. `Settings.from_env()` 拒绝实盘启用；
2. `TradingModes.snapshot()` 固定 `live_available=false`，`change("LIVE")` 返回冲突；
3. `Runtime` 仅接入 PaperRuntime，没有真实下单、对账或用户订单回报任务。

请先设计实盘独立服务/账本，保持模拟与实盘路由隔离；完成验证后再逐项替换这些阻断，不能简单删除保护代码。

已核查的官方接口资料：

- 交易 REST：<https://developers.binance.com/en/docs/catalog/advanced-trading-stocks-trading/api/rest-api/trade>
- 用户订单回报：<https://developers.binance.com/en/docs/catalog/advanced-trading-stocks-trading/api/ws-streams/user-streams>
- 官方 SDK 索引：<https://binance.github.io/binance-connector-js/classes/_binance_stocks.StocksRestAPI.RestAPI.html>
- 官方公开费率：<https://www.binance.com/en/fee/stocks>

上述为此前核查来源，接手时须再确认版本。关键约束：

- 下单受理 `status=S` **不是成交**；撤单受理也不代表最终撤销成功。
- `clientOrderId` 官方格式为 32–36 字符；当前策略候选 ID 是 SHA256，不能直接把 64 字符原值作为真实 clientOrderId。
- 当前离线构造器是 LIMIT / RTH / DAY，价格最多两位小数，`tokenize=false`。
- `walletType=MAIN` 表达买入支付钱包；卖出仍按官方规则结算 CARD，不能写代码假装退回现货。
- 查询完整账户、持仓、结算及真实资产映射的官方能力仍需核实；不能把普通现货余额接口、合约仓位接口或订单历史拼接结果冒充完整美股账户快照。
- 不自动调用股票免责声明签署接口；这属于用户本人需理解并接受的产品条款。
- 不自动重试可能已受理的创建订单，不因超时释放预占，不因进程重启重复下单。
- 不把已在用户账户中存在的手工仓位自动接管为策略仓位。
- 模拟余额、模拟成交和合成回放必须与真实账户彻底分开。

## 8. API 与数据库交接

### 8.1 API

公开：`GET /healthz`、项目静态页面、两个精确 APK 下载路径。

以下读取需要 `Authorization: Bearer <监控令牌>`：

```text
/api/v1/status
/api/v1/metrics
/api/v1/signals
/api/v1/outcomes
/api/v1/universe
/api/v1/positions
/api/v1/alerts
/api/v1/fees
/api/v1/reports
/api/v1/reports/YYYY-MM-DD
/api/v1/trading-mode
/api/v1/paper-config
/api/v1/demo
```

写操作仅：

- `POST /api/v1/trading-mode`：`mode` 与 `revision`；当前只允许有效 PAPER/OFF 切换。
- `POST /api/v1/paper-config`：`revision` 及完整预算字段。

两个 POST 同时要求监控 Bearer 和 `X-OBR-Control-Token`。操作令牌必须独立、至少 32 字符，不能等于监控令牌。预算写入字段以 `app/api.py::PaperConfigRequest` 为准，拒绝额外字段及类型不符值。

新增接口时同步修改 **FastAPI、Nginx 精确白名单和 Android 请求白名单**。否则本地测试通过而公网仍会 404/405。不要全局开放任意 POST 或把监控令牌升级成交易控制权限。

### 8.2 数据库

SQLite WAL / synchronous FULL；代码见 `app/storage.py`。主要表：

- `breakout_candidates`、`signal_decisions`、`market_bars`；
- `system_events`、`performance_metrics`、`daily_reports`；
- `universe_snapshots`、`signal_forward_outcomes`；
- `paper_state`、`trading_mode`、`paper_configuration`。

模拟账户目前以整体 JSON snapshot 持久化，包含订单、仓位、成交和风险状态。每轮事务失败会恢复内存快照并锁定故障。模式和预算有 revision，预算与账户限额可以原子更新。

重启后数据库中的预算配置优先于初始配置文件。不要修改文件后误以为已有账户预算一定改变，也不要删库来清除故障或重新充值。

新开发应提供正式 schema 迁移与兼容/回滚测试。当前新增表不等于已经具备完善的迁移框架；历史 orders/fills 长期增长后的快照体积和 I/O 仍需评估。

## 9. 手续费日检：换工具时的重点风险

**现有每天 09:00（北京时间）的官方费用核查依赖 Codex 当前聊天的定时任务，记录的任务 ID 为 `automation`，不是后端 systemd 的独立日检服务。** 本次交接未重新查询该自动任务的当前状态。

本机与服务器此前直接 GET 官方页面得到 202 空内容，所以由定时代理浏览官方页面、核实后写结构化观察并发布；没有已验证可用的自动账户手续费 API。

迁移工作：

1. 在 Antigravity 或独立任务系统重新安排每天一次的官方来源核查；确认可访问性和权限。
2. 比较费用条款指纹、当前生效规则及有效期；失败不覆盖最后成功基线，也不更新时间冒充成功。
3. `scripts/update_fee_watch.py` 更新观察；`scripts/publish_fee_watch.py` 通过 SSH 发布到服务器。
4. 变更/重要核查故障才提醒，无变化保持安静；保留来源、旧值、新值和时间。
5. Android WorkManager 约每 15 分钟查询服务器已有变更，**它不负责每天从币安抓取费率**。仅迁移 App 不会接管日检。
6. 观察超过 26 小时显示 STALE；确认过的公开规则仍不能代表实际账户手续费。

详细流程见 `docs/FEE_MONITOR.md`。该文件前段的 V0.2 发布路径和旧测试数量属于历史记录，不是当前线上版本。

## 10. 构建、测试及性能证据

### 后端

本地为 Python 3.11，服务器最近测试为 Python 3.14。项目要求 Python >=3.11。

```powershell
Set-Location D:\OBR-Math
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[test]"
.\.venv\Scripts\python.exe -m pytest -q
```

不必覆盖原环境。若新工具环境需离线/代理配置，先检查，避免无目的升级所有依赖。

最近结果：**本地 128 通过、服务器 128 通过**。有一条 Starlette/httpx 弃用警告，不是测试失败。曾在受限环境执行线程/临时数据库测试时遇到不完成的情况，在允许相关操作的正常环境测试通过；不要把环境限制误判成所有测试已跑完。

### Android

- JDK 17；本机使用 Microsoft JDK 17.0.20。
- Gradle Wrapper 8.11.1。
- SDK / compileSdk / targetSdk 35；minSdk 26。
- `android/local.properties` 为本机路径，换机器须更新。
- 包名 `com.obrmath.monitor`，versionName `0.5.0`，versionCode `7`。

```powershell
Set-Location D:\OBR-Math\android
.\gradlew.bat assembleDebug testDebugUnitTest lintDebug
```

正式签名构建前，从私密存储加载以下环境变量，不能把密码直接写进命令历史、源码或报告：

```text
OBR_SIGNING_STORE = 正式 p12 文件路径
OBR_SIGNING_PASSWORD = 私密签名密码
keyAlias = obr-math-release
```

再执行 `assembleRelease lintRelease`。现有本机辅助脚本 `var/build_signed_v05.py` 会读取/准备私密签名材料并构建，使用前先审阅；不能丢失原密钥后重新生成并宣称可覆盖旧正式版。

最近 Android 结果：5 项 JVM 测试通过；Debug lint 0 errors / 10 warnings，Release lint 0 errors / 8 warnings；没有真机或 AVD 测试证据。

### 性能结果如何理解

- `scripts/benchmark_core.py`：只测纯策略核心，不含 WS、数据库、队列或 broker。
- `scripts/benchmark_pipeline.py`：合成 K 线经过真实 Runtime、审计队列和 SQLite；不含真实网络和真实交易，也不是重负载真实账户场景。
- 服务器合成 300 标的流水线最近处理 P95 约 0.227ms、到审计批完成 P95 约 16.662ms；这些数字不能冒充真实开市端到端延迟。
- 源行情时间与服务器内部处理耗时必须分开，不得把缺失/过期源时间当作 0ms。

证据：`docs/evidence/v05-server-pipeline-load.json`、`v05-pipeline-load.json`、`v05-core-benchmark.json`。

## 11. 部署、回滚和安全边界

### 部署入口

- `scripts/deploy_release.py`：服务器侧发布器，目前版本前缀限制为 `v05-...`，健康检查期望 `0.5.0`。后续版本需要同步更新，不能只改 APK 版本。
- `var/deploy_v05.py`：本机实际发布流程；包含上传、SHA256 检查、数据库备份、部署、Nginx/APK 发布和私密令牌交付。**这是可执行生产变更脚本，不要在初次阅读交接时直接运行。**
- `var/verify_v05.py`：线上验证脚本，**并非纯只读**：会切换模拟模式、保存同值预算并重启服务。不得把它当无副作用健康检查重复执行。
- `scripts/nginx-obr-math.conf`：当前入口模板；新 APK 文件名和 API 必须同步维护。

正常流程：本地测试/构建 → 审核制品及 SHA256 → 发布前 SQLite backup/integrity_check → 新目录运行服务器测试 → 切换服务 → Nginx `-t` 后重载 → HTTPS/鉴权/下载/持久化验证。

### 当前备份与回滚材料

```text
/root/v05-20261031T085742Z-backup/obr.db
/root/v05-20261031T085742Z-backup/nginx.conf
/etc/obr-math/v05-20261031T085742Z.previous.service
/etc/obr-math/v05-20261031T085742Z.previous.env
```

回滚应先查看上述旧 unit 指向的版本，再恢复 unit/env 和必要的 Nginx 配置、测试后重启/重载。不要自动用备份数据库覆盖发布后产生的审计、配置或交易状态。实盘上线后数据库回滚风险更高，必须先对账。

只读运维示例：

```bash
sudo systemctl status obr-math --no-pager
sudo journalctl -u obr-math -n 100 --no-pager
sudo nginx -t
sudo ufw status
sudo systemctl status obr-certbot-renew.timer --no-pager
```

不要使用 `cat /etc/obr-math/obr.env` 向聊天输出凭据。

### 安全配置不能随发布丢失

- SSH 禁止 root/密码登录，只用固定主机密钥校验后的 ubuntu 公钥登录。
- UFW 默认拒绝入站，仅 22/80/443；80 仍用于 ACME 验证，不能直接关掉。
- Nginx TLS1.2/1.3，连接/速率/请求体限制，日志不记录令牌和查询参数。
- Fail2ban SSH/API 规则；重复使用错误令牌可能触发封禁，不要跑暴力鉴权测试。
- `/etc/systemd/system/obr-math.service.d/security.conf` 保留；服务非 root，ProtectSystem=strict，NoNewPrivileges=yes。
- 环境文件 root 0600；应用只写自己的数据目录，不能为了方便设 777 或改成 root 运行。
- IP TLS 证书为短有效期证书，续期依赖 `obr-certbot-renew.timer`，接手时优先检查，不要只看曾经 HTTPS 成功。
- 已有安全更新、auditd 和日志持久化；同机备份不是异地灾备，也没有“不会被 AI 攻击”的保证。

历史问题：第一次 V0.4 发布曾因 root umask 导致代码目录 700，服务无法 CHDIR，自动回滚成功；发布器现已显式设置代码目录 755、文件 644。V0.5 最后本机打印中文路径曾触发 cp1252 错误，但发生在发布和私密落盘后，独立线上验收成功；打印已修正，不要据此重复部署。

## 12. 需优先审查的工程风险

以下是接手时的审查重点，不是声称所有问题已经修复：

1. `MarketFeed.data_gap` 在断流/队列溢出后锁定，普通重连不会清除。应设计经过连续性验证的恢复流程，不能简单赋 false。
2. Runtime 对第 3 路 feed 的状态流位置有固定索引假设。实现动态订阅前先抽象 feed 角色，避免重排连接后误用报价流作为状态流。
3. `paper-verification.json` 和 `InstrumentEvidence` 是输入证据载体，不会自行证明填写内容真实；权威来源接入、校验和审计仍需实现。
4. 账户状态写入失败会锁定 `PAPER_STORAGE_FAILED`。独立任务存在不代表存储失效时仍能安全执行所有退出；实盘必须设计外部告警和真实账户风险应对。
5. `paper_state` 整体 JSON 中历史 orders/fills 会增长，长期延迟与恢复时间需实际测量。
6. `Account` 数据与模拟初始资金不可混用；引入实盘必须有独立余额、费用、订单命名空间与审计。
7. 关开仓不是紧急强制平仓。UI、API 和后端必须对“停止入场”“取消挂单”“退出仓位”有明确不同语义。
8. 当前 2 秒源报价时效严格；官方只读最新报价接口可能返回更陈旧数据，不能无条件代替 WS。
9. 暂无每设备令牌撤销、MFA、异地备份或完整外部渗透验收。
10. 核心/合成测试通过不能替代真实市场、真实账户、真机和长期运行验收。

## 13. 建议 Antigravity + 4 Argon 分工

以下为建议分工，不假定接手工具的具体 API、自动调度或模型能力。Antigravity 可负责集成与发布，4 个开发单元按边界协作，避免同时改同一份 Runtime/API/数据库协议。

| 单元 | 负责范围 | 必须交付 |
|---|---|---|
| Argon 1：行情与研究 | 官方资产元数据、动态订阅、量能校验、真实录制回放、样本外评估 | 可追溯数据证据、订阅恢复与负载测试、无前视证明 |
| Argon 2：执行与账户 | 实盘适配器、只读对账、独立账本、订单回报、限价/取消/未知状态 | 无真实资金的 Mock/录制合同测试、幂等与恢复测试、明确启用条件 |
| Argon 3：Android | 原生页面完善、实盘与模拟状态区别、真机通知、网络恢复、签名升级 | 真机验收记录、APK、清晰风险/故障状态，不显示虚假成功 |
| Argon 4：质量与运维 | 回归/故障/备份恢复、费用日检迁移、证书/部署/安全与监控 | 可重复验收、迁移后的定时核查、回滚与恢复说明 |
| Antigravity：集成负责人 | 用户约束、接口协议、分支集成、版本/DB 迁移、发布与报告 | 单一可信完成清单、完整测试、受控发布、未完成项如实列明 |

共享修改点应由集成负责人协调：`runtime.py`、`api.py`、`storage.py`、Android `Data.kt`/`MonitorViewModel.kt`、Nginx 白名单。先定义接口契约，再分工实现；不要让多个单元独立解除 LIVE 保护。

## 14. 建议推进顺序和验收门槛

### P0：接手当天，先保护现有可用版本

- [ ] 保存完整工作区并建立版本库基线，确认没有私钥/令牌进入仓库。
- [ ] 验证 SSH 主机指纹、当前 release、HTTPS 证书续期和服务状态。
- [ ] 验证正式 APK 签名材料可用，不重新生成替代密钥。
- [ ] 手机安装 V0.5，跑登录、预算、模式、合成回放及通知权限流程。
- [ ] 迁移 Codex 依赖的费用日检；确认旧任务与新任务不会重复发布。
- [ ] 保持现有实盘禁用和开仓核验约束。

### P1：让真实行情模拟盘具备验收条件

- [ ] 核实账户实际适用官方费用及准确模型。
- [ ] 建立权威股票/ETF 元数据及更新机制。
- [ ] 开市采样确认 K 线/量能/源时间/停牌状态，积累或合法接入同进度历史。
- [ ] 用真实录制行情跑相同策略和执行路径，覆盖缺口、重启、部分成交、退出未成交。
- [ ] 完成动态订阅与实际网络负载验证，按证据放大覆盖范围。

### P2：实盘代码开发与隔离验收

- [ ] 明确真实账户 API 能力与完整对账来源，不猜路径或资金资产映射。
- [ ] 完成独立执行与账本、真实订单状态机、回报和恢复。
- [ ] 模拟通路拦截测试证明不会触达真实交易写端点。
- [ ] 对请求已发送但响应丢失、部分成交与取消竞争、进程重启等场景做合同测试。
- [ ] 对实际费用、币种、资金预占、持仓数量和最大损失做独立核验。
- [ ] 按用户本人操作与适用平台规则处理实盘启用；不要由开发代理直接用真实资金“试一单”。

### P3：最终交付

- [ ] Android 真机、后台/杀进程/网络切换与版本升级验收。
- [ ] 数据库备份恢复、服务重启、凭据轮换、证书续期、故障告警验收。
- [ ] 完成真实开市及长期运行记录，区分模拟收益与真实收益。
- [ ] 新版 source、APK、签名指纹、发布 manifest、生产证据、回滚说明与未完成清单齐全。

## 15. 当前制品与证据索引

| 制品 | SHA256 |
|---|---|
| `artifacts/OBR-Math-0.5.0-backend.tar.gz` | `56873b2b1005cb0a7310618b1c810bb8b5c5440d4eb645d7402269adf6886230` |
| `artifacts/OBR-Math-0.5.0.apk` | `22da0dc0a293f135a950c1337fbdd5ac74ee63ab3f3162f6823c45ea22eb980b` |
| `artifacts/OBR-Math-0.5.0-debug.apk` | `b497bcc6d942dc09c994a998e496b355e346531fa48b773665bd23fea03eb913` |

正式签名证书 SHA256：`20e442ec2311c45c6bbf702017bbd5c07284cceda5cad591eba24d7832632fa5`。这是公开证书指纹，不是签名私钥。

阅读优先级：

1. 本报告与 `docs/IMPLEMENTATION_REPORT.md`：当前状态。
2. `docs/PHONE_TEST_V05.md`：手机安装实测。
3. `docs/evidence/v05-production.json`：公网验证、模式/预算/重启与下载校验。
4. `docs/evidence/v05-delivery.json`、`artifacts/v05-manifest.json`：构建、签名、校验。
5. `docs/PAPER_LOOP_V04.md`：模拟闭环和核验格式。
6. `docs/TRADING_MODES_PROGRESS.md`：模式与实盘范围设计的历史进度，发布状态以 V0.5 报告为准。
7. `docs/FEE_MONITOR.md`、`docs/BINANCE_API_CAPABILITY.md`：官方接入过程与限制，注意历史时间。
8. `docs/SECURITY_HARDENING_20261031.md`、`docs/OPERATIONS.md`：主机与运维。

## 16. 可直接粘贴给接手开发系统的启动说明

> 请接手 `D:/OBR-Math`，先阅读根目录《项目交接报告_Antigravity_4Argon_2026-10-31.md》与 `docs/IMPLEMENTATION_REPORT.md`，再核对代码和线上状态。当前线上 V0.5.0 是原生 Android 监控/模拟测试版本，不是已完成的实盘产品。请按报告中的分工推进未完成开发，保留 MAIN/USDC 买入、CARD 卖出、不自动划转、只限正规美国股票/ETF、禁止代币化的用户约束。先建立源码基线、确认密钥安全和手续费日检迁移，再做真实行情模拟验收及实盘独立账户/订单链路。禁止通过填假费率、伪造元数据、解除开关保护或使用合成结果冒充真实验收。新增版本需保留既有正式签名，完成本地/服务器测试、备份、受控部署及手机验收；明确列出所有 NOT_DONE/NOT_TESTED 项目。不要输出密钥或代替用户提交真实交易来做测试。

---

**交接边界：本文件是开发现状与建议清单，不是“项目全部开发完成”的证明，也不是实盘资金操作指令。**
