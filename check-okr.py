#!/usr/bin/env python3
"""
北区 OKR 区域完成度催办脚本（GitHub Actions 云端版）
"""
import json, sys, os, subprocess, datetime
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
    "17": ("最后通牒", "17:00", None),
}

ICONS = {
    "9":  ("\U0001f4cb", "\U0001f534"),
    "14": ("\u26a0\ufe0f", "\U0001f534"),
    "17": ("\U0001f6a8", "\U0001f534"),
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
        s = {"date": today, "sent": []}
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
            return (sl, f"trigger: {sl}")
    return (None, "all_sent")


def get_today_editors():
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
                print(f"[DEBUG] stderr first 500: {r.stderr[:500]}")
            if r.returncode != 0:
                print(f"[DEBUG] kdocs-cli FAILED with code {r.returncode}")
                break
            data = json.loads(r.stdout)
            inner = data.get("data", {}).get("data", {})
            items = inner.get("items", [])
            print(f"[DEBUG] page items: {len(items)}")
            all_versions.extend(items)
            pt = inner.get("next_page_token")
            if not pt:
                break
        today = bj_now().date()
        print(f"[DEBUG] total versions: {len(all_versions)}, today(Beijing): {today}")
        editors = set()
        for v in all_versions:
            mt = v.get("mtime", 0)
            if not mt:
                continue
            if mt > 1e12:
                mt /= 1000
            if datetime.datetime.fromtimestamp(mt, BJT).date() == today:
                nm = v.get("modified_by", {}).get("name")
                if nm:
                    editors.add(nm)
        print(f"[DEBUG] editors found: {editors}")
        return editors
    except Exception as e:
        print(f"[DEBUG] get_today_editors EXCEPTION: {e}")
        import traceback
        traceback.print_exc()
        return set()


def build_meeting_message():
    return """<@all>
## \U0001f4c5 \u5468\u516d\u4f8b\u4f1a\u63d0\u9192

\u5404\u4f4d\u7701\u603b\uff0c\u660e\u5929\u5c31\u662f\u5468\u516d\u4e86\uff0c\u8bf7\u63d0\u524d\u51c6\u5907\u597d\u5468\u4f8b\u4f1a\u7684\u6c47\u62a5\u5185\u5bb9\uff0c\u4eca\u5929\u5185\u53d1\u7ed9\u5f20\u901a\u3002

\u4f8b\u4f1a\u8981\u8bb0\u5f97\u5f00\u542f\u300c\u4e91\u5f55\u5236\u300d\uff0c\u65b9\u4fbf\u672a\u80fd\u53c2\u4f1a\u7684\u4eba\u5458\u56de\u770b\u3002

\u5404\u4f4d\u7701\u603b\uff0c\u6536\u5230\u8bf7\u56de\u590d\u3002

> \U0001f4cd [\u601d\u7ef4\u5bfc\u56fe](https://www.kdocs.cn/l/cnHbEt5NdceW)
"""


def build_message(slot, regions, today_editors):
    if slot == "meeting":
        return build_meeting_message()
    label, current_time, next_time = TIME_LABELS[slot]
    icon, warn_icon = ICONS[slot]
    has_update = len(today_editors) > 0
    editor_str = "\u3001".join(sorted(today_editors)) if has_update else "\u65e0"
    lines = [
        "<@all>",
        f"## {icon} \u5317\u65b9\u533a\u57df OKR \u00b7 {label}\uff08{current_time}\uff09",
        f"> \U0001f4dd \u4eca\u65e5\u7f16\u8f91\u8005\uff1a<font color='info'>**{editor_str}**</font>",
        "",
    ]
    lines.append("### \U0001f4cb \u5404\u533a\u57df\u5f85\u786e\u8ba4\u4eba\u5458")
    for region in regions:
        sub_people = region.get("sub_people", [])
        if not sub_people:
            continue
        names = "\u3001".join(p["name"] for p in sub_people)
        lines.append(f"> **{region['name']}** \u2014 \u7701\u603b\uff1a<font color=\"warning\">**{region['owner']}**</font>")
        lines.append(f"> - {names}")
    lines.append("")
    if not has_update:
        lines.append(f"> {warn_icon} \u4eca\u65e5\u601d\u7ef4\u5bfc\u56fe\u6682\u65e0\u66f4\u65b0\u8bb0\u5f55\uff0c\u8bf7\u5404\u4f4d\u5c3d\u5feb\u66f4\u65b0")
    else:
        lines.append("> \u2705 \u4eca\u65e5\u601d\u7ef4\u5bfc\u56fe\u5df2\u6709\u66f4\u65b0\u8bb0\u5f55")
    if next_time:
        lines.append(f"> \u23f0 \u4e0b\u6b21\u63d0\u9192\uff1a**{next_time}**")
    else:
        lines.append("> \u26a0\ufe0f \u4eca\u65e5\u5373\u5c06\u7ed3\u675f\uff0c\u8bf7 @\u5f20\u901a \u5173\u6ce8\u672a\u5b8c\u6210\u7684\u533a\u57df\u8d1f\u8d23\u4eba")
    lines.append(f"> \U0001f4cd [\u601d\u7ef4\u5bfc\u56fe]({MINDMAP_URL})")
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
        msg = build_message(slot, data["regions"], eds)
        result = send_wecom(msg)
        print(result)
        mark_slot_sent(slot)
        print(f"Marked {slot}")
        print("\n=== Message ===\n" + msg)
    except Exception as e:
        err_msg = f"""<@all>
## \u26a0\ufe0f OKR\u50ac\u529e\u5f02\u5e38
> \u9519\u8bef\uff1a{str(e)}
> \u8bf7 @\u5f20\u901a \u68c0\u67e5\u914d\u7f6e\u3002"""
        try:
            send_wecom(err_msg)
        except:
            pass
        print(f"ERROR: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
