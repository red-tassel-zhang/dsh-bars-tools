# dsh-rhythm

给长时间对话的 agent 装一个"作息"：**什么时候开口、记得什么、什么时候不许编。**

这套东西不是角色扮演框架，是三个具体毛病的补丁：

| 毛病 | 表现 | 这里的补丁 |
|---|---|---|
| 没有时间感 | agent 只在被输入时存在；"上次说"和"刚才说"没有区别 | `clock/biorhythm_clock.py`：从熵里抽一个下次开口的时刻，交给调度器 |
| 记忆会漂 | 上下文满了要压缩，摘要一遍就失真一遍 | 四层记忆 + `tools/recall.py`：只检索原文，不生成摘要 |
| 事实边界模糊 | 没有出处时，模型会替你把空白补成一个像样的答案 | `clock/watch_documents.py` + "文件即事实"规矩 |

## 它长什么样

```
clock/
  biorhythm_clock.py   # 昼夜节律唤醒时钟：算下一次该主动说话的时刻
  watch_documents.py   # 文档哨兵：谁往 documents/ 里放了新东西
  CLOCK_PROTOCOL.md    # 调度规则：挂任务、抢话、校验、失败处理
tools/
  recall.py            # 会话存档检索：按关键词捞原文片段
  export-transcript.mjs# 把 .jsonl.zstd 会话存档导成可读 markdown
  restore.ps1          # 把存档放回 DSH 会话目录（Windows）
  archive-and-delete.ps1 # 归档后删除本机会话数据（Windows）
docs/
  architecture.md      # 组件、数据流、不变量
  memory.md            # 四层记忆与精度分级
AGENTS.example.md      # 粘进你项目 AGENTS.md 的开工清单
skills/biorhythm-clock/SKILL.md
```

## 三块拼图

### 1. 节律：不要"随时在线"，要"有自己的作息"

脚本在 `[now+0.5h, now+24h]` 里按 5 分钟网格枚举候选时刻，权重 = 昼夜节律 × 间隔倾向，22:00–07:00 权重为 0。抽中的时刻交给调度器挂成一次性任务。

```bash
python clock/biorhythm_clock.py --json          # 看下次
python clock/biorhythm_clock.py --json --regen  # 强制重抽
```

要点：**随机必须来自脚本**。手挑一个"看起来合理"的时刻，只是把人的偏好伪装成随机。

### 2. 记忆：四层，各管一件事

| 层 | 文件 | 规则 |
|---|---|---|
| 现场 | `memory/state.md` | 50 行内，整篇覆盖：在哪、刚发生什么、哪条线还开着 |
| 关系 | `memory/rapport.md` | 只追加：怎么待他，不记做过什么 |
| 事实 | `documents/` | 真有出处的才进 |
| 存档 | `memory/session/` | 只检索、不加载 |

检索：

```bash
python tools/recall.py 关键词 --window 2 --limit 3
python tools/recall.py --stats
```

### 3. 边界：文件即事实

- 触发时第 0 步先跑哨兵，`new` / `changed` 非空就先读文件再动笔。
- 日志类文件记"出处"栏，无出处不得记。
- 检索只返回原文片段，**不让脚本自动写摘要**——摘要会把"记不清"改写成"记得"。

## 快速开始

1. 把 `clock/`、`tools/`、`docs/` 复制进你的项目工作区。
2. 把 `skills/biorhythm-clock/` 装到 `~/.dsh/skills/`（或你所用 agent 的技能目录）。
3. 把 `AGENTS.example.md` 的内容粘进项目的 `AGENTS.md`。
4. 建目录：`documents/`、`memory/session/`。
5. 跑一次：

```bash
python clock/biorhythm_clock.py --json
```

拿到的 `next` 用你的调度器挂成一次性任务；之后每次触发，按 `clock/CLOCK_PROTOCOL.md` 走。

## 依赖

- Python 3.9+（只用标准库；`.zstd` 解压优先调 `zstd` 可执行文件，退路是 `zstandard` 模块）
- 支持一次性定时任务的调度器（本项目在 DeepSeek Harness 的 `schedule_*` 上验证）
- Windows 脚本需要 PowerShell 5.1+；其他平台用 bash 等价物替换

## 已知局限

- **提示词是软约束**。写了"先读文件"，模型仍可能不读。真正硬的办法只有两个：让调度器在投递时带上文件摘要，或者让写文件的一方必须被读。本套没解决。
- **调度器只投递文字**。它不会替你读文件、不会替你核对。
- **Windows 沙箱**：受限令牌下 `pwsh` 可能以 `0xC0000142` 起不来，需要放宽权限执行。这是环境问题，不是脚本问题。

## License

MIT
