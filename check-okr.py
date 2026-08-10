#!/usr/bin/env python3
"""
OKR 
"""
import json, sys, os, subprocess, datetime
from urllib import request

WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "")
KDOCS_FILE_ID = "xkStXoxDi1MpLWyuVSPHrxQY7kyyPhQrv"
MINDMAP_URL = "https://www.kdocs.cn/l/cnHbEt5NdceW"
DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tracker-data.json")
STATE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "last-sent.json")
KDOCS_TOKEN = os.environ.get("KINGSOFT_DOCS_TOKEN", "")

TIME_LABELS = {"9": ("", "9:00", "14:00"), "14": ("", "14:00", "17:00"), "17": ("", "17:00", None)}
SLOT_TRIGGERS = [
    (datetime.time(8, 30), "meeting"),
    (datetime.time(9, 0), "9"),
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
    return (None, "all sent or not yet")

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
                # Only show first 500 chars of stderr
                stderr_short = r.stderr[:500]
                print(f"[DEBUG] stderr: {stderr_short}")
            if r.returncode != 0:
                print(f"[DEBUG] ERROR: kdocs-cli failed with code {r.returncode}")
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
        print(f"[DEBUG] editors: {editors}")
        return editors
    except Exception as e:
        print(f"[DEBUG] get_today_editors exception: {e}")
        return set()

def build_meeting_message():
    return """<@all>
##   OKR 

OKR OKR 

>  [](https://www.kdocs.cn/l/cnHbEt5NdceW)
"""

def build_message(slot, regions, today_editors):
    if slot == "meeting":
        return build_meeting_message()
    label, ct, nt = TIME_LABELS[slot]
    has = len(today_editors) > 0
    es = "".join(sorted(today_editors)) if has else ""
    lines = [
        "<@all>",
        f"##   OKR  {label}{ct}",
        f">  : **{es}**" if has else f">  : ** **",
        "",
    ]
    for region in regions:
        sp = region.get("sub_people", [])
        if not sp:
            continue
        ns = "".join(p["name"] for p in sp)
        lines.append(f"> **{region['name']}**  : **{region['owner']}**")
        lines.append(f"> - {ns}")
    lines.append("")
    if not has:
        lines.append(">   OKR ")
    else:
        lines.append(">   OKR ")
    if nt:
        lines.append(f">  : **{nt}**")
    else:
        lines.append(">   @ OKR ")
    lines.append(f">  []({MINDMAP_URL})")
    return "\n".join(lines)

def send_wecom(content):
    if not WEBHOOK_URL:
        raise RuntimeError("WEBHOOK_URL ")
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
        err = f"""<@all>
##  OKR 
> : {str(e)}
> @  """
        try:
            send_wecom(err)
        except:
            pass
        print(f"ERROR: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
