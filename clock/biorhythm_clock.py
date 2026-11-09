#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
biorhythm_clock.py —— 给 Agent 轮询用的「昼夜节律唤醒时钟」

作用
  1. 输出当前时间（年/月/日/时/分/秒 + 星期 + 时区 + 所处时段）
  2. 按「拟人的作息节律」随机抽取下一次主动对话的时刻（间隔 0.5h ~ 24h）
  3. 输出距离下一次唤醒的倒计时（秒 / 可读文本），供 Agent 轮询或阻塞等待

节律规则（权重越高 = 越可能在这个时刻主动发消息）
  00:00 - 07:00   权重 0   静默期，绝不主动发消息（睡觉）
  07:00 - 09:00   权重 低   刚起床，少量
  09:00 - 11:30   权重 中   上午活跃
  11:30 - 14:00   权重 最高 午休 / 午饭后高峰
  14:00 - 17:00   权重 偏低 下午工作段
  17:00 - 20:00   权重 中高 下班通勤 + 晚饭
  20:00 - 22:00   权重 最高 晚间高峰
  22:00 - 24:00   权重 0   静默期

采样算法
  在 [now + 0.5h, now + 24h] 内以 5 分钟为网格枚举所有候选时刻，
  每个时刻的权重 = 昼夜节律权重(hour) × 间隔倾向权重(gap)，
  其中 间隔倾向 = gap^(-gap_bias)，gap_bias 越大越偏向短间隔（默认 0.45）。
  权重为 0 的候选会被直接剔除，因此永远不会落在 22:00-07:00。
  选中网格后再做一次随机抖动，避免每次都落在整 5 分钟上。

随机数种子
  默认从系统熵取种；生成后种子会自动演进（next_seed）并写入状态文件，
  因此整条序列可复现：只要用 --seed 指定初始种子，后续结果完全一致。

常用命令
  python3 biorhythm_clock.py                 # 看当前时间 + 下次唤醒倒计时
  python3 biorhythm_clock.py --json          # 机器可读输出
  python3 biorhythm_clock.py --regen         # 一轮对话结束后：重新抽下一次
  python3 biorhythm_clock.py --wait          # 阻塞到倒计时归零，然后退出
  python3 biorhythm_clock.py -q              # 只打印倒计时秒数（配合 sleep）
  python3 biorhythm_clock.py --simulate 300  # 模拟 300 次唤醒，验证节律分布
  python3 biorhythm_clock.py --curve         # 打印 24 小时权重曲线
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import signal
import sys
import time
from datetime import datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None

# ---------------------------------------------------------------- 默认参数

DEFAULT_TZ = "Asia/Shanghai"
MIN_GAP_H = 0.5          # 最小间隔（小时）
MAX_GAP_H = 24.0         # 最大间隔（小时）
STEP_MIN = 5             # 采样网格（分钟）
GAP_BIAS = 0.70          # 间隔倾向：0=纯看节律，越大越偏向短间隔
PEAK_GAMMA = 1.5         # 高峰锐度：>1 拉大高峰与低谷的差距，1=不处理
FALLBACK_TZ = {"Asia/Shanghai": 8, "UTC": 0, "Asia/Tokyo": 9, "America/New_York": -5}

WEEKDAYS = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]

# 昼夜节律曲线：(小时浮点数, 权重)  —— 关键点之间线性插值
CURVE = [
    (0.0, 0.00),
    (6.999, 0.00),     # 07:00 之前一律静默
    (7.0, 0.18),       # 刚起床，低活跃
    (8.0, 0.38),
    (9.5, 0.55),
    (11.5, 1.00),      # 午间高峰开始（11:30）
    (14.0, 1.00),      # 午间高峰结束（14:00）
    (15.0, 0.42),      # 下午工作段，低谷
    (17.0, 0.55),
    (18.5, 0.72),      # 下班 + 晚饭后升温
    (20.0, 1.00),      # 晚间高峰开始（20:00）
    (21.999, 1.00),    # 晚间高峰结束（22:00）
    (22.0, 0.00),      # 22:00 之后一律静默
    (24.0, 0.00),
]


# ---------------------------------------------------------------- 工具函数

def get_tz(name: str):
    if ZoneInfo is not None:
        try:
            return ZoneInfo(name)
        except Exception:
            pass
    return timezone(timedelta(hours=FALLBACK_TZ.get(name, 8)), name=name)


def circadian_weight(hour_f: float) -> float:
    """输入 0~24 的小时浮点数，返回该时刻的作息权重。"""
    h = hour_f % 24.0
    for i in range(len(CURVE) - 1):
        x1, y1 = CURVE[i]
        x2, y2 = CURVE[i + 1]
        if x1 <= h <= x2:
            if x2 == x1:
                return y2
            r = (h - x1) / (x2 - x1)
            return y1 + (y2 - y1) * r
    return 0.0


