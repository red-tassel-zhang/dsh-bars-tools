#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""recall.py —— 从会话存档里按关键词捞出原文片段。

只做检索，不做总结：总结会漂移，索引不会。

用法：
    python tools/recall.py 参谋
    python tools/recall.py 第三块砖 --window 3 --limit 4
    python tools/recall.py 参谋 发卡 --limit 6 --json
    python tools/recall.py --stats
    python tools/recall.py --files
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_JSONL = ROOT / "memory" / "session" / "session.v4.jsonl"
DEFAULT_ZSTD = ROOT / "memory" / "session" / "session.v4.jsonl.zstd"
TZ = timezone(timedelta(hours=8))

ZSTD_CANDIDATES = [
    shutil.which("zstd"),
    r"D:\msys64\mingw64\bin\zstd.exe",
    r"C:\Program Files\Git\usr\bin\zstd.exe",
]


def find_zstd() -> str | None:
    for c in ZSTD_CANDIDATES:
        if c and Path(c).exists():
            return c
    return None


def read_lines(path: Path) -> list[str]:
    """读 jsonl；.zstd 需外部 zstd（node 解不了多帧）。"""
    if path.suffix != ".zstd":
        return path.read_text(encoding="utf-8", errors="replace").splitlines()

    exe = find_zstd()
    if exe:
        out = subprocess.run([exe, "-dc", str(path)], capture_output=True)
        if out.returncode != 0:
            sys.exit(f"[recall] zstd 解压失败：{out.stderr.decode('utf-8', 'replace')[:200]}")
        return out.stdout.decode("utf-8", "replace").splitlines()

    try:
        import zstandard  # type: ignore
        with open(path, "rb") as f:
            return zstandard.ZstdDecompressor().stream_reader(f).read().decode("utf-8", "replace").splitlines()
    except ImportError:
        sys.exit("[recall] 找不到 zstd 可执行文件，也没有 zstandard 模块。先解压成 .jsonl 再跑。")


def text_of(msg_content) -> str:
    """把 content 数组拼成纯文本，丢掉 reasoning。"""
    if isinstance(msg_content, str):
        return msg_content
    if not isinstance(msg_content, list):
        return ""
    parts = []
    for b in msg_content:
        if not isinstance(b, dict):
            continue
        if b.get("type") == "text" and b.get("text"):
            parts.append(b["text"])
    return "\n".join(parts)


def load_events(path: Path) -> list[dict]:
    events: list[dict] = []
    for raw in read_lines(path):
        raw = raw.strip()
        if not raw:
            continue
        try:
            ev = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(ev, dict):
            continue
        data = ev.get("data") or {}
        role = None
        text = ""
        if ev.get("type") == "user/message":
            role, text = "user", text_of(data.get("content"))
        elif ev.get("type") == "assistant/message":
            msg = data.get("message") or {}
            role, text = "assistant", text_of(msg.get("content"))
        if role and text.strip():
            events.append(
                {
                    "time": ev.get("time"),
                    "role": role,
                    "text": text.strip(),
                }
            )
    return events


def ts(ms) -> str:
    try:
        return datetime.fromtimestamp(int(ms) / 1000, TZ).strftime("%m-%d %H:%M")
    except Exception:
        return "  ?  "


def is_meta(text: str) -> bool:
    """系统注入的消息：提示词快照、运行时上下文、调度通知——检索时默认跳过。"""
    head = text.lstrip()[:400]
    if head.startswith("<system-reminder>"):
        return True
    for marker in ("Current runtime context", "Time sampled while preparing",
                   "[SCHEDULE CHANGE]", "[SCHEDULE REMINDER]", "Updated instructions from"):
        if marker in head:
            return True
    return False


def snippet(text: str, kws: list[str], width: int = 160) -> str:
    """以第一个命中词为中心截一段，保证看见关键词本身。"""
    low = text.lower()
    pos = min((low.find(k) for k in kws if k in low), default=-1)
    flat = " ".join(text.split())
    if pos < 0:
        return clip(flat, width * 2)
    # 原串被压平后位置会偏，按比例近似定位再居中
    ratio = len(flat) / max(1, len(text))
    p = int(pos * ratio)
    start = max(0, p - width)
    end = min(len(flat), p + width)
    return ("…" if start > 0 else "") + flat[start:end] + ("…" if end < len(flat) else "")


