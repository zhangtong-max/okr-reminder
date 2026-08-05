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

TIME_LABELS = {
    "9":  ("早间提醒", "9:00",  "14:00"),
    "14": ("二次催促", "14:00", "17:00"),
    "17": ("最后通牒", "17:00", None),
}

ICONS = {
    "9":  ("📋", "🔴"),
    "14": ("⚠️", "🔴"),
    "17": ("🚨", "🔴"),
}


def load_data(path=DATA_PATH):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


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
            data = json.loads(result.stdout)
            inner = data.get("data", {}).get("data", {})
            items = inner.get("items", [])
            all_versions.extend(items)
            page_token = inner.get("next_page_token")
            if not page_token:
                break

        today = datetime.date.today()
        editors = set()
        for v in all_versions:
            mtime = v.get("mtime", 0)
            if not mtime:
                continue
            if mtime > 1_000_000_000_000:
                mtime = mtime / 1000
            if datetime.date.fromtimestamp(mtime) == today:
                name = v.get("modified_by", {}).get("name")
                if name:
                    editors.add(name)
        return editors
    except Exception as e:
        print(f"获取版本历史失败：{e}")
        return set()


def build_meeting_message():
    """周五例会提醒"""
    return """<@all>
## 📅 周六例会提醒

各位省总，明天就是周六了，请提前准备好周例会的汇报内容。

例会要记得开启「云录制」，方便未能参会的人员回看。

各位省总，收到请回复。

> 📍 [思维导图](https://www.kdocs.cn/l/cnHbEt5NdceW)
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
        f"> 📝 今日编辑者：<font color='info'>**{editor_str}**</font>",
        "",
    ]

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
    if slot not in TIME_LABELS and slot != "meeting":
        print(f"未知时段: {slot}，请使用 9/14/17/meeting")
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
        print("\n=== 发送内容 ===\n" + msg)
    except Exception as e:
        err_msg = f"""<@all>
## ⚠️ 北区OKR催办异常
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
