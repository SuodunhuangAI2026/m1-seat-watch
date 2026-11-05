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


def load_families() -> list[dict]:
    reg = json.loads((DATA / "standards.json").read_text(encoding="utf-8-sig"))
    return reg["families"]


def load_sites() -> dict[str, dict]:
    data = json.loads((DATA / "sites.json").read_text(encoding="utf-8-sig"))
    return {s["id"]: s for s in data["sites"]}


def run_probe(only: list[str] | None = None) -> dict:
    """探测 + 抓取 + 归一化 + 落盘。返回健康表。

    任何一步失败都记进健康表并继续下一个族——一个站点挂了不能拖垮其余 71 个。
    """
    from scripts import normalize, state
    from scripts.adapters.base import AdapterError, get_adapter

    sites = load_sites()
    families = load_families()
    if only:
        families = [f for f in families if f["id"] in only]
        missing = set(only) - {f["id"] for f in families}
        if missing:
            raise SystemExit(f"找不到族：{', '.join(sorted(missing))}")

    health: dict[str, dict] = {}
    fetched = 0
    down: dict[str, str] = {}   # 站点 id → 首次失败原因；同一站点挂了就不再逐个硬试
    doc_event_done: set[str] = set()  # document 形状的站点，一次变更只出一条事件

    for fam in families:
        sid = fam["id"]
        site = fam["site"]

        if site in down:
            health[sid] = {"ok": False, "status": "site_down",
                           "error": f"同站点已失败，本次跳过：{down[site]}"}
            continue

        try:
            adapter = get_adapter(site, sites.get(site))
        except AdapterError as e:
            health[sid] = {"ok": False, "status": "no_adapter", "error": str(e)}
            down[site] = str(e)
            continue

        try:
            docs = adapter.probe(fam)
        except Exception as e:  # noqa: BLE001
            err = f"{type(e).__name__}: {e}"
            health[sid] = {"ok": False, "status": "probe_failed", "error": err}
            down[site] = err
            print(f"  [探测失败] {sid}: {e}（本站其余族本轮跳过）", flush=True)
            continue

        if not docs:
            if (sites.get(site) or {}).get("manual"):
                health[sid] = {"ok": False, "status": "needs_manual",
                               "error": f"待人工补正文：把文本放进 data/manual/{sid}/（文件名即版本号）"}
                print(f"  [待人工] {sid}：无公开正文源，等人工上传", flush=True)
            else:
                health[sid] = {"ok": False, "status": "not_found",
                               "error": "站点上没有找到该族的文档"}
                print(f"  [未命中] {sid}", flush=True)
            continue

        latest = docs[-1]
        text_key = latest.meta.get("text_key") or sid
        if state.load_text(text_key, latest.edition):
            state.record_edition(sid, latest.edition, {"url": latest.url})
            health[sid] = {"ok": True, "status": "unchanged", "edition": latest.edition,
                           "versions": len(docs)}
            continue

        try:
            raw = adapter.fetch(latest)
            text, form = normalize.to_text(raw, kind=latest.meta.get("format", ""))
        except normalize.UnusableDocument as e:
            health[sid] = {"ok": False, "status": "needs_manual", "edition": latest.edition,
                           "error": str(e)}
            print(f"  [需人工] {sid} {latest.edition}: {e}", flush=True)
            continue
        except Exception as e:  # noqa: BLE001
            health[sid] = {"ok": False, "status": "fetch_failed", "edition": latest.edition,
                           "error": f"{type(e).__name__}: {e}"}
            print(f"  [抓取失败] {sid}: {e}", flush=True)
            continue

        state.save_text(text_key, latest.edition, text)
        fetched += 1
        health[sid] = {"ok": True, "status": "new", "edition": latest.edition,
                       "form": form, "chars": len(text), "versions": len(docs)}
        print(f"  [新增] {sid} {latest.edition}（{form}, {len(text)} 字符）", flush=True)

        # 有上一版正文就做条款比对并归因；没有（首次建库）只登记版本
        prev = state.previous_edition(sid, latest.edition)
        old_text = state.load_text(text_key, prev) if prev else None
        if not old_text:
            state.record_edition(sid, latest.edition, {"form": form, "url": latest.url})
            continue

        # 一整份法规被多个族共用时，只由第一个族出事件，避免同一处改动报六遍
        if latest.meta.get("shape") == "document":
            if site in doc_event_done:
                state.record_edition(sid, latest.edition, {"form": form, "url": latest.url})
                continue
            doc_event_done.add(site)

        from scripts import diff as diffmod, publish

        changes = diffmod.diff(old_text, text)
        if not changes:
            health[sid]["status"] = "unchanged_content"
            state.record_edition(sid, latest.edition, {"form": form, "url": latest.url})
            print(f"  [同文] {sid} {latest.edition}：版本号变了但正文一致", flush=True)
            continue

        event = publish.process(
            family=fam, old_ed=prev, new_ed=latest.edition, changes=changes,
            doc={"published": latest.published, "form": form, "url": latest.url,
                 "version": normalize.detect_version(text, 6000),
                 "label": (latest.meta or {}).get("label")},
            source_url=latest.url,
        )
        health[sid]["status"] = "changed"
        health[sid]["diff_total"] = len(changes)
        health[sid]["analyzed"] = event["impact"].get("analyzed", True)
        print(f"  [变更] {sid} {prev} → {latest.edition}：{len(changes)} 处"
              f"{'' if event['impact'].get('analyzed', True) else '（未归因）'}", flush=True)

    summary = {
        "checked_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds"),
        "checked": len(families),
        "fetched": fetched,
        "families": health,
    }
    state.save_health(summary)
    print(
        f"\n探测 {len(families)} 族，新增正文 {fetched} 份，"
        f"失败 {sum(1 for v in health.values() if not v['ok'])} 族",
        flush=True,
    )
    return summary


