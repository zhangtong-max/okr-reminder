# 北区 OKR 思维导图催办机器人

基于 GitHub Actions 定时运行，每天自动检查金山文档思维导图版本历史，并通过企业微信群机器人发送催办消息。

## 定时规则（北京时间）

| 时间 | 内容 |
|------|------|
| 工作日 9:00 | 早间提醒 |
| 工作日 14:00 | 二次催促 |
| 工作日 17:00 | 最后通牒 |
| 周五 8:30 | 周六例会提醒 |

> 周六、周日不触发。

## 配置 Secrets

进入仓库 **Settings → Secrets and variables → Actions**，添加以下两个 Secrets：

| Secret 名称 | 说明 |
|-------------|------|
| `KINGSOFT_DOCS_TOKEN` | 金山文档 `kdocs-cli` 的登录 Token |
| `WEBHOOK_URL` | 企业微信群机器人完整 Webhook 地址 |

### 如何获取 KINGSOFT_DOCS_TOKEN

在本地已登录 kdocs-cli 的电脑上执行：

```bash
~/.local/bin/kdocs-cli auth get-token
```

将返回的 Token 复制到 GitHub Secrets 中。

## 手动测试

进入仓库 **Actions → OKR Reminder → Run workflow**，选择时段后点击运行。

## 文件说明

- `.github/workflows/okr-reminder.yml`：GitHub Actions 定时任务配置
- `check-okr.py`：催办脚本主体
- `tracker-data.json`：区域及负责人数据
- `requirements.txt`：Python 依赖（当前为空，使用标准库即可）
