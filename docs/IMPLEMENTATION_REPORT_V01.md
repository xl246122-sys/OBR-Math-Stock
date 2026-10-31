# 实施报告

更新：2026-10-31（Asia/Shanghai）。分阶段开发中，非完整V1.0验收。

## 已部署与真实环境

- 服务器43.163.203.127；Ubuntu26.04.1 LTS；2vCPU；1930MiB RAM；根分区49G/可用41G；NTP已同步；Python3.14.4。
- 安装了缺失的python3.14-venv及依赖，在独立目录创建探测venv和服务venv。
- obr-math.service已启用、active/running，以obr-math非root用户运行；仅监听127.0.0.1:8765。
- healthz返回200；状态API未认证401，正确Bearer令牌200。随机令牌只保存于服务器root可读配置，不在仓库或对话中输出。
- 检查时服务MemoryCurrent=36507648字节。这是瞬时服务内存，不是300标的峰值内存。
- 常驻服务目前只有观察状态API：WATCH_ONLY，market_connection=NOT_STARTED。长时行情探测是独立有限时长任务，不冒充常驻扫描器。
- 证据：evidence/server-deployment.txt、server-service-check.txt、requirements.deployed.txt。
- 服务器11分钟行情采样已完成：price 220条、AAPL quote/kline各0条，三条连接均成功且无报错。纽约周五20:19至20:30，保留标的阶段为C；这是休市采样，不是开市实时量能验收。证据：evidence/server-market-probe.json。

## 已实现代码及边界

| 模块 | 完成内容 | 尚缺内容 |
|---|---|---|
| market.py/feed.py | Decimal字段校验、源时间与推送时间分离、陈旧/重复/乱序拒绝、有界队列、公开股票WS重连退避 | 与常驻扫描和订阅调度接线；超过20流须另验平台限制 |
| universe.py | CSV格式/去重/失败明细/哈希版本、最多300的确定性筛选 | 真实CSV、exchangeInfo及发行人背景证据 |
| calendar.py | 显式已核验交易日、纽约时区/DST、提前收盘截止、未知日期关闭 | 真实权威日历数据源；当前测试日期均SYNTHETIC |
| strategy.py | 完成5mK线ORB/趋势延续研究、连续区间检查、同进度历史累计量RVOL、冷启动、追价/价差拒绝、结构去重 | 1/3/5分钟动量、形成中量能验证、实时接线与评分校准 |
| execution.py | 内存买入模拟、幂等、资金预占、部分成交、盘口只消费一次、超时、未知撤单保护、最多5标的、净费用及退出原因计算 | 自动卖出、交易规则全量校验、重报价、完整持仓/每日损失限制、持久化恢复 |
| storage.py | WAL、候选与拒绝原因、参数快照、有界异步批写、失败锁定、在线备份/完整性校验 | 全量schema迁移、后验走势、自动每日备份、留存/磁盘清理 |
| api.py/config.py | 鉴权状态接口、严格模拟开关、禁止实盘配置 | 完整历史指标/持仓/告警/报告接口 |

策略、模拟撮合和数据库是已测试的库模块，未组成自动交易系统。当前没有真实交易传输实现。全系统网络拦截安全测试仍待集成后完成，不能用单元测试替代未来代码审计。

## 测试与性能

- 最终开发机：37 passed，0.90s；服务器：37 passed，0.30s。服务器证据为evidence/server-tests-latest.txt。
- 覆盖：数据缺失/无效/乱序/重复/过期、未完成和未来K线、历史量能同进度及未来数据排除、ORB/延续区分、DST/提前收盘、CSV、鉴权、部分成交/资金/超时/未知撤单、5标的、净费用、审计事务回滚/恢复、队列溢出和断线保护。
- 仍有1条Starlette/httpx弃用警告；测试通过，后续应迁移测试客户端依赖。
- 服务器合成核心计算基准：10/50/100/200/300标的，分别780/3900/7800/15600/23400个事件；300标的P50=0.004910ms、P95=0.005850ms、P99=0.012000ms。
- 上述仅是SYNTHETIC_CORE_ONLY，排除网络、队列、数据库、券商；不能宣称100ms端到端验收通过。证据：evidence/server-core-benchmark.json。
- 真实行情负载、真实录制回放、全系统峰值内存、信号漏报率、进程崩溃/重启恢复：NOT_TESTED。

## 尚待交付

Web、Android/APK、每日中文报告、告警与自动恢复、完整自动模拟进出仓：NOT_DONE。不存在已实现的盈利或自动交易结果。

缺少真实CSV、只读API Key、账户费用及模拟资金预算；历史同进度量能尚未建立。可以继续不依赖这些材料的开发，但不能启用可交易信号。行情证据见BINANCE_API_CAPABILITY.md。

启停与回滚见OPERATIONS.md；后续顺序见REVIEW_AND_PLAN.md。始终PAPER_MODE=true、LIVE_TRADING_ENABLED=false。