def period_label(hour_f: float) -> str:
    h = hour_f % 24.0
    if h >= 22.0 or h < 7.0:
        return "静默期（不主动发消息）"
    if h < 9.0:
        return "清晨低活跃"
    if h < 11.5:
        return "上午活跃期"
    if h < 14.0:
        return "午间高峰"
    if h < 17.0:
        return "下午活跃期"
    if h < 20.0:
        return "傍晚活跃期"
    return "晚间高峰"


def humanize(seconds: float) -> str:
    seconds = int(round(seconds))
    if seconds < 0:
        return "-" + humanize(-seconds)
    d, s = divmod(seconds, 86400)
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    parts = []
    if d:
        parts.append(f"{d}天")
    if h:
        parts.append(f"{h}小时")
    if m:
        parts.append(f"{m}分")
    if s or not parts:
        parts.append(f"{s}秒")
    return "".join(parts)


def fmt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def weekday_cn(dt: datetime) -> str:
    return WEEKDAYS[dt.weekday()]


def hour_f(dt: datetime) -> float:
    return dt.hour + dt.minute / 60.0 + dt.second / 3600.0


# ---------------------------------------------------------------- 状态文件

def state_path(custom: str | None) -> str:
    if custom:
        return os.path.expanduser(custom)
    env = os.environ.get("CLOCK_STATE")
    if env:
        return os.path.expanduser(env)
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, ".clock_state.json")


