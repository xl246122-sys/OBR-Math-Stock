package com.obrmath.monitor

import android.app.Application
import android.content.Context
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import org.json.JSONObject

data class MonitorState(val connected: Boolean=false,val busy: Boolean=false,val error: String="",
    val dashboard: Dashboard?=null,val report: String="",val background: Boolean=false,
    val pendingChange: String?=null,val base: String="",val demo: JSONObject?=null)

class MonitorViewModel(app: Application): AndroidViewModel(app) {
    private val mutable=MutableStateFlow(MonitorState())
    val state=mutable.asStateFlow()
    private var repository: MonitorRepository?=null
    private var session: Pair<String,String>?=null
    private var generation=0
    private var request: Job?=null
    private var reportJob: Job?=null
    private var modeJob: Job?=null
    private val store=SessionStore(app)
    private val prefs=app.getSharedPreferences("fee_notifications",Context.MODE_PRIVATE)
    init {
        viewModelScope.launch {
            try {
                val saved=withContext(Dispatchers.IO) { store.load() }
                if (saved!=null && session==null && generation==0) connect(saved.first,saved.second,true)
            } catch (_: Exception) { mutable.update { it.copy(error="后台凭据无法读取，请重新连接") } }
        }
    }
    fun connect(base: String,token: String,background: Boolean=false) {
        try {
            val clean=validatedBase(base)
            val next=MonitorRepository(MonitorApi(clean,token))
            generation++;request?.cancel();reportJob?.cancel();modeJob?.cancel()
            session=clean to token;repository=next
            mutable.value=MonitorState(base=clean,background=background)
            refresh()
        } catch (_: Exception) { mutable.update { it.copy(error="请输入正确的 HTTPS 地址和访问令牌") } }
    }
    fun refresh() {
        if (request?.isActive==true || modeJob?.isActive==true) return
        val repo=repository ?: return
        val version=generation
        request=viewModelScope.launch {
            mutable.update { it.copy(busy=true,error="") }
            try {
                val data=repo.load()
                ensureActive()
                if (version!=generation) return@launch
                val id=feeChangeId(data.fees)
                val unseen=id?.takeIf { prefs.getString("acknowledged",null)!=mutable.value.base+"|"+it }
                mutable.update { it.copy(connected=true,dashboard=data,pendingChange=unseen) }
            } catch (cancelled: CancellationException) { throw cancelled }
            catch (_: Exception) { if(version==generation) mutable.update { it.copy(error="刷新失败，请检查网络、HTTPS 服务和访问令牌；现有数据可能过期") } }
            finally { if(version==generation) mutable.update { it.copy(busy=false) } }
        }
    }
    fun changeMode(mode: String,revision: Int,control: String) {
        val repo=repository ?: return
        if(modeJob?.isActive==true) return
        val version=generation
        request?.cancel()
        modeJob=viewModelScope.launch {
            mutable.update { it.copy(busy=true,error="") }
            try {
                repo.setMode(mode,revision,control)
                val data=repo.load();ensureActive()
                if(version==generation) mutable.update { it.copy(dashboard=data) }
            } catch(cancelled: CancellationException) { throw cancelled }
            catch(error: Exception) {
                if(version==generation) mutable.update { it.copy(error=error.message ?: "操作结果未知，请刷新核对模式") }
            } finally { if(version==generation) mutable.update { it.copy(busy=false) } }
        }
    }
    fun report(day: String) {
        val repo=repository ?: return
        val version=generation
        reportJob?.cancel()
        reportJob=viewModelScope.launch {
            try {
                val result=repo.report(day);ensureActive()
                if(version==generation) mutable.update { it.copy(report=result) }
            } catch(cancelled: CancellationException) { throw cancelled }
            catch(_: Exception) { if(version==generation) mutable.update { it.copy(error="日报读取失败") } }
        }
    }
    fun saveConfig(config: JSONObject,control: String) {
        val repo=repository ?: return
        if(modeJob?.isActive==true) return
        val version=generation;request?.cancel()
        modeJob=viewModelScope.launch {
            mutable.update { it.copy(busy=true,error="") }
            try {
                repo.setConfig(config,control)
                val data=repo.load();ensureActive()
                if(version==generation) mutable.update { it.copy(dashboard=data) }
            } catch(cancelled: CancellationException) { throw cancelled }
            catch(error: Exception) { if(version==generation) mutable.update { it.copy(error=error.message ?: "预算保存结果未知，请刷新") } }
            finally { if(version==generation) mutable.update { it.copy(busy=false) } }
        }
    }
    fun saveLiveConfig(config: JSONObject,control: String) {
        val repo=repository ?: return
        if(modeJob?.isActive==true) return
        val version=generation;request?.cancel()
        modeJob=viewModelScope.launch {
            mutable.update { it.copy(busy=true,error="") }
            try {
                repo.setLiveConfig(config,control)
                val data=repo.load();ensureActive()
                if(version==generation) mutable.update { it.copy(dashboard=data) }
            } catch(cancelled: CancellationException) { throw cancelled }
            catch(error: Exception) { if(version==generation) mutable.update { it.copy(error=error.message ?: "实盘仓位参数保存失败，请刷新") } }
            finally { if(version==generation) mutable.update { it.copy(busy=false) } }
        }
    }
    fun demo() {
        val repo=repository ?: return
        val version=generation;reportJob?.cancel()
        reportJob=viewModelScope.launch {
            try {
                val result=repo.demo();ensureActive()
                if(version==generation) mutable.update { it.copy(demo=result) }
            } catch(cancelled: CancellationException) { throw cancelled }
            catch(_: Exception) { if(version==generation) mutable.update { it.copy(error="回放读取失败，请检查连接") } }
        }
    }
    fun acknowledge() {
        val current=mutable.value
        current.pendingChange?.let { prefs.edit().putString("acknowledged",current.base+"|"+it).apply() }
        mutable.update { it.copy(pendingChange=null) }
    }
    fun background(enabled: Boolean) {
        val saved=session ?: return
        val version=generation
        viewModelScope.launch {
            try {
                if(version!=generation || session!=saved) return@launch
                // Serialized with UI session changes, so logout cannot race a pending save.
                if(enabled) { store.save(saved.first,saved.second);FeeWorker.enable(getApplication()) }
                else { store.clear();FeeWorker.disable(getApplication()) }
                mutable.update { it.copy(background=enabled) }
            } catch(_: Exception) { mutable.update { it.copy(error="后台提醒设置失败") } }
        }
    }
    fun disconnect() {
        generation++;request?.cancel();reportJob?.cancel();modeJob?.cancel();repository=null;session=null
        try { store.clear();FeeWorker.disable(getApplication()) }
        catch(_: Exception) { mutable.update { it.copy(error="清除后台访问失败，请在系统设置中清除此应用数据") };return }
        mutable.value=MonitorState()
    }
}
