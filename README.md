# M1 座椅标准变更监控

定时巡检 M1 类汽车座椅相关的法规与评价协议（UNECE / FMVSS / GB / ADR / GSO / 各国 NCAP / 限用物质），
发现版本变更后生成可直接转发的中文报告。

- 设计规格：`../docs/superpowers/specs/2026-11-05-m1-seat-standard-watch-design.md`
- 实施计划：`../docs/superpowers/plans/2026-11-05-m1-seat-standard-watch-plan.md`

## 当前状态

**P0 完成**：仓库骨架、调度判定、注册表编译、静态站最小版。
尚未实现的：抓取、归一化、差异比对、模型归因、报告页（P1–P2）。

## 结构

```
data/
  schedule.json          周几 + 时刻（Asia/Shanghai）
  sites.json             19 个站点，适配器按站点实现
  standards.json         由 registry.source.csv 编译生成，72 个族
  registry.source.csv    清单原始条目（来自 JF AI 非企业标准清单 + 补入的限用物质法规）
scripts/
  build_registry.py      CSV → standards.json
  build_site.py          → docs/*.html
run.py                   入口
docs/                    生成的静态站（GitHub Pages 从这里发布）
```

## 本地跑

```bash
python run.py --now        # 立即执行一次
python run.py --scheduled  # 按 schedule.json 判断该不该跑
```

## 部署

1. 仓库 Settings → Pages → Source 选 `Deploy from a branch`，分支 `main`，目录 `/docs`
2. Actions 已经配好，`*/15 * * * *` 唤醒，由 `data/schedule.json` 决定是否执行
3. 改检查时间：直接编辑 `data/schedule.json` 的 `days` 与 `time`，提交即可，不用动 workflow
4. 立即检索：Actions → watch → Run workflow

## 约定

- 无变化不提交
- 抓不到就报错，绝不静默当成「无变化」
- 人工结论写 `data/reviews/`，自动化流程只读不写
