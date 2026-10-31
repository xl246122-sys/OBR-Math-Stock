from collections import Counter, deque
from datetime import datetime, time as dt_time, timedelta
import os
from pathlib import Path
import shutil
import time
from app.calendar import NY


class Metrics:
    def __init__(self):
        self.counts = Counter()
        self.processing_ms = deque(maxlen=10000)
        self.queue_ms = deque(maxlen=10000)
        self.source_age_ms = deque(maxlen=10000)
        self.started = time.monotonic()
        self.cpu_time = sum(os.times()[:2])
        self.cpu_checked = self.started

    def snapshot(self, data_dir):
        def percentiles(values):
            if not values:
                return {"status": "NOT_TESTED", "samples": 0}
            ordered = sorted(values)
            return {"samples": len(ordered), **{f"p{p}_ms": ordered[int((len(ordered)-1)*p/100)] for p in (50,95,99)}}
        elapsed = time.monotonic()-self.cpu_checked
        cpu = sum(os.times()[:2])
        cpu_percent = 100*(cpu-self.cpu_time)/elapsed if elapsed else 0
        self.cpu_time, self.cpu_checked = cpu, time.monotonic()
        rss = None
        proc = Path("/proc/self/status")
        if proc.exists():
            for line in proc.read_text().splitlines():
                if line.startswith("VmRSS:"):
                    rss = int(line.split()[1])*1024
        disk = shutil.disk_usage(data_dir)
        return {"counts_since_process_start": dict(self.counts), "uptime_seconds": time.monotonic()-self.started,
                "processing": percentiles(self.processing_ms), "queue_wait": percentiles(self.queue_ms),
                "source_age": percentiles(self.source_age_ms), "window": "last_10000_samples",
                "cpu_percent_one_core": cpu_percent, "rss_bytes": rss,
                "disk_free_ratio": disk.free/disk.total, "disk_free_bytes": disk.free}


def daily_report(store, directory, day, calendar, status, metrics, now_ms):
    """Exactly one database report per NY day; deterministic rules, no AI calls."""
    key = day.isoformat()
    existing = store.report(key)
    start = datetime.combine(day, dt_time.min, NY)
    end = datetime.combine(day+timedelta(days=1), dt_time.min, NY)
    counts = store.day_counts(int(start.timestamp()*1000), int(end.timestamp()*1000))
    payload = {"date": key, "generated_ms": now_ms, "calendar": calendar.status(day),
               "status": status, "metrics_snapshot": metrics, "counts": counts,
               "completeness": "PARTIAL_OBSERVATION", "trades": "NOT_ENABLED"}
    suggestions = []
    if "VOLUME_NOT_VERIFIED" in status["blockers"]:
        suggestions.append("量能未验证：有效交易时段采集形成中K线及历史同进度成交量。")
    if metrics.get("disk_free_ratio", 1) < .25:
        suggestions.append("磁盘余量低于25%：核查归档和备份，保留关键审计记录。")
    if metrics["processing"].get("p95_ms",0) > 100:
        suggestions.append("内部处理P95超过100ms：核查队列等待与订阅负载。")
    if not suggestions:
        suggestions.append("当前指标没有触发优化规则；继续积累可验证样本。")
    text = existing or (f"# OBR Math 中文日报 — {key}\n\n"
        f"- 日历状态：{payload['calendar']}\n- 运行模式：{status['mode']}；真实交易关闭。\n"
        f"- 候选池：{status.get('candidate_count',0)}；重点订阅：{status.get('focus_count',0)}。\n"
        f"- 已保存K线：{counts['bars']}；信号状态计数：{counts['signals']}。\n"
        f"- 内部处理最近窗口：{metrics['processing']}。\n"
        f"- 源行情年龄（独立口径）：{metrics['source_age']}。\n"
        f"- CPU单核占比：{metrics.get('cpu_percent_one_core')}%；RSS：{str(metrics['rss_bytes'])+'字节' if metrics.get('rss_bytes') is not None else '未测得'}。\n"
        f"- 数据完整度：PARTIAL_OBSERVATION；指标为生成时最新快照，消息计数为进程启动以来，延迟为最近窗口，非全日聚合。\n"
        f"- 自动模拟交易尚未启用；不报告虚构订单、收益或退出记录。\n\n## 待处理事项\n\n"
        + "\n".join(f"- {s}" for s in suggestions[:3]) + "\n")
    if existing is None:
        store.save_report(key, now_ms, text, payload)
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory/f"{key}.md"
    temporary = target.with_suffix(".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(target)
    return text
