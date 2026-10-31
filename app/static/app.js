"use strict";
let token = "", timer = null, pending = false, universeData = null;
const $ = id => document.getElementById(id);
const names = {VOLUME_NOT_VERIFIED:"实时量能尚未验证",HISTORICAL_VOLUME_COLD_START:"历史同进度量能积累中",FEES_NOT_VERIFIED:"账户适用手续费尚待核实",PAPER_BUDGET_NOT_CONFIGURED:"模拟资金预算尚未配置",AUTO_TRADING_NOT_CONNECTED:"自动模拟交易尚未启用",EXCHANGE_RULES_UNVERIFIED_OR_STALE:"平台交易规则待刷新",MARKET_DATA_GAP:"行情连续性存在缺口"};
function text(id,value){$(id).textContent=value;}
function number(value,suffix=""){return typeof value==="number"?value.toFixed(2)+suffix:"未测得";}
function error(message){$("error").hidden=!message;text("error",message||"");}
async function api(path){const response=await fetch("/api/v1/"+path,{headers:{Authorization:"Bearer "+token},cache:"no-store"});if(!response.ok)throw new Error(response.status===401?"令牌无效，请重新连接。":"接口暂不可用（"+response.status+"），稍后重试。");return response.headers.get("content-type").includes("application/json")?response.json():response.text();}
function table(id,headers,rows){const root=$(id);root.replaceChildren();if(!rows.length){root.textContent="暂无记录。系统不会用示例数据填充此处。";return;}const table=document.createElement("table"),thead=document.createElement("thead"),tr=document.createElement("tr");headers.forEach(h=>{const th=document.createElement("th");th.textContent=h;tr.append(th);});thead.append(tr);table.append(thead);const body=document.createElement("tbody");rows.forEach(row=>{const tr=document.createElement("tr");row.forEach(value=>{const td=document.createElement("td");td.textContent=value??"—";tr.append(td);});body.append(tr);});table.append(body);root.append(table);}
function renderUniverse(){if(!universeData)return;const query=$("search").value.toUpperCase().trim();table("universe-table",["代码","平台交易方向","重点订阅"],universeData.symbols.filter(s=>s.includes(query)).map(s=>[s,universeData.rules[s]?.tradability||"未找到",universeData.focus.includes(s)?"是":"否"]));}
async function refresh(){if(pending||!token)return;pending=true;try{const [status,metric,signals,alerts,reports,u]=await Promise.all([api("status"),api("metrics"),api("signals"),api("alerts"),api("reports"),api("universe")]);error("");$("login").hidden=true;$("workspace").hidden=false;const m=metric.latest; text("connection",`${status.market_connection} · ${status.market_phase} · 更新于 ${new Date().toLocaleTimeString()}`);text("health",status.health);text("mode",status.mode);text("symbols",`${status.observed_symbols} / ${status.candidate_count}`);text("focus",`${status.focus_count} 个重点标的`);text("latency",number(m.processing?.p95_ms," ms"));text("memory",typeof m.rss_bytes==="number"?number(m.rss_bytes/1048576," MB"):"未测得");text("uptime",`运行 ${Math.floor((m.uptime_seconds||0)/60)} 分钟`);$("blockers").replaceChildren(...status.blockers.map(code=>{const li=document.createElement("li");li.textContent=names[code]||code;return li;}));$("focus-symbols").replaceChildren(...status.focus_symbols.map(s=>{const span=document.createElement("span");span.className="tag";span.textContent=s;return span;}));$("feeds").replaceChildren(...status.feeds.map((f,i)=>{const row=document.createElement("div");row.className="feed-row";const label=document.createElement("span"),value=document.createElement("span");label.textContent=i===0?"全市场价格":"重点报价 / K线";value.textContent=`${f.connected?"已连接":"重连中"} · 队列 ${f.queue} · 重连 ${f.reconnects}`;row.append(label,value);return row;}));text("source-age","源行情年龄 P95："+number(m.source_age?.p95_ms," ms"));table("signal-table",["标的","类型","状态","原因","源时间（UTC）"],signals.map(s=>[s.symbol,s.kind,s.state,s.reason,new Date(s.source_ms).toISOString()]));table("alert-table",["时间（UTC）","告警","详情"],alerts.map(a=>[new Date(a.time_ms).toISOString(),a.code,JSON.stringify(a.detail)]));$("report-list").replaceChildren(...reports.map(r=>{const button=document.createElement("button");button.className="secondary";button.textContent=r.date;button.onclick=async()=>{try{text("report-body",await api("reports/"+r.date));}catch(e){error(e.message);}};return button;}));if(!reports.length)text("report-body","暂无日报，等待定时生成。");universeData=u;text("universe-summary",`${u.symbols.length} 个去重候选；发行人地区与市值仍待核验。`);renderUniverse();await refreshFees();}catch(e){error(e.message);}finally{pending=false;}}
$("login-form").onsubmit=async event=>{event.preventDefault();token=$("token").value.trim();$("token").value="";await refresh();clearInterval(timer);timer=setInterval(refresh,10000);};
$("logout").onclick=()=>{token="";clearInterval(timer);$("workspace").hidden=true;$("login").hidden=false;error("");};
document.querySelectorAll("[data-tab]").forEach(button=>button.onclick=()=>{document.querySelectorAll(".panel").forEach(p=>p.hidden=p.id!==button.dataset.tab);document.querySelectorAll("[data-tab]").forEach(b=>b.classList.toggle("active",b===button));});
$("search").oninput=renderUniverse;

