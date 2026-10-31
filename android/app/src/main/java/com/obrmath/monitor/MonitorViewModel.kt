package com.obrmath.monitor

import android.app.Application
import android.content.Context
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

data class MonitorState(
    val connected: Boolean = false,
    val busy: Boolean = false,
    val error: String = "",
    val notice: String = "",
    val darkTheme: Boolean = true,
    val lastRefreshTime: String = "—",
    val dashboard: Dashboard? = null,
    val selectedReportDate: String = "",
    val report: String = "",
    val background: Boolean = false,
    val pendingChange: String? = null,
    val base: String = "",
    val demo: JSONObject? = null,
    val evolution: JSONObject? = null
)

class MonitorViewModel(app: Application) : AndroidViewModel(app) {
    private val prefs = app.getSharedPreferences("fee_notifications", Context.MODE_PRIVATE)
    private val mutable = MutableStateFlow(
        MonitorState(darkTheme = prefs.getBoolean("dark_theme", true))
    )
    val state = mutable.asStateFlow()

    private var repository: MonitorRepository? = null
    private var session: Pair<String, String>? = null
    private var generation = 0
    private var request: Job? = null
    private var reportJob: Job? = null
    private var modeJob: Job? = null
    private val store = SessionStore(app)

    init {
        viewModelScope.launch {
            try {
                val saved = withContext(Dispatchers.IO) { store.load() }
                if (saved != null && session == null && generation == 0) {
                    connect(saved.first, saved.second, true)
                }
            } catch (_: Exception) {
                mutable.update { it.copy(error = "后台凭据无法读取，请重新连接") }
            }
        }
    }

    private fun nowTimeStr(): String =
        SimpleDateFormat("HH:mm:ss", Locale.US).format(Date())

    fun toggleTheme() {
        val next = !mutable.value.darkTheme
        prefs.edit().putBoolean("dark_theme", next).apply()
        mutable.update { it.copy(darkTheme = next) }
    }

    fun dismissError() {
        mutable.update { it.copy(error = "") }
    }

    fun dismissNotice() {
        mutable.update { it.copy(notice = "") }
    }

    fun connect(base: String, token: String, background: Boolean = false) {
        try {
            val clean = validatedBase(base)
            val next = MonitorRepository(MonitorApi(clean, token))
            generation++
            request?.cancel()
            reportJob?.cancel()
            modeJob?.cancel()
            session = clean to token
            repository = next
            mutable.value = MonitorState(
                base = clean,
                background = background,
                darkTheme = prefs.getBoolean("dark_theme", true)
            )
            refresh()
        } catch (_: Exception) {
            mutable.update { it.copy(error = "请输入正确的 HTTPS 地址和访问令牌") }
        }
    }

