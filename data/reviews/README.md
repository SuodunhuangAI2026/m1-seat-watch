# 人工处理意见

这个目录是**唯一的人工覆盖入口**。任何自动化流程（`publish.py` / `build_site.py`）都只读不写，
所以你写在这里的东西不会被下一次运行覆盖。

## 怎么写

文件名用事件 id，两种格式任选，也可以并存：

**`2026-11-05-UN-R17.json`** —— 结构化，适合改判

```json
{
  "verdict": "confirmed",
  "override_type": null,
  "override_relevant": null,
  "opinion": "已与锁工确认，下一版 DVP 需增加头枕后移量测量。",
  "by": "岳宗钊"
}
```

| 字段 | 取值 | 作用 |
|:--|:--|:--|
| `verdict` | `confirmed` / `rejected` / `deferred` | 你的结论；`rejected` 表示这条不用管 |
| `override_type` | 如 `CORRIGENDUM` | 模型判错了变更类型时人工改判 |
| `override_relevant` | `true` / `false` | 模型判错了相关性时人工改判 |
| `opinion` | 任意文字 | 显示在报告第 8 节 |

**`2026-11-05-UN-R17.md`** —— 直接写正文，内容原样出现在报告里。

## 怎么改

在 GitHub 网页上打开对应文件 → 编辑 → 提交即可，不需要本地环境。
下一次构建（定时或手动）报告页就会更新。

事件 id 在报告页顶部和 URL 里都能看到，形如 `reports/2026-11-05-UN-R17.html`。