def load_state(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(path: str, data: dict) -> None:
    try:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception as e:
        print(f"[warn] 状态文件写入失败: {e}", file=sys.stderr)


# ---------------------------------------------------------------- 核心采样

def sample_next(now: datetime, rng: random.Random, *, min_h: float, max_h: float,
                step_min: int, gap_bias: float, peak_gamma: float = 1.0) -> datetime:
    """按作息节律，从 [now+min_h, now+max_h] 中抽一个唤醒时刻。"""
    step_sec = max(1, int(step_min * 60))
    lo_ep = now.timestamp() + min_h * 3600.0
    hi_ep = now.timestamp() + max_h * 3600.0

    # 向上对齐到网格
    start_ep = math.ceil(lo_ep / step_sec) * step_sec
    if start_ep < lo_ep:
        start_ep += step_sec

    weights, times = [], []
    ep = start_ep
    while ep <= hi_ep + 1e-6:
        gap_h = (ep - now.timestamp()) / 3600.0
        t = datetime.fromtimestamp(ep, now.tzinfo)
        w = circadian_weight(hour_f(t))
        if w > 0:
            if peak_gamma != 1.0:
                w = math.pow(w, peak_gamma)
            if gap_bias and gap_h > 0:
                w *= math.pow(gap_h, -gap_bias)
            weights.append(w)
            times.append(ep)
        ep += step_sec

    if not times:
        # 兜底：极端参数下没有可用候选，直接用最小间隔
        return datetime.fromtimestamp(lo_ep, now.tzinfo)

    total = sum(weights)
    r = rng.random() * total
    acc = 0.0
    chosen = times[-1]
    for w, t in zip(weights, times):
        acc += w
        if r <= acc:
            chosen = t
            break

    # 网格内抖动，避免总落在整 5 分钟上
    jitter = rng.uniform(0, step_sec)
    cand = min(chosen + jitter, hi_ep)
    ct = datetime.fromtimestamp(cand, now.tzinfo)
    if circadian_weight(hour_f(ct)) <= 0:
        cand = chosen  # 抖动跨进了静默期，退回网格点
    return datetime.fromtimestamp(cand, now.tzinfo)


# ---------------------------------------------------------------- 组装输出

def build_payload(now: datetime, nxt: datetime, tzname: str, seed_used: int,
                  next_seed: int, state_file: str, last_wake: datetime | None) -> dict:
    cd = (nxt - now).total_seconds()
    gap_h = cd / 3600.0
    payload = {
        "timezone": tzname,
        "now": {
            "iso": fmt(now),
            "epoch": int(now.timestamp()),
            "weekday": weekday_cn(now),
            "hour": round(hour_f(now), 4),
            "period": period_label(hour_f(now)),
            "in_quiet_hours": period_label(hour_f(now)).startswith("静默"),
        },
        "next": {
            "iso": fmt(nxt),
            "epoch": int(nxt.timestamp()),
            "weekday": weekday_cn(nxt),
            "hour": round(hour_f(nxt), 4),
            "period": period_label(hour_f(nxt)),
            "in_quiet_hours": period_label(hour_f(nxt)).startswith("静默"),
        },
        "countdown_seconds": int(round(cd)),
        "countdown_human": humanize(cd),
        "gap_hours": round(gap_h, 3),
        "due": cd <= 0,
        "seed_used": seed_used,
        "next_seed": next_seed,
        "state_file": state_file,
    }
    if last_wake:
        payload["last_wake_at"] = fmt(last_wake)
        payload["since_last_wake_human"] = humanize((now - last_wake).total_seconds())
    return payload


def render_text(p: dict) -> str:
    lines = [
        f"当前时间：{p['now']['iso']} {p['now']['weekday']}（{p['timezone']} · {p['now']['period']}）",
    ]
    if p.get("last_wake_at"):
        lines.append(f"距上次主动发言：{p['since_last_wake_human']}（{p['last_wake_at']}）")
    lines.append(
        f"下次唤醒：{p['next']['iso']} {p['next']['weekday']}（{p['next']['period']}）"
    )
    if p["due"]:
        lines.append("倒计时：已到点 —— 现在应该主动发起对话")
    else:
        lines.append(f"倒计时：{p['countdown_human']}（{p['countdown_seconds']} 秒 / {p['gap_hours']} 小时）")
    lines.append(f"种子：{p['seed_used']} → 下次 {p['next_seed']}")
    return "\n".join(lines)


def render_prompt(p: dict) -> str:
    """生成可直接塞进 Agent 上下文的时钟提示片段。"""
    n, x = p["now"], p["next"]
    if p["due"]:
        status = f"倒计时已归零，现在请主动开启一轮新对话。当前 {n['period']}，注意语气符合此刻的作息状态。"
    else:
        status = (f"在倒计时归零前，不要主动输出任何内容。倒计时归零后，"
                  f"用符合{x['period']}的语气主动开启一轮新对话。")
    return (
        "【时钟快照】\n"
        f"现在：{n['iso']} {n['weekday']}（{p['timezone']} · {n['period']}）\n"
        f"下次主动对话：{x['iso']} {x['weekday']}（{x['period']}）\n"
        f"剩余：{p['countdown_human']}（{p['countdown_seconds']} 秒）\n"
        "规则：22:00-07:00 为静默期，任何情况下都不主动发消息。\n"
        f"{status}"
    )


# ---------------------------------------------------------------- 子功能

def do_curve(gamma: float = 1.0) -> None:
    print("小时  权重  分布")
    for h in range(24):
        w = circadian_weight(h + 0.5)
        if gamma != 1.0:
            w = math.pow(w, gamma)
        bar = "█" * int(round(w * 30))
        tag = "静默" if w == 0 else ""
        print(f"{h:02d}:00 {w:5.2f}  {bar:<32}{tag}")


def do_simulate(args, tz) -> None:
    rng = random.Random(args.seed if args.seed is not None else 20241001)
    if args.start:
        now = datetime.strptime(args.start, "%Y-%m-%d %H:%M").replace(tzinfo=tz)
    else:
        now = datetime.now(tz)
    start = now
    buckets = [0] * 24
    quiet_hits = 0
    gaps = []
    for _ in range(args.simulate):
        nxt = sample_next(now, rng, min_h=args.min_gap, max_h=args.max_gap,
                          step_min=args.step, gap_bias=args.gap_bias,
                          peak_gamma=args.peak)
        buckets[nxt.hour] += 1
        if circadian_weight(hour_f(nxt)) <= 0:
            quiet_hits += 1
        gaps.append((nxt - now).total_seconds() / 3600.0)
        now = nxt
    total = sum(buckets) or 1
    print(f"模拟 {args.simulate} 次唤醒，起点 {fmt(start)}（{args.tz}）\n")
    print("小时  次数  占比   分布")
    for h in range(24):
        c = buckets[h]
        bar = "█" * int(round(c / max(buckets) * 30)) if max(buckets) else ""
        print(f"{h:02d}:00 {c:5d}  {c/total*100:5.1f}%  {bar}")
    print(f"\n静默期（22:00-07:00）命中次数：{quiet_hits}  <-- 必须为 0")
    print(f"平均间隔：{sum(gaps)/len(gaps):.2f} 小时，最短 {min(gaps):.2f}h，最长 {max(gaps):.2f}h")


def do_wait(nxt: datetime, poll: float, state_file: str) -> int:
    def handler(signum, frame):
        left = (nxt - datetime.now(nxt.tzinfo)).total_seconds()
        print(f"\n[中断] 已退出等待，剩余 {humanize(left)}", file=sys.stderr)
        sys.exit(130)

    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGTERM, handler)

    while True:
        left = (nxt - datetime.now(nxt.tzinfo)).total_seconds()
        if left <= 0:
            break
        time.sleep(min(max(poll, 0.5), left))

    # 到点：清空 pending，记录本次唤醒
    st = load_state(state_file)
    st["last_wake_at"] = datetime.now(nxt.tzinfo).timestamp()
    st["pending_wake_at"] = None
    st.setdefault("history", [])
    st["history"].append(int(st["last_wake_at"]))
    st["history"] = st["history"][-50:]
    save_state(state_file, st)
    return 0


