#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""扫描 documents/，报告自上次以来新增、改动、删除的文件。

用法：
    python watch_documents.py          # 扫描、更新索引、打印 JSON
    python watch_documents.py --peek   # 只看不动索引

输出：
    {"scanned_at": "...", "new": [...], "changed": [...], "removed": [...], "total": N}

索引文件：clock/.documents_index.json（path -> sha1 + size + mtime）
"""

import hashlib
import json
import os
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(ROOT, "documents")
INDEX = os.path.join(ROOT, "clock", ".documents_index.json")


def sha1_of(path):
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def scan():
    out = {}
    if not os.path.isdir(DOCS):
        return out
    for name in sorted(os.listdir(DOCS)):
        full = os.path.join(DOCS, name)
        if not os.path.isfile(full):
            continue
        st = os.stat(full)
        out[name] = {
            "sha1": sha1_of(full),
            "size": st.st_size,
            "mtime": int(st.st_mtime),
        }
    return out


def load_index():
    try:
        with open(INDEX, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_index(data):
    os.makedirs(os.path.dirname(INDEX), exist_ok=True)
    with open(INDEX, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def main():
    peek = "--peek" in sys.argv
    now = scan()
    old = load_index()

    new = sorted(k for k in now if k not in old)
    changed = sorted(
        k for k in now if k in old and now[k]["sha1"] != old[k].get("sha1")
    )
    removed = sorted(k for k in old if k not in now)

    result = {
        "scanned_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "documents_dir": DOCS,
        "new": new,
        "changed": changed,
        "removed": removed,
        "total": len(now),
    }

    if not peek:
        save_index(now)

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
