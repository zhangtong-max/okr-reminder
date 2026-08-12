#!/usr/bin/env python3
"""
北区 OKR 区域完成度催办脚本（GitHub Actions 云端版）
"""
import json, sys, os, subprocess, datetime, traceback
from urllib import request

WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "")
KDOCS_FILE_ID = "xkStXoxDi1MpLWyuVSPHrxQY7kyyPhQrv"
MINDMAP_URL = "https://www.kdocs.cn/l/cnHbEt5NdceW"
DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tracker-data.json")
STATE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "last-sent.json")
KDOCS_TOKEN = os.environ.get("KINGSOFT_DOCS_TOKEN", "")

TIME_LABELS = {
    "9":  ("早间提醒", "9:00",  "14:00"),
    "14": ("二次催促", "14:00", "17:00"),
    "17": ("收尾提醒", "17:00", None),
}

ICONS = {
    "9":  ("📋", "🔴"),
    "14": ("⚠️", "🔴"),
    "17": ("🚨", "🔴"),
}

SLOT_TRIGGERS = [
    (datetime.time(8, 30), "meeting"),
    (datetime.time(9, 0),  "9"),
    (datetime.time(14, 0), "14"),
    (datetime.time(17, 0), "17"),
]

BJT = datetime.timezone(datetime.timedelta(hours=8))


def bj_now():
    return datetime.datetime.now(BJT)


def load_data(path=DATA_PATH):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_state():
    try:
        with open(STATE_PATH, "r") as f:
            return json.load(f)
    except:
        return {"date": "", "sent": []}


def save_state(state):
    with open(STATE_PATH, "w") as f:
        json.dump(state, f, ensure_ascii=False, default=str)


def is_slot_sent(slot):
    s = load_state()
    return s.get("date") == bj_now().strftime("%Y-%m-%d") and slot in s.get("sent", [])


