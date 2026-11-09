#!/usr/bin/env node
// 把 DSH 会话日志（session.v4.jsonl.zstd / .jsonl）导出成可读的 markdown。
// 用法： node tools/export-transcript.mjs <输入文件> <输出文件>

import { readFileSync, writeFileSync } from "node:fs";
import { zstdDecompressSync } from "node:zlib";
import { execFileSync } from "node:child_process";

const [, , input, output] = process.argv;
if (!input || !output) {
  console.error("usage: node tools/export-transcript.mjs <session.v4.jsonl[.zstd]> <out.md>");
  process.exit(1);
}

function readSession(file) {
  const raw = readFileSync(file);
  if (!file.endsWith(".zstd") && !file.endsWith(".zst")) return raw.toString("utf8");
  // DSH 的存档是多帧 zstd，node 内置解压只认第一帧，优先用系统 zstd。
  try {
    return execFileSync("zstd", ["-d", "-c", file], { maxBuffer: 256 * 1024 * 1024 }).toString("utf8");
  } catch {
    console.warn("[warn] 未找到 zstd，退回单帧解压（可能不完整）。建议直接导出 .jsonl。");
    return zstdDecompressSync(raw).toString("utf8");
  }
}

const text = readSession(input);

const events = text.split("\n").filter((l) => l.trim()).map((l) => JSON.parse(l));

const pad = (n) => String(n).padStart(2, "0");
const stamp = (ms) => {
  const d = new Date(ms);
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
};
const clip = (s, n) => (s.length > n ? s.slice(0, n) + ` …（截断，共 ${s.length} 字）` : s);

let out = "# 会话存档\n\n";
const metaEvent = events.find((e) => e.type === "session");
const meta = metaEvent ? (metaEvent.data ?? metaEvent) : null;
if (meta) {
  out += `- 会话：\`${meta.id}\`\n- 工作区：\`${meta.cwd}\`\n- 开始：${stamp(meta.createdAt)}\n\n---\n\n`;
}

for (const e of events) {
  const t = e.type;
  const time = stamp(e.time);

  if (t === "user/message") {
    const body = (e.data.content || []).filter((c) => c.type === "text").map((c) => c.text).join("\n");
    if (body.trim()) out += `\n## 用户 · ${time}\n\n${body}\n`;
  } else if (t === "assistant/message") {
    const parts = (e.data?.message?.content || []).filter((c) => c.type === "text").map((c) => c.text);
    const body = parts.join("\n");
    if (body.trim()) out += `\n### 助手 · ${time}\n\n${body}\n`;
  } else if (t === "tool/call") {
    const args = clip(String(e.data.arguments || ""), 300);
    out += `\n> 调用 \`${e.data.name}\` ${args}\n`;
  } else if (t === "tool/result") {
    const body = (e.data?.message?.content || []).map((c) => c.text || "").join("\n");
    const flag = e.data?.message?.isError ? "（失败）" : "";
    out += `> 结果${flag}：${clip(body.replace(/\n/g, " "), 300)}\n`;
  } else if (t === "session/title") {
    const title = e.data?.title;
    if (title) out = out.replace("# 会话存档", `# 会话存档 · ${title}`);
  }
}

writeFileSync(output, out, "utf8");
console.log(`wrote ${output} (${out.length} chars, ${events.length} events)`);