def clip(s: str, n: int) -> str:
    s = " ".join(s.split())
    return s if len(s) <= n else s[: n - 1] + "…"


def main() -> None:
    ap = argparse.ArgumentParser(description="从会话存档里按关键词检索原文")
    ap.add_argument("keywords", nargs="*", help="关键词，可多个（任一命中即算，命中多的靠前）")
    ap.add_argument("--window", type=int, default=2, help="命中前后各带几条（默认 2）")
    ap.add_argument("--limit", type=int, default=5, help="最多几处命中（默认 5）")
    ap.add_argument("--max-chars", type=int, default=1800, help="输出总字数上限")
    ap.add_argument("--min-len", type=int, default=0, help="忽略短于此长度的消息")
    ap.add_argument("--source", default=None, help="存档路径（默认 memory/session/）")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    ap.add_argument("--include-meta", action="store_true", help="把系统注入的消息也算进检索")
    ap.add_argument("--stats", action="store_true", help="只看统计")
    ap.add_argument("--files", action="store_true", help="列出可用存档")
    args = ap.parse_args()

    if args.files:
        for p in (DEFAULT_JSONL, DEFAULT_ZSTD):
            print(f"{'有' if p.exists() else '无'}  {p}  {p.stat().st_size if p.exists() else '-'}")
        print(f"zstd: {find_zstd() or '未找到'}")
        return

    src = Path(args.source) if args.source else (DEFAULT_JSONL if DEFAULT_JSONL.exists() else DEFAULT_ZSTD)
    if not src.exists():
        sys.exit(f"[recall] 没有存档：{src}")
    events = load_events(src)
    if not events:
        sys.exit("[recall] 存档里没解出消息")

    meta_count = sum(1 for e in events if is_meta(e["text"]))
    if not args.include_meta:
        events = [e for e in events if not is_meta(e["text"])]

    if args.stats:
        users = sum(1 for e in events if e["role"] == "user")
        print(json.dumps({"source": str(src), "events": len(events), "user": users,
                          "assistant": len(events) - users, "meta_skipped": meta_count,
                          "first": ts(events[0]["time"]), "last": ts(events[-1]["time"])},
                         ensure_ascii=False, indent=2))
        return

    kws = [k.lower() for k in args.keywords if k.strip()]
    if not kws:
        ap.error("给一个关键词，或 --stats / --files")

    scored = []
    for i, ev in enumerate(events):
        if len(ev["text"]) < args.min_len:
            continue
        low = ev["text"].lower()
        hits = sum(1 for k in kws if k in low)
        if hits:
            scored.append((hits, i))
    scored.sort(key=lambda x: (-x[0], len(events[x[1]]["text"])))

    picked: list[int] = []
    for _, i in scored:
        if any(abs(i - j) <= args.window for j in picked):
            continue
        picked.append(i)
        if len(picked) >= args.limit:
            break

    if not picked:
        print(f"没找到：{' / '.join(args.keywords)}")
        print(f"（存档 {len(events)} 条消息，{ts(events[0]['time'])} — {ts(events[-1]['time'])}）")
        return

    blocks = []
    budget = args.max_chars
    for center in sorted(picked):
        lo, hi = max(0, center - args.window), min(len(events) - 1, center + args.window)
        lines = []
        for i in range(lo, hi + 1):
            ev = events[i]
            mark = "▶" if i == center else " "
            who = "用户" if ev["role"] == "user" else "助手"
            body = snippet(ev["text"], kws, 150)
            lines.append(f"{mark} {ts(ev['time'])} {who}：{body}")
        block = "\n".join(lines)
        if budget - len(block) <= 0 and blocks:
            blocks.append("……（已到字数上限，用 --limit / --max-chars 调整）")
            break
        blocks.append(block)
        budget -= len(block)

    out = "\n\n".join(blocks)
    if args.json:
        print(json.dumps({"source": str(src), "hits": len(picked), "text": out}, ensure_ascii=False, indent=2))
    else:
        print(out)


if __name__ == "__main__":
    main()
