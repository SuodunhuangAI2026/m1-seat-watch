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
import threading
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


def _family_job(family_id: str) -> dict:
    """在子进程里探测+抓取+归一化+落盘单个族，返回该族的健康结果。

    这里只做有网络风险的工作；条款比对和归因留在父进程（快、且依赖已有状态）。
    任何异常都被转换成这个 dict 里的一项——子进程不能崩。
    """
    from scripts import normalize, state
    from scripts.adapters.base import AdapterError, get_adapter

    fam = next((f for f in load_families() if f["id"] == family_id), None)
    if not fam:
        return {"id": family_id, "stage": "no_adapter", "error": "找不到族"}

    try:
        adapter = get_adapter(fam["site"], load_sites().get(fam["site"]))
    except AdapterError as e:
        return {"id": family_id, "stage": "no_adapter", "error": str(e)}

    try:
        docs = adapter.probe(fam)
    except Exception as e:  # noqa: BLE001
        err = f"{type(e).__name__}: {e}"
        return {"id": family_id, "stage": "probe_failed", "error": err}

    if not docs:
        if (load_sites().get(fam["site"]) or {}).get("manual"):
            return {"id": family_id, "stage": "needs_manual",
                    "error": f"待人工补正文：把文本放进 data/manual/{family_id}/（文件名即版本号）"}
        return {"id": family_id, "stage": "not_found", "error": "站点上没有找到该族的文档"}

    latest = docs[-1]
    text_key = latest.meta.get("text_key") or family_id
    if state.load_text(text_key, latest.edition):
        state.record_edition(family_id, latest.edition, {"url": latest.url})
        return {"id": family_id, "stage": "unchanged", "edition": latest.edition,
                "versions": len(docs)}

    try:
        raw = adapter.fetch(latest)
        text, form = normalize.to_text(raw, kind=latest.meta.get("format", ""))
    except normalize.UnusableDocument as e:
        return {"id": family_id, "stage": "needs_manual", "edition": latest.edition,
                "error": str(e)}
    except Exception as e:  # noqa: BLE001
        err = f"{type(e).__name__}: {e}"
        return {"id": family_id, "stage": "fetch_failed", "edition": latest.edition,
                "error": err}

    state.save_text(text_key, latest.edition, text)
    return {"id": family_id, "stage": "new", "edition": latest.edition,
            "form": form, "chars": len(text), "versions": len(docs),
            "text_key": text_key, "url": latest.url,
            "published": latest.published, "label": (latest.meta or {}).get("label"),
            "shape": latest.meta.get("shape", "")}


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

    summary = {
        "checked_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds"),
        "checked": len(families),
        "fetched": 0,
        "families": health,
    }

    def flush_health() -> None:
        summary["fetched"] = fetched
        state.save_health(summary)

    # 整轮墙钟预算：到点就把剩余族标成 deferred，继续出健康表和站点，
    # 保证工作流一定能跑完（而不是被一个慢站点挂死到超时被杀）。
    budget_s = float(os.environ.get("PROBE_BUDGET_SECONDS", "1500"))
    deadline = datetime.now() + timedelta(seconds=budget_s)
    per_family_s = float(os.environ.get("PROBE_FAMILY_SECONDS", "45"))

    # 核心族优先（稳定排序，组内保持原顺序）。预算有限时优先覆盖核心 T1 体系。
    families = sorted(families, key=lambda f: 0 if f.get("category") == "core" else 1)
    summary["checked"] = len(families)

    # 子进程结果的落盘目录（.state 不进仓库、不进提交）
    child_dir = ROOT / "data" / ".state" / "children"
    child_dir.mkdir(parents=True, exist_ok=True)
    for stale in child_dir.glob("*.json"):
        try:
            stale.unlink()
        except OSError:
            pass

    for fam in families:
        flush_health()            # 先把已完成的族落盘，再处理下一个
        sid = fam["id"]
        site = fam["site"]

        if datetime.now() >= deadline:
            health[sid] = {"ok": False, "status": "deferred",
                           "error": f"超出本轮 {int(budget_s)}s 预算，下轮再试"}
            continue

        if site in down:
            health[sid] = {"ok": False, "status": "site_down",
                           "error": f"同站点已失败，本次跳过：{down[site]}"}
            continue

        # 每个族一个子进程：网络相关的探测/抓取全在里面。卡死的 DNS 或慢滴流
        # socket 用线程等不到返回，用进程 kill + wait(timeout=) 一定杀得掉。
        out_path = child_dir / f"{sid}.json"
        try:
            out_path.unlink()
        except OSError:
            pass
        proc = subprocess.Popen(
            [sys.executable, str(ROOT / "run.py"), "--one", sid, "--out", str(out_path)],
            cwd=ROOT,
        )
        timed_out = False
        try:
            proc.wait(timeout=per_family_s)
        except subprocess.TimeoutExpired:
            timed_out = True
            proc.kill()
            try:
                proc.wait(10)
            except subprocess.TimeoutExpired:
                pass

        if timed_out:
            health[sid] = {"ok": False, "status": "timeout",
                           "error": f"超过 {int(per_family_s)}s 未返回，已强杀子进程"}
            down[site] = f"超过 {int(per_family_s)}s 未返回"
            print(f"  [超时] {sid}: 超过 {int(per_family_s)}s 未返回（已强杀）", flush=True)
            continue

        if not out_path.exists():
            health[sid] = {"ok": False, "status": "probe_failed",
                           "error": "子进程退出但没有写出结果（内部崩溃）"}
            print(f"  [探测失败] {sid}: 子进程没有写出结果", flush=True)
            continue

        res = json.loads(out_path.read_text(encoding="utf-8-sig"))
        stage = res.get("stage")

        if stage == "no_adapter":
            health[sid] = {"ok": False, "status": "no_adapter", "error": res.get("error")}
            down[site] = res.get("error", "")
            continue

        if stage == "probe_failed":
            err = res.get("error") or "未知"
            health[sid] = {"ok": False, "status": "probe_failed", "error": err}
            down[site] = err
            print(f"  [探测失败] {sid}: {err}", flush=True)
            continue

        if stage == "not_found":
            health[sid] = {"ok": False, "status": "not_found",
                           "error": res.get("error", "站点上没有找到该族的文档")}
            print(f"  [未命中] {sid}", flush=True)
            continue

        if stage == "needs_manual":
            err = res.get("error") or "无公开正文源，等人工上传"
            health[sid] = {"ok": False, "status": "needs_manual",
                           "edition": res.get("edition"),
                           "error": err}
            print(f"  [需人工] {sid}{(' ' + str(res.get('edition'))) if res.get('edition') else ''}: {err}", flush=True)
            continue

        if stage == "fetch_failed":
            health[sid] = {"ok": False, "status": "fetch_failed",
                           "edition": res.get("edition"),
                           "error": res.get("error")}
            print(f"  [抓取失败] {sid}: {res.get('error')}", flush=True)
            continue

        if stage == "unchanged":
            state.record_edition(sid, res["edition"], {})
            health[sid] = {"ok": True, "status": "unchanged",
                           "edition": res["edition"], "versions": res.get("versions")}
            continue

        if stage != "new":
            # 子进程返回了未知 stage，按失败处理
            health[sid] = {"ok": False, "status": "unknown",
                           "error": f"子进程返回未知 stage：{stage}"}
            continue

        fetched += 1
        health[sid] = {"ok": True, "status": "new", "edition": res["edition"],
                       "form": res["form"], "chars": res["chars"],
                       "versions": res.get("versions")}
        print(f"  [新增] {sid} {res['edition']}（{res['form']}, {res['chars']} 字符）", flush=True)

        text_key = res.get("text_key") or sid
        new_text = state.load_text(text_key, str(res["edition"]))

        prev = state.previous_edition(sid, str(res["edition"]))
        old_text = state.load_text(res.get("text_key") or sid, prev) if prev else None
        if not old_text:
            state.record_edition(sid, res["edition"],
                                 {"form": res["form"], "url": res.get("url")})
            continue

        if res.get("shape") == "document":
            if site in doc_event_done:
                state.record_edition(sid, res["edition"],
                                     {"form": res["form"], "url": res.get("url")})
                continue
            doc_event_done.add(site)

        from scripts import diff as diffmod, publish

        changes = diffmod.diff(old_text, new_text)
        if not changes:
            health[sid]["status"] = "unchanged_content"
            state.record_edition(sid, res["edition"],
                                 {"form": res["form"], "url": res.get("url")})
            print(f"  [同文] {sid} {res['edition']}：版本号变了但正文一致", flush=True)
            continue

        event = publish.process(
            family=fam, old_ed=prev, new_ed=res["edition"], changes=changes,
            doc={"published": res.get("published"), "form": res["form"],
                 "url": res.get("url"),
                 "version": normalize.detect_version(res.get("text") or "", 6000),
                 "label": res.get("label")},
            source_url=res.get("url"),
        )
        health[sid]["status"] = "changed"
        health[sid]["diff_total"] = len(changes)
        health[sid]["analyzed"] = event["impact"].get("analyzed", True)
        print(f"  [变更] {sid} {prev} → {res['edition']}：{len(changes)} 处"
              f"{'' if event['impact'].get('analyzed', True) else '（未归因）'}", flush=True)

    flush_health()
    print(
        f"\n探测 {len(families)} 族，新增正文 {fetched} 份，"
        f"失败 {sum(1 for v in health.values() if not v['ok'])} 族",
        flush=True,
    )
    return summary


