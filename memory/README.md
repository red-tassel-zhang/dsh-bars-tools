# memory/

四层记忆里的三层在这里（事实层是 `documents/`）。

| 文件 | 作用 | 更新方式 |
|---|---|---|
| `state.md` | 现状卡：在哪、刚发生什么、哪条线还开着 | 整篇覆盖，50 行内 |
| `rapport.md` | 对方这个人、怎么待他 | 只追加 |
| `session/` | 原始会话存档（`.jsonl.zstd`） | 运行时写，只检索 |
| `transcript.md` | 存档的可读版，给人和检索用 | 由导出脚本生成 |

第一次用，自己建这两个文件：

```bash
touch memory/state.md memory/rapport.md
```

`state.md` 起手可以就三行：

```markdown
- 更新：YYYY-MM-DD HH:MM
- 时地：
- 下次接：
```

不写就不写，别拿空模板当记忆。
