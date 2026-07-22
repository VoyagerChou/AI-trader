import json
from pathlib import Path
from collections import defaultdict
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
path = ROOT / "weekly_report_output.json"

with open(path, "r", encoding="utf-8") as f:
    d = json.load(f)

report = d.get("report", {})
deep = report.get("deep_analysis", [])

today = datetime.now().strftime("%Y-%m-%d")
report_dir = ROOT / "reports"
report_dir.mkdir(exist_ok=True)

lines = []
lines.append("=" * 60)
lines.append("        日报")
lines.append("=" * 60)
lines.append(f"日期: {today}")
lines.append(f"生成时间: {d.get('generated_at', '')}")
lines.append("")

summary = report.get("summary", "")
if summary:
    lines.append(summary)
    lines.append("")

# Regime info first
if deep:
    regime_items = [da for da in deep if da.get("is_regime")]
    etf_items = [da for da in deep if not da.get("is_regime")]
    
    for da in regime_items:
        theme = da.get("theme", "")
        trend = da.get("trend_status", "")
        lines.append(f"{'─' * 60}")
        lines.append(f"  【{theme}】 {trend}")
        for sig in da.get("signals", []):
            if "close=" not in sig:
                lines.append(f"    · {sig}")
        lines.append("")
    
    by_strat = defaultdict(list)
    for da in etf_items:
        by_strat[da.get("strategy", "其他")].append(da)

    name_map = {
        "dynamic_etf": "动态ETF轮动",
        "super_trend": "超级趋势增强动量",
        "triple_screen": "三重滤网",
        "ma_slope": "均线斜率",
        "超级趋势增强动量": "超级趋势增强动量",
        "三重滤网": "三重滤网",
        "均线斜率": "均线斜率",
        "动态ETF轮动": "动态ETF轮动",
    }

    for sname, items in by_strat.items():
        label = name_map.get(sname, sname)
        lines.append(f"{'─' * 60}")
        lines.append(f"  {label}")
        for da in items:
            theme = da.get("theme", "")
            trend = da.get("trend_status", "")
            lines.append(f"\n    ■ {theme} — {trend}")
            for sig in da.get("signals", []):
                lines.append(f"      + {sig}")
            for warn in da.get("warnings", []):
                lines.append(f"      ! {warn}")
            entry = da.get("entry_suggestion", "")
            if entry:
                lines.append(f"      -> 入场建议: {entry}")

fn = report.get("footnotes", "")
if fn:
    lines.append("")
    lines.append(f"{'─' * 60}")
    lines.append("")
    if isinstance(fn, list):
        for f in fn:
            lines.append(f"  · {f.get('term', '')}: {f.get('definition', '')}")
    elif isinstance(fn, str):
        lines.append(f"  {fn}")

lines.append("")
lines.append("=" * 60)
lines.append("报告结束")
lines.append("=" * 60)

text = "\n".join(lines)
print(text)

out_path = report_dir / f"report_{today}.txt"
out_path.write_text(text, encoding="utf-8")
print(f"\n(Saved to {out_path})")