def pipeline(only: list[str] | None = None, probe_only: bool = False) -> int:
    """P1：probe → fetch → normalize → 落盘。P2 再接 diff → analyze → publish。

    probe_only=True 时只探测不建站（工作流把构建拆成独立步骤，避免探测被
    timeout 强杀后连站点都出不来）。
    """
    for cmd in ([sys.executable, str(ROOT / "scripts" / "build_registry.py")],):
        print("+", Path(cmd[1]).name, flush=True)
        if subprocess.call(cmd, cwd=ROOT) != 0:
            return 1

    run_probe(only)

    if probe_only:
        print("+ 跳过 build_site（--probe-only）", flush=True)
        return 0

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
    # 单族子进程入口：独立进程里做 probe+fetch，把结果写进 --out。
    # 放进互斥组是为了让子进程的 "run.py --one X" 能通过 argparse 必填校验。
    g.add_argument("--one", metavar="族", help=argparse.SUPPRESS)
    g.add_argument("--diff", nargs=3, metavar=("族", "旧版本", "新版本"), help="比对两个已存版本")
    g.add_argument("--calibrate", metavar="站点", help="探一次站点并打印解析结果")
    ap.add_argument("--only", action="append", help="只跑指定族，可重复")
    # 与 --now 组合使用：只探测不建站。工作流用 timeout 强杀它，再单独 build_site。
    ap.add_argument("--out", metavar="路径", help=argparse.SUPPRESS)
    ap.add_argument("--probe-only", action="store_true",
                    help="配合 --now：只探测，不 build_site（供工作流分离构建用）")
    args = ap.parse_args()

    # --one：单族子进程入口。probe/fetch 在子进程里做，结果写 --out 指定文件。
    if getattr(args, "one", None):
        res = _family_job(args.one)
        out = getattr(args, "out", None) or os.devnull
        Path(out).write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
        print(f"[child] {args.one} → {res.get('stage')}", flush=True)
        return 0

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

    rc = pipeline(args.only, probe_only=getattr(args, "probe_only", False))
    if rc == 0:
        cfg = json.loads((DATA / "schedule.json").read_text(encoding="utf-8-sig"))
        today = datetime.now(ZoneInfo(cfg.get("timezone", "Asia/Shanghai"))).date().isoformat()
        write_last_run(today)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
