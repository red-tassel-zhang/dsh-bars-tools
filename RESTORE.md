# 带走这段对话

目标：换一台机器，clone 仓库、装好技能、把会话文件放回 DSH 的目录，打开就能接着聊。

## 存档是什么

DSH 把会话写成 `session.v4.jsonl.zstd`，放在

```
%DSH_HOME%\sessions\<slug>\<session-id>\
```

`slug` 由工作区路径算出：`"--" + 路径（把 ":\" 和 "\" 换成 "-"）+ "--"`。

例：`C:\work\my-project` → `--C-work-my-project--`。

## 恢复四步

1. **clone 到同一个路径**（路径不同则用 `-WorkspacePath` 指定）。
2. **装技能**：把 `skills/biorhythm-clock/` 复制到 `%DSH_HOME%\skills\`。
3. **放回存档**：

```powershell
powershell -ExecutionPolicy Bypass -File tools\restore.ps1 -SessionId session-xxxxxxxx
```

脚本会算好 slug、建目录、复制存档；加 `-Skill skills\biorhythm-clock\SKILL.md` 可一并装技能。

4. **打开**：DSH 里打开该工作区，会话列表里应出现这段对话。定时任务不会自动恢复，进去后手动重挂。

## 存档在仓库里放哪

```
memory/session/session.v4.jsonl.zstd   # 原始事件日志，DSH 认这个
memory/transcript.md                   # 可读版，给人看、给检索用
```

可读版由 `tools/export-transcript.mjs` 生成：

```bash
node tools/export-transcript.mjs memory/session/session.v4.jsonl.zstd memory/session/transcript.md
```

## 归档后删除本机数据

```powershell
powershell -ExecutionPolicy Bypass -File tools\archive-and-delete.ps1 -SessionId session-xxxxxxxx
powershell -ExecutionPolicy Bypass -File tools\archive-and-delete.ps1 -SessionId session-xxxxxxxx -Execute
```

第一条只预演。脚本会先确认工作区干净、HEAD 已推远端，默认打一个 zip 到桌面。

## 恢复不了怎么办

用 `memory/transcript.md` + `memory/state.md` + `documents/` 手工接续：读一遍现状卡和最后几十条对话，把时钟重挂上。会话 id 对不上不影响继续聊，只影响"历史消息还能不能翻"。

## 注意

- 存档里包含完整对话（含系统提示词），发到公开仓库前务必确认是否可以公开。
- `*.jsonl`（解压后的中间文件）不要提交，`.gitignore` 已排除。
