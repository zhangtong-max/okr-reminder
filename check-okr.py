#!/usr/bin/env python3
"""
北区 OKR 区域完成度催办脚本（GitHub Actions 云端版）
- 通过版本历史 API 判定今日思维导图是否有更新
- 消息中显示各区域子负责人名单作为提醒参考
- 实际个人完成情况由张通线下跟进
"""
import json
import sys
import os
import subprocess
import datetime
from urllib import request

WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "")
KDOCS_FILE_ID = "xkStXoxDi1MpLWyuVSPHrxQY7kyyPhQrv"
MINDMAP_URL = "https://www.kdocs.cn/l/cnHbEt5NdceW"
DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tracker-data.json")
STATE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "last-sent.json")

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

# 各时段触发时间（北京时间）及对应 slot
SLOT_TRIGGERS = [
    (datetime.time(8, 30), "meeting"),   # 周五 8:30 例会提醒
    (datetime.time(9, 0),  "9"),          # 9:00 早间
    (datetime.time(14, 0), "14"),         # 14:00 二次
    (datetime.time(17, 0), "17"),         # 17:00 最后
]


def load_data(path=DATA_PATH):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_state():
    """读取已发送状态"""
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"date": "", "sent": []}


def save_state(state):
    """保存已发送状态"""
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False)


def is_slot_sent(slot):
    """检查某个时段今天是否已发送"""
    state = load_state()
    today = datetime.date.today().isoformat()
    if state.get("date") != today:
        return False
    return slot in state.get("sent", [])


def mark_slot_sent(slot):
    """标记某个时段今天已发送"""
    state = load_state()
    today = datetime.date.today().isoformat()
    if state.get("date") != today:
        state = {"date": today, "sent": []}
    if slot not in state["sent"]:
        state["sent"].append(slot)
    save_state(state)


def beijing_now():
    """返回当前北京时间"""
    return datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))


def auto_detect_slot(now):
    """
    根据当前北京时间自动判断应该触发哪个时段。
    返回 (slot, reason) 或 (None, reason)。
    只会返回当前时间已到达但尚未发送过的时段。
    如果多个时段都已到达，优先返回最早未发送的那个。
    """
    weekday = now.weekday()  # 0=周一, 6=周日
    current_time = now.time()

    # 周末不触发
    if weekday >= 5:
        return (None, f"周末跳过（{['周一','周二','周三','周四','周五','周六','周日'][weekday]}）")

    candidates = []
    for trigger_time, slot in SLOT_TRIGGERS:
        # 周五例会提醒仅周五触发
        if slot == "meeting" and weekday != 4:
            continue
        # 非 meeting 的 slots 工作日都可以
        if current_time >= trigger_time and not is_slot_sent(slot):
            candidates.append((trigger_time, slot))

    if not candidates:
        return (None, "所有时段已发送或未到触发时间")

    # 返回最早的未发送时段
    candidates.sort()
    slot = candidates[0][1]
    return (slot, f"触发时段: {slot}（{candidates[0][0].strftime('%H:%M')}）")