// Fee observations contain no account credentials. Persist acknowledgement only.
const feePanel=document.createElement("section");
feePanel.className="card";
const feeTitle=document.createElement("h2"),feeStatus=document.createElement("p"),feeDetails=document.createElement("details"),feeSummary=document.createElement("summary"),feeBody=document.createElement("pre"),feeLink=document.createElement("a");
feeTitle.textContent="币安官方美股手续费";feeSummary.textContent="查看官方费率与适用条件";feeLink.textContent="打开币安官方费用表";feeLink.href="https://www.binance.com/en/fee/stocks";feeLink.target="_blank";feeLink.rel="noopener noreferrer";
feeBody.style.whiteSpace="pre-wrap";feeDetails.append(feeSummary,feeBody);feePanel.append(feeTitle,feeStatus,feeLink,feeDetails);$("workspace").append(feePanel);
const feeDialog=document.createElement("dialog"),feeDialogTitle=document.createElement("h2"),feeDialogText=document.createElement("pre"),feeAck=document.createElement("button");
feeDialogTitle.textContent="币安美股手续费发生变更";feeDialogText.style.whiteSpace="pre-wrap";feeDialogText.style.maxHeight="60vh";feeDialogText.style.overflow="auto";feeAck.textContent="我已知悉";feeDialog.append(feeDialogTitle,feeDialogText,feeAck);document.body.append(feeDialog);
let displayedFeeChange=null, acknowledgedFeeChange=null;
try{acknowledgedFeeChange=localStorage.getItem("obr-fee-change-ack");}catch(e){}
feeAck.onclick=()=>{acknowledgedFeeChange=displayedFeeChange;try{localStorage.setItem("obr-fee-change-ack",displayedFeeChange);}catch(e){}feeDialog.close();};
async function refreshFees(){
 const fee=await api("fees");
 const checked=fee.observation?.checked_ms;
 feeStatus.textContent=(fee.status==="CURRENT_PUBLIC_SCHEDULE"?"官方公开费率已核查":fee.status==="STALE"?"核查已超过26小时，等待更新":"尚无成功核查记录")+" · 每天北京时间09:00检查 · "+(checked?"上次核查 "+new Date(checked).toLocaleString():"")+" · 账户适用费率仍待核实";
 feeBody.textContent=JSON.stringify(fee.observation?.terms||{},null,2);
 if(fee.change && fee.change.id!==acknowledgedFeeChange && fee.change.id!==displayedFeeChange){
  displayedFeeChange=fee.change.id;
  feeDialogText.textContent="核查时间："+new Date(fee.change.time_ms).toLocaleString()+"\n官方来源："+fee.source+"\n变更类型："+fee.change.kind+"\n原规则：\n"+JSON.stringify(fee.change.before,null,2)+"\n新规则：\n"+JSON.stringify(fee.change.after,null,2)+"\n生效规则："+fee.change.active_rules.join(", ");
  if(!feeDialog.open)feeDialog.showModal();
 }
}