    fun refresh() {
        if (request?.isActive == true || modeJob?.isActive == true) return
        val repo = repository ?: return
        val version = generation
        request = viewModelScope.launch {
            mutable.update { it.copy(busy = true, error = "") }
            try {
                val data = repo.load()
                ensureActive()
                if (version != generation) return@launch
                val id = feeChangeId(data.fees)
                val unseen = id?.takeIf { prefs.getString("acknowledged", null) != mutable.value.base + "|" + it }
                mutable.update {
                    it.copy(
                        connected = true,
                        dashboard = data,
                        pendingChange = unseen,
                        lastRefreshTime = nowTimeStr()
                    )
                }
                // Auto-load latest report if none loaded yet and reports exist
                val firstReportDate = data.reports.objects().firstOrNull()?.optString("date")
                if (!firstReportDate.isNullOrBlank() && mutable.value.report.isBlank()) {
                    report(firstReportDate)
                }
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (_: Exception) {
                if (version == generation) {
                    mutable.update {
                        it.copy(error = "刷新失败，请检查网络、HTTPS 服务和访问令牌；现有数据可能过期")
                    }
                }
            } finally {
                if (version == generation) mutable.update { it.copy(busy = false) }
            }
        }
    }

    fun changeMode(mode: String, revision: Int, control: String) {
        val repo = repository ?: return
        if (modeJob?.isActive == true) return
        val version = generation
        request?.cancel()
        modeJob = viewModelScope.launch {
            mutable.update { it.copy(busy = true, error = "", notice = "") }
            try {
                repo.setMode(mode, revision, control)
                val data = repo.load()
                ensureActive()
                if (version == generation) {
                    mutable.update {
                        it.copy(
                            dashboard = data,
                            lastRefreshTime = nowTimeStr(),
                            notice = "交易通道状态已安全更新并同步至服务器"
                        )
                    }
                }
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (error: Exception) {
                if (version == generation) {
                    mutable.update { it.copy(error = error.message ?: "操作结果未知，请刷新核对模式") }
                }
            } finally {
                if (version == generation) mutable.update { it.copy(busy = false) }
            }
        }
    }

    fun report(day: String) {
        val repo = repository ?: return
        val version = generation
        reportJob?.cancel()
        reportJob = viewModelScope.launch {
            try {
                val result = repo.report(day)
                ensureActive()
                if (version == generation) {
                    mutable.update { it.copy(selectedReportDate = day, report = result) }
                }
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (_: Exception) {
                if (version == generation) mutable.update { it.copy(error = "日报读取失败") }
            }
        }
    }

    fun saveConfig(config: JSONObject, control: String) {
        val repo = repository ?: return
        if (modeJob?.isActive == true) return
        val version = generation
        request?.cancel()
        modeJob = viewModelScope.launch {
            mutable.update { it.copy(busy = true, error = "", notice = "") }
            try {
                repo.setConfig(config, control)
                val data = repo.load()
                ensureActive()
                if (version == generation) {
                    mutable.update {
                        it.copy(
                            dashboard = data,
                            lastRefreshTime = nowTimeStr(),
                            notice = "模拟盘预算与风控限额已原子更新"
                        )
                    }
                }
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (error: Exception) {
                if (version == generation) {
                    mutable.update { it.copy(error = error.message ?: "预算保存结果未知，请刷新") }
                }
            } finally {
                if (version == generation) mutable.update { it.copy(busy = false) }
            }
        }
    }

    fun saveLiveConfig(config: JSONObject, control: String) {
        val repo = repository ?: return
        if (modeJob?.isActive == true) return
        val version = generation
        request?.cancel()
        modeJob = viewModelScope.launch {
            mutable.update { it.copy(busy = true, error = "", notice = "") }
            try {
                repo.setLiveConfig(config, control)
                val data = repo.load()
                ensureActive()
                if (version == generation) {
                    mutable.update {
                        it.copy(
                            dashboard = data,
                            lastRefreshTime = nowTimeStr(),
                            notice = "实盘仓位与止盈止损参数已保存生效"
                        )
                    }
                }
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (error: Exception) {
                if (version == generation) {
                    mutable.update { it.copy(error = error.message ?: "实盘仓位参数保存失败，请刷新") }
                }
            } finally {
                if (version == generation) mutable.update { it.copy(busy = false) }
            }
        }
    }

    fun demo() {
        val repo = repository ?: return
        val version = generation
        reportJob?.cancel()
        reportJob = viewModelScope.launch {
            mutable.update { it.copy(busy = true, error = "") }
            try {
                val result = repo.demo()
                ensureActive()
                if (version == generation) {
                    mutable.update { it.copy(demo = result, notice = "合成沙盒回放已完成计算") }
                }
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (_: Exception) {
                if (version == generation) mutable.update { it.copy(error = "回放读取失败，请检查连接") }
            } finally {
                if (version == generation) mutable.update { it.copy(busy = false) }
            }
        }
    }

    fun loadEvolution() {
        val repo = repository ?: return
        val version = generation
        reportJob?.cancel()
        reportJob = viewModelScope.launch {
            mutable.update { it.copy(busy = true, error = "") }
            try {
                val result = repo.evolution()
                ensureActive()
                if (version == generation) {
                    mutable.update { it.copy(evolution = result) }
                }
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (_: Exception) {
                if (version == generation) mutable.update { it.copy(error = "复盘与进化数据读取失败") }
            } finally {
                if (version == generation) mutable.update { it.copy(busy = false) }
            }
        }
    }

    fun triggerPeriodReview(periodType: String, control: String) {
        val repo = repository ?: return
        if (modeJob?.isActive == true) return
        val version = generation
        modeJob = viewModelScope.launch {
            mutable.update { it.copy(busy = true, error = "", notice = "") }
            try {
                repo.triggerReview(periodType, control)
                val evo = repo.evolution()
                ensureActive()
                if (version == generation) {
                    mutable.update {
                        it.copy(
                            evolution = evo,
                            notice = "已重新生成 $periodType 周期复盘与 AI 参数诊断报告"
                        )
                    }
                }
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (error: Exception) {
                if (version == generation) {
                    mutable.update { it.copy(error = error.message ?: "生成周期复盘失败") }
                }
            } finally {
                if (version == generation) mutable.update { it.copy(busy = false) }
            }
        }
    }

    fun proposeAndBacktestStrategy(
        versionId: String,
        parameters: JSONObject,
        notes: String,
        splitRatio: Double,
        control: String
    ) {
        val repo = repository ?: return
        if (modeJob?.isActive == true) return
        val version = generation
        modeJob = viewModelScope.launch {
            mutable.update { it.copy(busy = true, error = "", notice = "") }
            try {
                repo.proposeVersion(versionId, parameters, notes, control)
                val bt = repo.backtestVersion(versionId, splitRatio, control)
                val evo = repo.evolution()
                ensureActive()
                if (version == generation) {
                    val passed = bt.optBoolean("passed_validation", false)
                    val msg = if (passed) {
                        "候选版本 $versionId 已通过样本外验证，可安全晋升为稳定版"
                    } else {
                        "候选版本 $versionId 已提交回测，但未通过样本外门槛（禁止覆盖稳定版）"
                    }
                    mutable.update { it.copy(evolution = evo, notice = msg) }
                }
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (error: Exception) {
                if (version == generation) {
                    mutable.update { it.copy(error = error.message ?: "候选策略回测或提案失败") }
                }
            } finally {
                if (version == generation) mutable.update { it.copy(busy = false) }
            }
        }
    }

    fun promoteStrategyVersion(versionId: String, control: String) {
        val repo = repository ?: return
        if (modeJob?.isActive == true) return
        val version = generation
        modeJob = viewModelScope.launch {
            mutable.update { it.copy(busy = true, error = "", notice = "") }
            try {
                repo.promoteVersion(versionId, control)
                val evo = repo.evolution()
                val dash = repo.load()
                ensureActive()
                if (version == generation) {
                    mutable.update {
                        it.copy(
                            evolution = evo,
                            dashboard = dash,
                            lastRefreshTime = nowTimeStr(),
                            notice = "策略版本 $versionId 已成功晋升为当前线上稳定版"
                        )
                    }
                }
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (error: Exception) {
                if (version == generation) {
                    mutable.update { it.copy(error = error.message ?: "策略晋升失败（需先通过样本外验证）") }
                }
            } finally {
                if (version == generation) mutable.update { it.copy(busy = false) }
            }
        }
    }

    fun acknowledge() {
        val current = mutable.value
        current.pendingChange?.let {
            prefs.edit().putString("acknowledged", current.base + "|" + it).apply()
        }
        mutable.update { it.copy(pendingChange = null) }
    }

    fun background(enabled: Boolean) {
        val saved = session ?: return
        val version = generation
        viewModelScope.launch {
            try {
                if (version != generation || session != saved) return@launch
                if (enabled) {
                    store.save(saved.first, saved.second)
                    FeeWorker.enable(getApplication())
                } else {
                    store.clear()
                    FeeWorker.disable(getApplication())
                }
                mutable.update {
                    it.copy(
                        background = enabled,
                        notice = if (enabled) "已开启 Keystore 加密存储与后台手续费核查提醒" else "已关闭后台提醒并清除本地保存凭据"
                    )
                }
            } catch (_: Exception) {
                mutable.update { it.copy(error = "后台提醒设置失败") }
            }
        }
    }

    fun disconnect() {
        generation++
        request?.cancel()
        reportJob?.cancel()
        modeJob?.cancel()
        repository = null
        session = null
        try {
            store.clear()
            FeeWorker.disable(getApplication())
        } catch (_: Exception) {
            mutable.update { it.copy(error = "清除后台访问失败，请在系统设置中清除此应用数据") }
            return
        }
        mutable.value = MonitorState(darkTheme = prefs.getBoolean("dark_theme", true))
    }
}
