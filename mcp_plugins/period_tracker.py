"""
MCP 插件: 生理期记录
记录生理期开始/结束，自动计算周期，预测下次日期
"""
import os
import json
import logging
import uuid
from datetime import datetime, timedelta, date
from core.tool_base import MCPlugin, ToolResult

logger = logging.getLogger(__name__)

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "memory")
DATA_FILE = os.path.join(DATA_DIR, "period_data.json")
os.makedirs(DATA_DIR, exist_ok=True)

BODY_EVENT_LABELS = {"headache": "头痛", "nausea": "恶心"}
MOOD_EVENT_LABELS = {"happy": "开心", "unhappy": "不开心"}


def _empty_data():
    return {
        "records": [],
        "current": None,
        "body_events": [],
        "mood_events": [],
    }


def _normalize_data(data):
    if not isinstance(data, dict):
        data = {}
    data.setdefault("records", [])
    data.setdefault("current", None)
    data.setdefault("body_events", [])
    data.setdefault("mood_events", [])
    return data


def _now_str():
    return datetime.now().astimezone().isoformat(timespec="seconds")

def _load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return _normalize_data(json.load(f))
        except (json.JSONDecodeError, Exception) as e:
            logger.warning(f"⚠️ period_data.json 损坏，尝试修复: {e}")
            bak = DATA_FILE + ".bak"
            try:
                import shutil
                shutil.copy2(DATA_FILE, bak)
                logger.info(f"📋 已备份损坏文件到 {bak}")
            except Exception:
                pass
            return _empty_data()
    return _empty_data()

def _save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(_normalize_data(data), f, ensure_ascii=False, indent=2)

def _today_str():
    return date.today().isoformat()


def _require_event_kind(kind, allowed, label):
    if kind not in allowed:
        choices = " / ".join(allowed)
        raise ValueError(f"未知{label}类型，支持：{choices}")
    return kind


def _active_body_event(data, kind):
    return next(
        (
            event
            for event in reversed(data.get("body_events", []))
            if event.get("kind") == kind and not event.get("end_at")
        ),
        None,
    )


def _start_body_event(data, kind, occurred_at=None):
    kind = _require_event_kind(kind, BODY_EVENT_LABELS, "身体")
    active = _active_body_event(data, kind)
    if active:
        return active, False
    event = {
        "id": str(uuid.uuid4()),
        "kind": kind,
        "start_at": occurred_at or _now_str(),
        "end_at": None,
    }
    data["body_events"].append(event)
    return event, True


def _end_body_event(data, kind, occurred_at=None):
    kind = _require_event_kind(kind, BODY_EVENT_LABELS, "身体")
    active = _active_body_event(data, kind)
    if active is None:
        return None, False
    active["end_at"] = occurred_at or _now_str()
    return active, True


def _toggle_body_event(data, kind, occurred_at=None):
    if _active_body_event(data, kind):
        event, changed = _end_body_event(data, kind, occurred_at)
        return event, "ended", changed
    event, changed = _start_body_event(data, kind, occurred_at)
    return event, "started", changed


def _record_mood_event(data, kind, occurred_at=None):
    kind = _require_event_kind(kind, MOOD_EVENT_LABELS, "心情")
    event = {
        "id": str(uuid.uuid4()),
        "kind": kind,
        "occurred_at": occurred_at or _now_str(),
    }
    data["mood_events"].append(event)
    return event


def _wellbeing_snapshot(data, limit=20):
    data = _normalize_data(data)
    body = {}
    for kind, label in BODY_EVENT_LABELS.items():
        active = _active_body_event(data, kind)
        body[kind] = {
            "label": label,
            "active": active is not None,
            "started_at": active.get("start_at") if active else None,
        }
    body_events = [
        {**event, "label": BODY_EVENT_LABELS.get(event.get("kind"), event.get("kind", ""))}
        for event in data["body_events"][-limit:][::-1]
    ]
    mood_events = [
        {**event, "label": MOOD_EVENT_LABELS.get(event.get("kind"), event.get("kind", ""))}
        for event in data["mood_events"][-limit:][::-1]
    ]
    return {"body": body, "body_events": body_events, "mood_events": mood_events}

