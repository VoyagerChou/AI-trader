"""Print full readable report without character-splitting bug."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
path = ROOT / "weekly_report_output.json"

with open(path, "r", encoding="utf-8") as f:
    d = json.load(f)

r = d["report"]

print("=" * 60)
print("        每周板块轮动分析报告")
print("=" * 60)
print(f"生成时间: {d['generated_at']}")
print(f"分析文档: {d['window']['doc_count']} 篇")
print()

print("【摘要】")
print(r.get("summary", ""))
print()

for i, s in enumerate(r.get("top_sectors", []), 1):
    name = s.get("name", "?")
    conf = s.get("confidence", "-")
    print(f"{i}. {name} (置信度: {conf})")
    reasons = s.get("reasons", "")
    if isinstance(reasons, str):
        print(f"   + {reasons}")
    else:
        for reason in reasons:
            print(f"   + {reason}")
    risks = s.get("risks", "")
    if isinstance(risks, str):
        print(f"   ! 风险: {risks}")
    elif risks:
        for risk in risks:
            print(f"   ! 风险: {risk}")
    print()

print("【后续关注】")
actions = r.get("next_actions", [])
if isinstance(actions, str):
    actions = [actions]
for a in actions:
    print(f"  - {a}")
print()

print("【行业主线排名】")
print(f"  {'板块':<10} {'得分':>8} {'文档':>5} {'5日收益'}")
print("  " + "-" * 40)
for row in r.get("industry_mainline", []):
    name = row.get("name", "?")
    score = row.get("score", 0)
    docs = row.get("doc_count", 0)
    ret5 = row.get("return_5d", "-")
    print(f"  {name:<10} {score:>8.1f} {docs:>5} {ret5}")

print()
print("【主题/风格主线】")
for row in r.get("theme_mainline", []):
    print(f"  {row['name']}: score={row['score']} docs={row['doc_count']}")

print()
print("【ETF 候选池】")
for e in r.get("etf_candidates", []):
    linked = e.get("linked_sector", e.get("linked_theme", ""))
    print(f"  {e['etf_code']} | {e.get('etf_name', '')} | 关联: {linked}")

print()
print("=" * 60)
print("报告结束")
print("=" * 60)
