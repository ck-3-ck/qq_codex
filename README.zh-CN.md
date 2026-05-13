# qq_codex

这是一个在 Windows 上使用的 QQ 单聊桥接程序，用来通过 QQ 官方机器人控制本机 Codex 会话。

它的基本流程是：

```text
你的 QQ 号
  -> QQ 官方机器人单聊
  -> 本机 qq_codex 桥接程序
  -> Codex CLI / Codex Desktop 会话
  -> QQ 回复结果或审批请求
```

## 当前功能

- 只支持 QQ 官方机器人单聊，不做群聊。
- 只允许白名单里的 QQ `openid` 发送指令。
- `/codex list` 可以列出本机 Codex 会话。
- 可以通过别名、标题或短会话 ID 指定 Codex 会话：

```text
/codex 测试对话 15*15=多少？只回复结果。
/codex 019e1784 15*15=多少？只回复结果。
```

- `/codex last <prompt>` 可以继续上一次使用的会话。
- `/status <task_id>` 可以查询后台任务状态。
- `/bridge storage` 可以查看桥接程序相关存储位置和占用。
- `/codex hide <alias|short_id>` 可以从 `/codex list` 中隐藏不想看的会话。
- `/codex unhide <alias|short_id>` 可以重新显示隐藏的会话。
- 可以把 Codex Desktop 里弹出的 UI 审批同步到 QQ，并在 QQ 中回复审批结果。

## QQ 命令

```text
/help
/codex list
/codex list all
/codex <别名|标题|短ID> <你的指令>
/codex last <你的指令>
/codex hide <别名|短ID>
/codex unhide <别名|短ID>
/status <task_id>
/status ui
/bridge storage
```

旧审批命令仍然兼容：

```text
/approve <task_id>
/approve ui-...
/approve-always ui-...
/cancel <task_id>
/cancel ui-...
```

## Codex UI 审批

当 Codex Desktop 窗口里出现“是否允许执行命令”的审批框时，桥接程序会尝试通过 Windows UIAutomation 检测它，并把审批内容发到 QQ。

单个审批时，QQ 消息类似：

```text
Codex UI 审批：工程干活

需要读取 G 盘 rerun2 输出目录，核对 512 GiB baseline 数据文件。

Get-ChildItem 'G:\xxx' -Force | Select-Object Name,Length,LastWriteTime

A = 允许本次
B = 允许本次，并记住同类命令
C = 拒绝/跳过
```

这时你只需要回复：

```text
A
```

或：

```text
B
C
```

含义：

- `A`：等价于在桌面端选择“是”，只允许本次。
- `B`：等价于在桌面端选择“是，且对于同类命令不再询问”。只有桌面端本身显示这个选项时才可用。
- `C`：等价于拒绝、跳过或取消本次审批。

## 多个审批同时存在

如果第一个审批你一直没处理，又来了第二个审批，桥接程序会进入多审批模式，并给每个审批加编号。

示例：

```text
Codex UI 审批：工程干活 #1

<第一个审批内容>

A1 = 允许本次
B1 = 允许本次，并记住同类命令
C1 = 拒绝/跳过
```

```text
Codex UI 审批：英语论文 #2

<第二个审批内容>

A2 = 允许本次
B2 = 允许本次，并记住同类命令
C2 = 拒绝/跳过
```

这时必须回复带编号的选项：

```text
A1
C2
B1
```

如果有多个审批时只回复 `A`、`B` 或 `C`，桥接程序会提示你改用 `A1/B1/C1` 或 `A2/B2/C2`，避免误批。

## 安全边界

- `.env` 里保存 QQ 机器人 `AppID`、`AppSecret` 和白名单 `openid`，不要提交到 Git。
- `config/*.json` 是本机真实配置，不提交到 Git。
- `logs/*` 是运行日志，不提交到 Git。
- 生成的 `.docx`、`.pptx`、预览图片等运行产物不提交到 Git。
- 桥接程序只处理白名单 QQ 用户的消息。
- 后台命令行任务和非 UI 会话仍保留桥接程序自己的安全限制。
- 通过 Codex Desktop UI 会话执行的任务，权限以桌面端 Codex 当前会话和它弹出的审批为准。

## 本地配置

安装依赖：

```powershell
python -m pip install -r requirements.txt
```

复制配置模板：

```powershell
Copy-Item .env.example .env
Copy-Item config\sessions.example.json config\sessions.json
Copy-Item config\policy.example.json config\policy.json
```

填写 `.env`：

```text
QQ_APP_ID=
QQ_APP_SECRET=
QQ_ALLOWED_OPENIDS=

SESSIONS_FILE=config/sessions.json
POLICY_FILE=config/policy.json
CODEX_CMD=%APPDATA%\npm\codex.cmd
CODEX_TIMEOUT_SECONDS=420
```

监听一条 QQ 单聊消息，获取发送者 `openid`：

```powershell
python -m src.main --listen-openid
```

启动桥接服务：

```powershell
python -u -m src.main --serve
```

本地测试命令解析：

```powershell
python -m src.main --local "/codex list"
```

运行测试：

```powershell
python -m unittest discover -s tests
```

## 限制

- UI 审批同步依赖 Windows UIAutomation，Codex Desktop 窗口需要实际打开并能被系统检测到。
- 如果 Codex Desktop UI 结构变化，审批检测可能需要调整。
- 多审批编号只在当前桥接进程内稳定；重启桥接程序后，旧编号不会保留。
- QQ 官方机器人可能有消息频控，长输出会被桥接程序分段发送。
