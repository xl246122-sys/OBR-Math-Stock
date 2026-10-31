# V0.5 已上线（2026-10-31）

原生模拟预算编辑、模式控制、合成回放和权益曲线已加入；正式签名与调试升级包均已构建。安装与实测见 `../docs/PHONE_TEST_V05.md`。实盘不可用，整个项目尚未全部完成。

# Android V0.4 模拟交易监控（2026-10-31）

原生持仓页新增可用资金、当日盈亏、熔断、开仓阻断、风险告警、订单及成交。APK：artifacts/OBR-Math-0.4.0-debug.apk，versionCode 5。构建、5 项 JVM 测试、lint 通过；尚未真机验收。后端 V0.4 已部署并重启，当前因费用和成交量核验未完成保持观察模式。

# Android V0.3.1 登录修复（2026-10-31）

- 默认服务器地址 `https://43.163.203.127`，已完成公开受信任 IP 证书与 Nginx HTTPS 反代。
- 用户已放行腾讯云 TCP 443；本机经公网 TLS 校验，8 个监控接口携带令牌均返回 200，未认证返回 401。
- 访问令牌不包含在源码或 APK 中，已单独交付到用户本机私密文件。
- 登录失败时保留输入令牌，成功后清空输入框。
- 新包 `D:/OBR-Math/artifacts/OBR-Math-0.3.1-debug.apk`，versionCode 4，可覆盖安装前版。
- assembleDebug、5 项 JVM 测试、lintDebug 通过；仍未进行 Android 真机自动化验收。

# OBR Math Android 原生客户端 V0.3

2026-10-31：已生成可安装的 Debug APK，完成编译、4 项 JVM 单元测试及 lint（0 errors、10 warnings）。尚无已连接手机或可用模拟器，真机安装、界面视觉和后台通知送达未验收。

## 已实现

- Kotlin + Jetpack Compose，全原生页面；禁止 WebView、H5 嵌入和网页套壳。
- Compose UI → AndroidViewModel / StateFlow → Repository → HTTPS API 分层。
- 概览、信号、股票池搜索、持仓与模拟预算展示、手续费、日报、告警、设置页面。
- 前台随生命周期刷新；网络失败保留旧数据并提示过期风险；断开会取消当前请求，避免旧响应恢复已断开会话。
- 费用变更原生 AlertDialog，按服务器和变更 ID 记录确认状态。
- 可选后台提醒：用户开启后使用 Android Keystore AES-GCM 加密保存令牌，WorkManager 约每 15 分钟查询服务器已有变更。Android 13+ 请求通知权限，通知渠道使用高重要性，重复变更不重复发送。
- 默认不持久化令牌；关闭后台提醒或断开后清除保存的凭据并取消后台任务。禁止云备份与设备迁移应用数据。
- 仅 HTTPS、固定只读 API 路径、不跟随重定向、限制响应大小，不接受包含账号或查询参数的服务地址。

## 安装包与构建

安装包：`D:/OBR-Math/artifacts/OBR-Math-0.3.0-debug.apk`（调试签名，不是商店发布版）。

环境：JDK 17、Gradle 8.11.1、Android SDK Platform 35 / Build Tools 35.0.0。Gradle Wrapper 已生成并纳入工程。

```powershell
.\gradlew.bat assembleDebug testDebugUnitTest lintDebug
```

`local.properties` 指向本机 SDK，按机器配置，不提交环境路径。常规输出 `app/build/outputs/apk/debug/app-debug.apk`。

测试报告：`app/build/reports/tests/testDebugUnitTest/index.html`；静态报告：`app/build/reports/lint-results-debug.html`。
剩余 lint 提示为 targetSdk/依赖版本较旧及 SharedPreferences KTX 风格建议；没有静态错误。

## 未完成及运行限制

- 后端仅监听 127.0.0.1:8765，手机接入需要受信任的 HTTPS 网关。不能直接填公网 HTTP 地址或跳过证书校验。
- 预算目前为服务器配置展示，尚无 App 内编辑提交功能；自动模拟交易总线尚未连接。
- 原生图表、UI 视觉与无障碍验收、屏幕旋转/进程回收/断网等设备测试待完成。
- WorkManager 的 15 分钟是最小调度间隔，不承诺准点；省电模式、权限、厂商系统限制可延迟或关闭通知。后台查服务器不等于重新向币安查询费率。
- 官方每日核查仍由 Codex 定时任务执行，不是 Android 独立爬取。账户适用费率未确定时继续观察模式。
- 未生成 Release 签名包，未上线商店，不宣称已通过真机验收。

参考：
https://developer.android.com/develop/background-work/background-tasks/persistent/getting-started/define-work
https://developer.android.com/develop/ui/compose/notifications/notification-permission

