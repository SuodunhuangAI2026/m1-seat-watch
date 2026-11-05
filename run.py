#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""入口。

  python run.py --scheduled   按 data/schedule.json 判断该不该跑（GitHub Actions 每 15 分钟调用一次）
  python run.py --now         立即跑一次，跳过调度判断（对应页面上的「立即检索」）
"""
import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
STATE = DATA / ".state" / "last_run"

# 周几的写法容错。认不出来的值直接报错——配置写错必须让流水线红，不能静默永远跳过。
DAY_ALIASES = {
    "mon": "Mon", "monday": "Mon", "周一": "Mon", "星期一": "Mon",
    "tue": "Tue", "tuesday": "Tue", "周二": "Tue", "星期二": "Tue",
    "wed": "Wed", "wednesday": "Wed", "周三": "Wed", "星期三": "Wed",
    "thu": "Thu", "thursday": "Thu", "周四": "Thu", "星期四": "Thu",
    "fri": "Fri", "friday": "Fri", "周五": "Fri", "星期五": "Fri",
    "sat": "Sat", "saturday": "Sat", "周六": "Sat", "星期六": "Sat",
    "sun": "Sun", "sunday": "Sun", "周日": "Sun", "星期日": "Sun",
}


def parse_days(raw) -> set[str]:
    if not isinstance(raw, list) or not raw:
        raise SystemExit('schedule.json 的 days 必须是非空数组，例如 ["Mon","Wed","Fri"]')
    out = set()
    for item in raw:
        key = str(item).strip().lower()
        if key not in DAY_ALIASES:
            raise SystemExit(
                f"schedule.json 的 days 里有无法识别的值：{item!r}\n"
                f"可用写法：Mon…Sun、周一…周日、monday…sunday"
            )
        out.add(DAY_ALIASES[key])
    return out


def parse_time(raw: str) -> tuple[int, int]:
    try:
        hh, mm = (int(x) for x in str(raw).strip().split(":"))
    except Exception:
        raise SystemExit(f'schedule.json 的 time 必须是 HH:MM，当前是 {raw!r}')
    if not (0 <= hh < 24 and 0 <= mm < 60):
        raise SystemExit(f"schedule.json 的 time 超出范围：{raw!r}")
    return hh, mm


def read_last_run() -> str | None:
    try:
        return STATE.read_text(encoding="utf-8-sig").strip()
    except FileNotFoundError:
        return None


def write_last_run(day: str) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(day + "\n", encoding="utf-8")


def set_output(run: bool, reason: str) -> None:
    gh = os.environ.get("GITHUB_OUTPUT")
    if gh:
        with open(gh, "a", encoding="utf-8") as fh:
            fh.write(f"run={'true' if run else 'false'}\n")
            fh.write(f"reason={reason}\n")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as fh:
            fh.write(f"### 调度判定：{'执行' if run else '跳过'}\n\n{reason}\n")


def gate() -> tuple[bool, str]:
    cfg = json.loads((DATA / "schedule.json").read_text(encoding="utf-8-sig"))
    tz = ZoneInfo(cfg.get("timezone", "Asia/Shanghai"))
    now = datetime.now(tz)
    today = now.date().isoformat()

    days = parse_days(cfg.get("days"))
    hh, mm = parse_time(cfg.get("time"))
    window = int(cfg.get("window_minutes", 30))

    if not cfg.get("enabled", True):
        return False, "调度已关闭（schedule.json enabled=false）"

    weekday = DAY_ALIASES[now.strftime("%a").lower()]
    if weekday not in days:
        return False, f"今天是 {weekday}，不在 {sorted(days)} 内"

    target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)

    if now < target:
        return False, f"当前 {now:%H:%M}，尚未到 {cfg['time']}"
    if now >= target + timedelta(minutes=window):
        return False, f"当前 {now:%H:%M}，已过 {cfg['time']}+{window} 分钟窗口"

    last = read_last_run()
    if last == today:
        return False, f"{today} 已经跑过"

    return True, f"命中调度：{today} {cfg['time']}，窗口 {window} 分钟"


def pipeline() -> int:
    """P0：只重建站点。P1 起在这里接入 probe → fetch → normalize → diff → analyze。"""
    steps = [
        [sys.executable, str(ROOT / "scripts" / "build_registry.py")],
        [sys.executable, str(ROOT / "scripts" / "build_site.py")],
    ]
    for cmd in steps:
        print("+", " ".join(Path(c).name for c in cmd), flush=True)
        rc = subprocess.call(cmd, cwd=ROOT)
        if rc != 0:
            print(f"  失败，退出码 {rc}", flush=True)
            return rc
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--scheduled", action="store_true", help="按调度配置判断是否执行")
    g.add_argument("--now", action="store_true", help="立即执行")
    g.add_argument("--force", action="store_true", help="等同 --now（workflow_dispatch 用）")
    args = ap.parse_args()

    if args.scheduled:
        run, reason = gate()
        print(f"[调度] {reason}", flush=True)
        set_output(run, reason)
        if not run:
            return 0
    else:
        print("[调度] 手动触发，跳过调度判断", flush=True)
        set_output(True, "manual")

    rc = pipeline()
    if rc == 0:
        cfg = json.loads((DATA / "schedule.json").read_text(encoding="utf-8-sig"))
        today = datetime.now(ZoneInfo(cfg.get("timezone", "Asia/Shanghai"))).date().isoformat()
        write_last_run(today)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