# ---------------------------------------------------------------- 入口

def main() -> int:
    ap = argparse.ArgumentParser(
        description="昼夜节律唤醒时钟：给 Agent 用的当前时间 + 下次主动对话倒计时",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--tz", default=DEFAULT_TZ, help="时区，默认 Asia/Shanghai")
    ap.add_argument("--min-gap", type=float, default=MIN_GAP_H, help="最小间隔（小时），默认 0.5")
    ap.add_argument("--max-gap", type=float, default=MAX_GAP_H, help="最大间隔（小时），默认 24")
    ap.add_argument("--step", type=int, default=STEP_MIN, help="采样网格（分钟），默认 5")
    ap.add_argument("--gap-bias", type=float, default=GAP_BIAS,
                    help="间隔倾向，0=纯看节律，越大越偏短间隔，默认 0.70")
    ap.add_argument("--peak", type=float, default=PEAK_GAMMA,
                    help="高峰锐度，>1 让午间/晚间高峰更突出，默认 1.5")
    ap.add_argument("--seed", type=int, default=None, help="固定随机种子（不传则自动生成）")
    ap.add_argument("--state", default=None, help="状态文件路径")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    ap.add_argument("-q", "--quiet", action="store_true", help="只输出倒计时秒数")
    ap.add_argument("-r", "--regen", action="store_true", help="强制重新抽取下一次唤醒时刻")
    ap.add_argument("-w", "--wait", action="store_true", help="阻塞等待到唤醒时刻后退出")
    ap.add_argument("--poll", type=float, default=30.0, help="wait 模式的检查间隔（秒）")
    ap.add_argument("--prompt", action="store_true", help="额外输出给 Agent 的提示词片段")
    ap.add_argument("--no-save", action="store_true", help="不写状态文件")
    ap.add_argument("--curve", action="store_true", help="打印 24 小时权重曲线")
    ap.add_argument("--simulate", type=int, default=0, help="模拟 N 次唤醒并统计分布")
    ap.add_argument("--start", default=None, help="模拟起点，格式 'YYYY-MM-DD HH:MM'")
    args = ap.parse_args()

    if args.curve:
        do_curve(args.peak)
        return 0

    tz = get_tz(args.tz)

    if args.simulate > 0:
        do_simulate(args, tz)
        return 0

    if args.min_gap <= 0 or args.max_gap <= args.min_gap:
        print("[error] 需要 0 < --min-gap < --max-gap", file=sys.stderr)
        return 2

    sf = state_path(args.state)
    st = load_state(sf)
    now = datetime.now(tz)

    pending = st.get("pending_wake_at")
    need_new = True
    if isinstance(pending, (int, float)) and not args.regen:
        if datetime.fromtimestamp(pending, tz) > now:
            need_new = False

    if need_new:
        seed = args.seed if args.seed is not None else int(st.get("seed") or random.SystemRandom().randrange(1, 2**32))
        rng = random.Random(seed)
        nxt = sample_next(now, rng, min_h=args.min_gap, max_h=args.max_gap,
                          step_min=args.step, gap_bias=args.gap_bias,
                          peak_gamma=args.peak)
        next_seed = rng.randrange(1, 2**32)
        st["seed"] = next_seed
        st["pending_wake_at"] = nxt.timestamp()
        st["generated_at"] = now.timestamp()
        st["timezone"] = args.tz
        if not args.no_save:
            save_state(sf, st)
    else:
        nxt = datetime.fromtimestamp(pending, tz)
        seed = int(st.get("seed_used", st.get("seed", 0)))
        next_seed = int(st.get("seed", seed))
        st["seed_used"] = seed

    last_wake = st.get("last_wake_at")
    last_dt = datetime.fromtimestamp(last_wake, tz) if last_wake else None
    if need_new:
        st["seed_used"] = seed
        if not args.no_save:
            save_state(sf, st)

    p = build_payload(now, nxt, args.tz, seed, next_seed, sf, last_dt)

    if args.wait:
        rc = do_wait(nxt, args.poll, sf)
        p2 = build_payload(datetime.now(tz), nxt, args.tz, seed, next_seed, sf, last_dt)
        p2["due"] = True
        p2["countdown_seconds"] = 0
        p2["countdown_human"] = "0秒"
        if args.json:
            print(json.dumps(p2, ensure_ascii=False, indent=2))
        else:
            print(render_text(p2))
            if args.prompt:
                print("\n" + render_prompt(p2))
        return rc

    if args.quiet:
        print(max(0, p["countdown_seconds"]))
        return 0

    if args.json:
        print(json.dumps(p, ensure_ascii=False, indent=2))
    else:
        print(render_text(p))
        if args.prompt:
            print("\n" + render_prompt(p))
    return 0


if __name__ == "__main__":
    sys.exit(main())
