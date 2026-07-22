#!/usr/bin/env python3
"""Print the weekly report in readable format."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
path = ROOT / "weekly_report_output.json"

with open(path, "r", encoding="utf-8") as f:
    data = json.load(f)

report = data["report"]

out = []
out.append("=" * 60)
out.append("        每周板块轮动分析报告")
out.append("=" * 60)
out.append(f"生成时间: {data['generated_at']}")
out.append(f"回溯天数: {report.get('lookback_days')} 天")
out.append(f"分析文档: {data['window']['doc_count']} 篇")
out.append("")

out.append("【摘要】")
out.append(report.get("summary", "N/A"))
out.append("")

out.append("【TOP 板块研判】")
for i, s in enumerate(report.get("top_sectors", []), 1):
    name = s.get("name", "?")
    conf = s.get("confidence", 0)
    out.append(f"\n  {i}. {name} (置信度: {conf})")
    for r in s.get("reasons", []):
        out.append(f"     + {r}")
    risks = s.get("risks", [])
    if risks:
        out.append(f"     ! 风险: {risks[0]}")

out.append("")
out.append("【后续关注】")
for a in report.get("next_actions", []):
    out.append(f"  - {a}")

out.append("")
out.append("【行业主线排名】")
out.append(f"  {'板块':<12} {'综合分':>10} {'文档数':>6} {'5日收益':>10} {'热度':>6}")
out.append("  " + "-" * 50)
for row in report.get("industry_mainline", []):
    name = row.get("name", "?")
    score = row.get("score", 0)
    docs = row.get("doc_count", 0)
    ret5d = row.get("return_5d", "0")
    heat = row.get("heat", "0")
    out.append(f"  {name:<12} {score:>10.1f} {docs:>6} {ret5d:>10} {heat:>6}")

out.append("")
out.append("【主题/风格主线】")
for row in report.get("theme_mainline", []):
    name = row.get("name", "?")
    score = row.get("score", 0)
    docs = row.get("doc_count", 0)
    sources = ", ".join(row.get("sources", []))
    out.append(f"  {name}: 评分={score}, 文档={docs}, 来源={sources}")

out.append("")
out.append("【ETF 候选池】")
for e in report.get("etf_candidates", []):
    code = e.get("etf_code", "")
    linked = e.get("linked_sector", e.get("linked_theme", ""))
    name = e.get("etf_name", "")
    out.append(f"  {code} | {name} | 关联: {linked}")

out.append("")
out.append("=" * 60)
out.append("报告结束")
out.append("=" * 60)

text = "\n".join(out)
print(text)

with open(ROOT / "weekly_report_readable.txt", "w", encoding="utf-8") as f:
    f.write(text)
print("\n(已保存到 weekly_report_readable.txt)")