def get_today_editors():
    """调用 kdocs-cli 获取今日版本历史编辑者集合（支持翻页）"""
    try:
        all_versions = []
        page_token = None
        for _ in range(5):  # 最多翻 5 页
            params = {"file_id": KDOCS_FILE_ID, "page_size": 500}
            if page_token:
                params["page_token"] = page_token
            result = subprocess.run(
                ["kdocs-cli", "drive", "list-file-versions", json.dumps(params)],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode != 0:
                print(f"[版本历史] kdocs-cli 返回非零: {result.returncode}")
                print(f"[版本历史] stderr: {result.stderr}")
            data = json.loads(result.stdout)
            inner = data.get("data", {}).get("data", {})
            items = inner.get("items", [])
            all_versions.extend(items)
            page_token = inner.get("next_page_token")
            if not page_token:
                break

        # 使用北京时间作为"今天"的判定
        beijing_today = beijing_now().date()
        editors = set()

        print(f"[版本历史] 共 {len(all_versions)} 条记录, 北京时间今天: {beijing_today}")

        # 打印最近 3 条版本用于排查
        for i, v in enumerate(all_versions[:3]):
            mtime = v.get("mtime", 0)
            if mtime > 1_000_000_000_000:
                mtime = mtime / 1000
            bj_dt = datetime.datetime.fromtimestamp(mtime, datetime.timezone(datetime.timedelta(hours=8)))
            name = v.get("modified_by", {}).get("name", "未知")
            print(f"[版本历史]  #{i+1} {bj_dt.strftime('%Y-%m-%d %H:%M:%S')} (北京) 编辑者: {name}")

        for v in all_versions:
            mtime = v.get("mtime", 0)
            if not mtime:
                continue
            if mtime > 1_000_000_000_000:
                mtime = mtime / 1000
            version_bj_date = datetime.datetime.fromtimestamp(
                mtime, datetime.timezone(datetime.timedelta(hours=8))
            ).date()
            if version_bj_date == beijing_today:
                name = v.get("modified_by", {}).get("name")
                if name:
                    editors.add(name)

        print(f"[版本历史] 今日编辑者(北京时间): {editors}")
        return editors
    except Exception as e:
        print(f"获取版本历史失败：{e}")
        return set()


def build_meeting_message():
    """周五例会提醒"""
    return """<@all>
\U0001f4c5 ## 周六例会提醒

各位省总，明天就是周六了，请提前准备好周例会的汇报内容，今天内发给张通。

例会要记得开启「云录制」，方便未能参会的人员回看。

各位省总，收到请回复。

> \U0001f4cd [思维导图](https://www.kdocs.cn/l/cnHbEt5NdceW)
"""


def build_message(slot, regions, today_editors):
    """构造企微 markdown 消息"""
    if slot == "meeting":
        return build_meeting_message()

    label, current_time, next_time = TIME_LABELS[slot]
    icon, warn_icon = ICONS[slot]

    has_update = len(today_editors) > 0
    editor_str = "、".join(sorted(today_editors)) if has_update else "无"

    lines = [
        "<@all>",
        f"## {icon} 北方区域 OKR · {label}（{current_time}）",
        f"> \U0001f4dd 今日编辑者：<font color='info'>**{editor_str}**</font>",
        "",
    ]

    lines.append("### \U0001f4cb 各区域待确认人员")
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
        lines.append("> \u2705 今日思维导图已有更新记录")

    if next_time:
        lines.append(f"> \u23f0 下次提醒：**{next_time}**")
    else:
        lines.append("> \u26a0\ufe0f 今日即将结束，请 @张通 关注未完成的区域负责人")

    lines.append(f"> \U0001f4cd [思维导图]({MINDMAP_URL})")

    return "\n".join(lines)


def send_wecom(content):
    if not WEBHOOK_URL:
        raise RuntimeError("WEBHOOK_URL 环境变量未设置")
    payload = json.dumps({
        "msgtype": "markdown",
        "markdown": {"content": content},
    }, ensure_ascii=False).encode("utf-8")
    req = request.Request(WEBHOOK_URL, data=payload, headers={"Content-Type": "application/json"}, method="POST")
    with request.urlopen(req, timeout=20) as resp:
        return resp.read().decode("utf-8")


def main():
    slot = sys.argv[1] if len(sys.argv) > 1 else "9"

    # auto 模式：自动判断时段
    if slot == "auto":
        now = beijing_now()
        print(f"当前北京时间: {now.strftime('%Y-%m-%d %H:%M:%S')} ({['周一','周二','周三','周四','周五','周六','周日'][now.weekday()]})")
        slot, reason = auto_detect_slot(now)
        print(reason)
        if not slot:
            print("无需操作，退出。")
            return

    if slot not in TIME_LABELS and slot != "meeting":
        print(f"未知时段: {slot}，请使用 9/14/17/meeting/auto")
        sys.exit(1)

    try:
        data = load_data()
        today_editors = set()
        if slot != "meeting":
            today_editors = get_today_editors()
            print(f"今日编辑者：{today_editors}")

        msg = build_message(slot, data["regions"], today_editors)
        result = send_wecom(msg)
        print(result)

        # 标记已发送
        mark_slot_sent(slot)
        print(f"\n已标记 {slot} 时段为已发送")

        print("\n=== 发送内容 ===\n" + msg)
    except Exception as e:
        err_msg = f"""<@all>
## \u26a0\ufe0f 北区OKR催办异常
> 错误：{str(e)}
> 请 @张通 检查文件配置。"""
        try:
            send_wecom(err_msg)
        except Exception:
            pass
        print(f"ERROR: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