def mark_slot_sent(slot):
    s = load_state()
    today = bj_now().strftime("%Y-%m-%d")
    if s.get("date") != today:
        # 日期切换时保留昨日编辑记录，否则第二天9:00读不到
        old_editors = s.get("daily_editors", {})
        yesterday = (bj_now() - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
        s = {"date": today, "sent": []}
        if yesterday in old_editors:
            s["daily_editors"] = {yesterday: old_editors[yesterday]}
    if slot not in s["sent"]:
        s["sent"].append(slot)
    save_state(s)


def auto_detect_slot(now):
    wd = now.weekday()
    if wd >= 5:
        return (None, "weekend")
    ct = now.time()
    for tt, sl in SLOT_TRIGGERS:
        if sl == "meeting" and wd != 4:
            continue
        if ct >= tt and not is_slot_sent(sl):
            # 超过1小时不补发（防止cron恢复后发送过期提醒）
            delta_mins = (ct.hour * 60 + ct.minute) - (tt.hour * 60 + tt.minute)
            if delta_mins > 60:
                continue
            return (sl, f"trigger: {sl}")
    return (None, "all_sent")


def get_today_editors():
    """调用 kdocs-cli 获取今日版本历史编辑者集合。关键：必须传 --token！"""
    try:
        all_versions = []
        pt = None
        for _ in range(5):
            params = {"file_id": KDOCS_FILE_ID, "page_size": 500}
            if pt:
                params["page_token"] = pt
            cmd = ["kdocs-cli"]
            if KDOCS_TOKEN:
                cmd.extend(["--token", KDOCS_TOKEN])
            cmd.extend(["drive", "list-file-versions", json.dumps(params)])
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            print(f"[DEBUG] kdocs-cli exit={r.returncode} stdout_len={len(r.stdout)} stderr_len={len(r.stderr)}")
            if r.stderr:
                print(f"[DEBUG] stderr: {r.stderr[:500]}")
            if r.returncode != 0:
                print(f"[DEBUG] kdocs-cli FAILED code={r.returncode}")
                break
            data = json.loads(r.stdout)
            code = data.get("code", "N/A")
            inner = data.get("data", {}).get("data", {})
            inner_code = inner.get("code", "N/A")
            items = inner.get("items", [])
            print(f"[DEBUG] code={code} inner_code={inner_code} items={len(items)}")
            all_versions.extend(items)
            pt = inner.get("next_page_token")
            if not pt:
                break
        today = bj_now().date()
        print(f"[DEBUG] total_versions={len(all_versions)} today(Beijing)={today}")
        # 打印所有版本中的唯一编辑者（不限日期）
        all_editors = set()
        for v in all_versions:
            nm = v.get("modified_by", {}).get("name")
            if nm:
                all_editors.add(nm)
        print(f"[DEBUG] ALL unique editors across all versions: {all_editors}")
        # 打印第一个版本项的完整结构
        if all_versions:
            print(f"[DEBUG] first version item keys: {list(all_versions[0].keys())}")
            print(f"[DEBUG] first version item: {json.dumps(all_versions[0], ensure_ascii=False)[:800]}")
        editors = set()
        matched_times = []
        for v in all_versions:
            mt = v.get("mtime", 0)
            if not mt:
                continue
            if mt > 1e12:
                mt /= 1000
            vdate = datetime.datetime.fromtimestamp(mt, BJT).date()
            if vdate == today:
                nm = v.get("modified_by", {}).get("name")
                if nm:
                    editors.add(nm)
                    matched_times.append(datetime.datetime.fromtimestamp(mt, BJT).strftime("%H:%M"))
        print(f"[DEBUG] editors_found={editors}")
        print(f"[DEBUG] matched_times={matched_times[:20]}")
        return editors
    except Exception as e:
        print(f"[DEBUG] EXCEPTION: {e}")
        traceback.print_exc()
        return set()


def save_daily_editors(editors):
    """将今日编辑者追加到状态中（取并集）"""
    s = load_state()
    today = bj_now().strftime("%Y-%m-%d")
    if "daily_editors" not in s:
        s["daily_editors"] = {}
    existing = set(s["daily_editors"].get(today, []))
    existing.update(editors)
    s["daily_editors"][today] = sorted(existing)
    save_state(s)


def get_yesterday_editors():
    """获取昨日的编辑者名单"""
    s = load_state()
    yesterday = (bj_now() - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    return s.get("daily_editors", {}).get(yesterday, [])


def build_meeting_message():
    return """<@all>
## 📅 周六例会提醒

各位省总，明天就是周六了，请提前准备好周例会的汇报内容，今天内发给张通。

例会要记得开启「云录制」，方便未能参会的人员回看。

各位省总，收到请回复。

> 📍 [思维导图](https://www.kdocs.cn/l/cnHbEt5NdceW)
"""


def build_message(slot, regions, today_editors):
    if slot == "meeting":
        return build_meeting_message()
    label, current_time, next_time = TIME_LABELS[slot]
    icon, warn_icon = ICONS[slot]
    has_update = len(today_editors) > 0
    editor_str = "、".join(sorted(today_editors)) if has_update else "无"
    lines = [
        "<@all>",
        f"## {icon} 北方区域 OKR · {label}（{current_time}）",
        f"> 📝 今日编辑者：<font color='info'>**{editor_str}**</font>",
    ]
    # 早间提醒附加昨日编辑者
    if slot == "9":
        yed = get_yesterday_editors()
        if yed:
            lines.append(f"> 📅 昨日编辑者：<font color='comment'>**{'、'.join(yed)}**</font>")
        else:
            lines.append("> 📅 昨日无编辑记录")
    lines.append("")
    lines.append("### 📋 各区域待确认人员")
    for region in regions:
        sub_people = region.get("sub_people", [])
        if not sub_people:
            continue
        names = "、".join(p["name"] for p in sub_people)
        lines.append(f"> **{region['name']}** — 省总：<font color=\"warning\">**{region['owner']}**</font>")
        lines.append(f"> - {names}")
    lines.append("")
    if not has_update:
        lines.append(f"> {warn_icon} 今日思维导图暂无更新记录，请各位尽快更新")
    else:
        lines.append("> ✅ 今日思维导图已有更新记录")
    if next_time:
        lines.append(f"> ⏰ 下次提醒：**{next_time}**")
    else:
        lines.append("> ⚠️ 今日即将结束，请 @张通 关注未完成的区域负责人")
    lines.append(f"> 📍 [思维导图]({MINDMAP_URL})")
    return "\n".join(lines)


def send_wecom(content):
    if not WEBHOOK_URL:
        raise RuntimeError("WEBHOOK_URL not set")
    payload = json.dumps({"msgtype": "markdown", "markdown": {"content": content}}, ensure_ascii=False).encode("utf-8")
    req = request.Request(WEBHOOK_URL, data=payload, headers={"Content-Type": "application/json"}, method="POST")
    with request.urlopen(req, timeout=20) as resp:
        return resp.read().decode("utf-8")


def main():
    slot = sys.argv[1] if len(sys.argv) > 1 else "9"
    if slot == "auto":
        now = bj_now()
        print(f"Beijing: {now}")
        slot, reason = auto_detect_slot(now)
        print(reason)
        if not slot:
            print("No action.")
            return
    if slot not in TIME_LABELS and slot != "meeting":
        print(f"Unknown slot: {slot}")
        sys.exit(1)
    try:
        data = load_data()
        eds = set()
        if slot != "meeting":
            eds = get_today_editors()
            print(f"Editors: {eds}")
            if eds:
                save_daily_editors(eds)
        msg = build_message(slot, data["regions"], eds)
        result = send_wecom(msg)
        print(result)
        mark_slot_sent(slot)
        print(f"Marked {slot}")
        print("\n=== Message ===\n" + msg)
    except Exception as e:
        err_msg = f"""<@all>
## ⚠️ OKR催办异常
> 错误：{str(e)}
> 请 @张通 检查配置。"""
        try:
            send_wecom(err_msg)
        except:
            pass
        print(f"ERROR: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
