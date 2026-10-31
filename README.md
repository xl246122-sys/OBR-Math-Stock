# OBR Math

分阶段开发中。V0.3常驻观察系统已接入479个候选股票池、只读股票规则核验、公开WS、候选审计、监控页、中文日报和每日备份。模拟买卖与事务恢复模块已测试，但自动交易未启用。

Android 原生 Debug APK 已生成：`artifacts/OBR-Math-0.3.0-debug.apk`。已完成编译和 JVM 测试，尚未真机验收；手机连接需要 HTTPS 网关。

Python >=3.11：

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e '.[test]'
$env:OBR_API_TOKEN = (python -c "import secrets; print(secrets.token_urlsafe(32))")
$env:OBR_RUNTIME_ENABLED = 'true'
.venv\Scripts\python -m uvicorn app.api:create_app --factory --host 127.0.0.1 --port 8765
```

`/healthz`公开且仅报告进程存活；`/api/v1/status`要求Bearer令牌。不要将此服务直接裸露公网。

浏览器打开同一地址即为监控页；使用OBR_API_TOKEN登录，不要填Binance凭据。可通过外部环境注入BINANCE_API_KEY进行只读规则刷新，不需要Secret。未设置Key仍可收公开行情，但规则状态显示未核验。

`data/universe.json`为用户CSV正规化结果；`data/calendar.json`为2026–2027带来源版本日历。安卓源码及构建限制见android/README.md。

测试：`python -m pytest -q`。只读行情采样：`python scripts/probe_market.py --seconds 660 --output docs/evidence/probe-new.json`。

合成核心性能基准：`python scripts/benchmark_core.py`，不代表真实行情或端到端延迟。

审阅和分阶段计划见 docs/REVIEW_AND_PLAN.md；实际完成情况见 docs/IMPLEMENTATION_REPORT.md；已部署观察API的运维说明见 docs/OPERATIONS.md。首次部署脚本会拒绝覆盖已有目录。