def pipeline(only: list[str] | None = None) -> int:
    """P1：probe → fetch → normalize → 落盘。P2 再接 diff → analyze → publish。"""
    for cmd in ([sys.executable, str(ROOT / "scripts" / "build_registry.py")],):
        print("+", Path(cmd[1]).name, flush=True)
        if subprocess.call(cmd, cwd=ROOT) != 0:
            return 1

    run_probe(only)

    print("+ build_site.py", flush=True)
    return subprocess.call([sys.executable, str(ROOT / "scripts" / "build_site.py")], cwd=ROOT)


def cmd_diff(standard_id: str, old: str, new: str) -> int:
    from scripts import diff as diffmod
    from scripts import state

    a = state.load_text(standard_id, old)
    b = state.load_text(standard_id, new)
    if a is None:
        print(f"没有正文：{standard_id} / {old}（已有 {state.list_editions(standard_id)}）")
        return 1
    if b is None:
        print(f"没有正文：{standard_id} / {new}（已有 {state.list_editions(standard_id)}）")
        return 1

    changes = diffmod.diff(a, b)
    s = diffmod.summarize(changes)
    print(f"\n{standard_id}: {old} → {new}")
    print(f"条款变动 {s['total']} 处：新增 {s['counts']['added']} / 删除 {s['counts']['removed']} / 修改 {s['counts']['modified']}\n")
    for c in changes[:40]:
        mark = {"added": "+", "removed": "-", "modified": "~"}[c["kind"]]
        body = (c["new"] or c["old"] or "")[:160]
        print(f"  {mark} [{c['clause']}] {body}")
    if len(changes) > 40:
        print(f"  … 另有 {len(changes) - 40} 处未显示")
    return 0


def cmd_calibrate(site_id: str) -> int:
    """在真实网络上探一次站点，把「解析器看到了什么」打印出来。

    本机没有外网时只能在 Actions 里跑；把输出贴回来就能校准配置。
    """
    from scripts import http
    from scripts.adapters.generic import extract_links, find_date

    cfg = load_sites().get(site_id)
    if not cfg:
        print(f"没有这个站点：{site_id}")
        print("可选：" + ", ".join(sorted(load_sites())))
        return 1

    url = cfg.get("entry_url")
    if not url:
        print(f"{site_id} 没有配置 entry_url")
        return 1

    print(f"站点：{cfg['name']}")
    print(f"入口：{url}")
    print(f"形状：{cfg.get('shape', 'list')}\n")

    try:
        raw = http.get(url)
    except Exception as e:  # noqa: BLE001
        print(f"抓取失败：{type(e).__name__}: {e}")
        return 1

    text = raw.decode(cfg.get("charset", "utf-8"), "replace")
    print(f"HTTP 成功：{len(raw)} 字节 / {len(text)} 字符")
    print(f"识别到的日期：{find_date(text, cfg.get('date_patterns'))}")

    links = extract_links(text, cfg.get("link_pattern", r"\.pdf$"))
    print(f"\n链接匹配（pattern={cfg.get('link_pattern')!r}）：{len(links)} 条")
    for href, ctx in links[:25]:
        print(f"  - {href[:110]}")
        print(f"      {ctx[:110]}")

    fams = [f for f in load_families() if f["site"] == site_id]
    print(f"\n该站点的族（{len(fams)} 个）：")
    for f in fams:
        print(f"  {f['id']:<18} match={(f.get('locator') or {}).get('match')!r}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--scheduled", action="store_true", help="按调度配置判断是否执行")
    g.add_argument("--now", action="store_true", help="立即执行")
    g.add_argument("--force", action="store_true", help="等同 --now（workflow_dispatch 用）")
    g.add_argument("--diff", nargs=3, metavar=("族", "旧版本", "新版本"), help="比对两个已存版本")
    g.add_argument("--calibrate", metavar="站点", help="探一次站点并打印解析结果")
    ap.add_argument("--only", action="append", help="只跑指定族，可重复")
    args = ap.parse_args()

    if args.calibrate:
        return cmd_calibrate(args.calibrate)

    if args.diff:
        return cmd_diff(*args.diff)

    if args.scheduled:
        run, reason = gate()
        print(f"[调度] {reason}", flush=True)
        set_output(run, reason)
        if not run:
            return 0
    else:
        print("[调度] 手动触发，跳过调度判断", flush=True)
        set_output(True, "manual")

    rc = pipeline(args.only)
    if rc == 0:
        cfg = json.loads((DATA / "schedule.json").read_text(encoding="utf-8-sig"))
        today = datetime.now(ZoneInfo(cfg.get("timezone", "Asia/Shanghai"))).date().isoformat()
        write_last_run(today)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