class PeriodTrackerPlugin(MCPlugin):
    @property
    def name(self) -> str:
        return "period_tracker"

    @property
    def description(self) -> str:
        return "生理期与身体心情记录工具：经期、头痛/恶心区间、开心/不开心瞬时事件"

    @property
    def parameters(self) -> dict:
        return {
            "action": {
                "type": "string",
                "description": "操作：start/end/status/history/backfill；body_start/body_end/body_toggle；mood；wellbeing_status",
                "enum": ["start", "end", "status", "history", "backfill", "body_start", "body_end", "body_toggle", "mood", "wellbeing_status"],
            },
            "start_date": {
                "type": "string",
                "description": "补录时的开始日期 YYYY-MM-DD",
            },
            "end_date": {
                "type": "string",
                "description": "补录时的结束日期 YYYY-MM-DD",
            },
            "event_type": {
                "type": "string",
                "description": "身体：headache/nausea；心情：happy/unhappy",
                "enum": ["headache", "nausea", "happy", "unhappy"],
            },
        }

    def execute(self, action="status", start_date="", end_date="", event_type="") -> ToolResult:
        data = _load_data()
        today = _today_str()
        records = data.get("records", [])
        current = data.get("current")

        if action in {"body_start", "body_end", "body_toggle"}:
            try:
                _require_event_kind(event_type, BODY_EVENT_LABELS, "身体")
            except ValueError as exc:
                return ToolResult.fail(str(exc), operation="write")
            if action == "body_start":
                event, changed = _start_body_event(data, event_type)
                state = "started"
            elif action == "body_end":
                event, changed = _end_body_event(data, event_type)
                state = "ended"
            else:
                event, state, changed = _toggle_body_event(data, event_type)
            label = BODY_EVENT_LABELS[event_type]
            if changed:
                _save_data(data)
                verb = "开始" if state == "started" else "结束"
                when = event["start_at"] if state == "started" else event["end_at"]
                return ToolResult.success(
                    f"🫧 已记录：{label}{verb}于 {when}",
                    operation="write", path="memory/period_data.json"
                )
            if event:
                return ToolResult.success(
                    f"🫧 {label}已经在记录中（开始于 {event['start_at']}）",
                    operation="read", path="memory/period_data.json"
                )
            return ToolResult.success(
                f"🫧 当前没有进行中的{label}记录。",
                operation="read", path="memory/period_data.json"
            )

        if action == "mood":
            try:
                event = _record_mood_event(data, event_type)
            except ValueError as exc:
                return ToolResult.fail(str(exc), operation="write")
            _save_data(data)
            return ToolResult.success(
                f"💭 已记录：{MOOD_EVENT_LABELS[event_type]} · {event['occurred_at']}",
                operation="write", path="memory/period_data.json"
            )

        if action == "wellbeing_status":
            snapshot = _wellbeing_snapshot(data)
            active = [item["label"] for item in snapshot["body"].values() if item["active"]]
            active_text = "、".join(active) if active else "无"
            latest_mood = snapshot["mood_events"][0] if snapshot["mood_events"] else None
            mood_text = f"{latest_mood['label']}（{latest_mood['occurred_at']}）" if latest_mood else "暂无"
            return ToolResult.success(
                f"🫧 当前身体记录：{active_text}\n💭 最近心情：{mood_text}",
                operation="read", path="memory/period_data.json"
            )

        if action == "start":
            if current:
                start = current["start"]
                diff = (date.today() - date.fromisoformat(start)).days + 1
                return ToolResult.success(
                    f"📅 你已经在经期中了哦（从 {start} 开始，今天是第 {diff} 天），不需要重复记录～",
                    operation="write", path="memory/period_data.json"
                )
            last_note = ""
            if records:
                last = records[-1]
                gap = (date.today() - date.fromisoformat(last["start"])).days
                last_note = f"距离上次开始（{last['start']}）已过 {gap} 天。"
            data["current"] = {"start": today}
            _save_data(data)
            return ToolResult.success(
                f"📝 已记录：生理期开始于 {today}。{last_note}记得注意保暖、多喝热水哦 💛",
                operation="write", path="memory/period_data.json"
            )

        elif action == "end":
            if not current:
                return ToolResult.success(
                    "📅 当前没有进行中的生理期记录，不需要结束哦。如果是忘了记开始，请用「补录」功能。",
                    operation="read", path="memory/period_data.json"
                )
            start = current["start"]
            s = date.fromisoformat(start)
            e = date.today()
            duration = (e - s).days + 1
            cycle_info = ""
            if records:
                last_start = date.fromisoformat(records[-1]["start"])
                cycle = (s - last_start).days
                cycle_info = f"周期天数：{cycle} 天。"
                current["cycle"] = cycle
            data["records"].append({
                "start": start, "end": today,
                "duration": duration, "cycle": current.get("cycle", 0),
            })
            next_date = self._predict_next(data["records"])
            data["current"] = None
            _save_data(data)
            return ToolResult.success(
                f"📝 已记录：生理期结束于 {today}。\n经期天数：{duration} 天。{cycle_info}\n📊 预测下次：大约 {next_date}。小禾辛苦啦～🥰",
                operation="write", path="memory/period_data.json"
            )

        elif action == "status":
            if current:
                start = current["start"]
                diff = (date.today() - date.fromisoformat(start)).days + 1
                rs = f"📅 当前经期中（从 {start} 开始，今天第 {diff} 天）"
                if diff > 10:
                    rs += "\n⚠️ 已经超过 10 天了，注意身体哦！"
                return ToolResult.success(rs, operation="read", path="memory/period_data.json")
            if records:
                last = records[-1]
                last_end = date.fromisoformat(last["end"])
                passed = (date.today() - last_end).days
                next_date = self._predict_next(records)
                next_d = date.fromisoformat(next_date)
                remain = (next_d - date.today()).days
                status = f"📅 非经期\n上次结束：{last['end']}（已过 {passed} 天）\n"
                if remain > 0:
                    status += f"🔮 预测下次：{next_date}（还有 {remain} 天）"
                else:
                    status += f"🔮 预测下次：{next_date}（已过预测日，可能快来了哦）"
                return ToolResult.success(status, operation="read", path="memory/period_data.json")
            return ToolResult.success("📅 暂无生理期记录。可以用「我来了」开始记录～", operation="read", path="memory/period_data.json")

        elif action == "history":
            if not records:
                return ToolResult.success("📅 暂无生理期历史记录。", operation="read", path="memory/period_data.json")
            lines = [f"📋 最近 {min(6, len(records))} 次记录："]
            for r in records[-6:]:
                cycle_str = f"周期 {r['cycle']} 天" if r.get("cycle") else "周期 ?"
                lines.append(f"  {r['start']} → {r['end']}（{r['duration']} 天, {cycle_str}）")
            if len(records) >= 2:
                cycles = [r["cycle"] for r in records[-6:] if r.get("cycle") and 15 <= r["cycle"] <= 60]
                durations = [r["duration"] for r in records[-6:]]
                if cycles:
                    avg_c = sum(cycles) // len(cycles)
                    lines.append(f"📊 平均周期：{avg_c} 天")
                if durations:
                    avg_d = sum(durations) // len(durations)
                    lines.append(f"📊 平均经期：{avg_d} 天")
                lines.append(f"🔮 预测下次：{self._predict_next(records)}")
            return ToolResult.success("\n".join(lines), operation="read", path="memory/period_data.json")

        elif action == "backfill":
            if not start_date or not end_date:
                return ToolResult.fail("补录需要提供开始和结束日期，格式：/补录 YYYY-MM-DD YYYY-MM-DD", operation="write")
            try:
                s = date.fromisoformat(start_date)
                e = date.fromisoformat(end_date)
            except ValueError:
                return ToolResult.fail("日期格式错误，请用 YYYY-MM-DD 格式", operation="write")
            if e <= s:
                return ToolResult.fail("结束日期必须晚于开始日期", operation="write")
            for r in records:
                rs = date.fromisoformat(r["start"])
                re = date.fromisoformat(r["end"])
                if not (e < rs or s > re):
                    return ToolResult.fail(f"日期范围与已有记录重叠（{r['start']} → {r['end']}）", operation="write")
            if current:
                cs = date.fromisoformat(current["start"])
                if not (e < cs or s > date.today()):
                    return ToolResult.fail(f"日期范围与当前进行中的经期重叠（{current['start']} → 至今）", operation="write")
            duration = (e - s).days + 1
            new_record = {"start": start_date, "end": end_date, "duration": duration, "cycle": 0}
            records.append(new_record)
            records.sort(key=lambda x: x["start"])
            for i, r in enumerate(records):
                if i > 0:
                    prev_start = date.fromisoformat(records[i-1]["start"])
                    this_start = date.fromisoformat(r["start"])
                    r["cycle"] = (this_start - prev_start).days
            data["records"] = records
            _save_data(data)
            return ToolResult.success(
                f"📝 已补录：{start_date} → {end_date}（{duration} 天）✅",
                operation="write", path="memory/period_data.json"
            )

        return ToolResult.fail("未知操作，支持经期、身体、心情与 wellbeing_status 记录", operation="error")

    def _predict_next(self, records):
        if not records:
            return (date.today() + timedelta(days=28)).isoformat()
        cycles = [r["cycle"] for r in records[-6:] if r.get("cycle") and 15 <= r["cycle"] <= 60]
        if cycles:
            avg_cycle = sum(cycles[-3:]) // len(cycles[-3:])
        else:
            avg_cycle = 28
        last_start = date.fromisoformat(records[-1]["start"])
        return (last_start + timedelta(days=avg_cycle)).isoformat()
