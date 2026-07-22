#!/usr/bin/env python3
"""Probe curated sources defined in rag_ingest.source_registry.

This script is intentionally lightweight: it does not boot the full Flask app.
It uses direct web search requests to sanity-check whether current query
templates can discover useful pages for each source.

Goals:
1. Check whether a source can return results at all.
2. Check whether returned URLs actually match the intended source domain.
3. Provide a practical recommendation: keep search-mode, tune queries, or move
   to a future direct-ingestion path.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional


ROOT = Path(__file__).resolve().parents[1]


def _load_source_registry_module():
    registry_path = ROOT / "app" / "services" / "rag_ingest" / "source_registry.py"
    module_name = "ai-trader_source_registry"
    spec = importlib.util.spec_from_file_location(module_name, registry_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load source registry from {registry_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


_SOURCE_REGISTRY = _load_source_registry_module()
SourceDefinition = _SOURCE_REGISTRY.SourceDefinition
list_sources = _SOURCE_REGISTRY.list_sources


DEFAULT_TIMEOUT = 15
DUCKDUCKGO_HTML = "https://html.duckduckgo.com/html/"


SITE_QUERY_MAP: Dict[str, List[str]] = {
    "cn_csrc": [
        "site:csrc.gov.cn 证监会 最新 通知 A股",
        "site:csrc.gov.cn 基金 信息披露 办法 最新",
    ],
    "cn_sse": [
        "site:sse.com.cn 上交所 最新 公告 ETF 规则",
        "site:sse.com.cn 上交所 信息披露 最新",
    ],
    "cn_szse": [
        "site:szse.cn 深交所 最新 公告 ETF 规则",
        "site:szse.cn 深交所 信息披露 最新",
    ],
    "cn_cninfo": [
        "site:cninfo.com.cn 巨潮资讯 最新 公告 A股",
        "site:cninfo.com.cn 基金 公告 最新",
    ],
    "cn_sse_etf": [
        "site:etf.sse.com.cn ETF 公告 最新",
        "site:etf.sse.com.cn 基金 公告 最新",
    ],
    "cn_cls": [
        "site:cls.cn A股 快讯 最新",
        "site:cls.cn 板块 轮动 A股",
    ],
    "cn_ndrc": [
        "site:ndrc.gov.cn 产业 政策 最新",
        "site:ndrc.gov.cn 能源 科技 制造 政策 最新",
    ],
    "cn_miit": [
        "site:miit.gov.cn 半导体 算力 通信 政策 最新",
        "site:miit.gov.cn 产业 政策 最新",
    ],
    "cn_nea": [
        "site:nea.gov.cn 电力 储能 光伏 风电 政策 最新",
        "site:nea.gov.cn 能源 政策 最新",
    ],
    "cn_stcn": [
        "site:stcn.com A股 板块 最新",
        "site:stcn.com e公司 板块 轮动",
    ],
    "cn_cs": [
        "site:cs.com.cn A股 板块 最新",
        "site:cs.com.cn 中证快讯 A股",
    ],
    "cn_cnstock": [
        "site:cnstock.com A股 板块 最新",
        "site:cnstock.com 产业资讯 A股",
    ],
    "cn_wallstreetcn": [
        "site:wallstreetcn.com A股 科技 板块",
        "site:wallstreetcn.com 中国市场 最新",
    ],
    "cn_eastmoney_news": [
        "site:eastmoney.com A股 板块 最新",
        "site:eastmoney.com 财经 快讯 A股",
    ],
    "cn_fund_company": [
        "ETF 基金公司 公告 最新",
        "基金 管理人 ETF 公告 最新",
    ],
    "cn_xueqiu": [
        "site:xueqiu.com A股 板块 热门 讨论",
        "site:xueqiu.com ETF 热门 讨论 A股",
    ],
    "cn_guba": [
        "site:eastmoney.com 股吧 A股 热门 板块",
        "site:eastmoney.com 股吧 ETF 热门 讨论",
    ],
    "cn_10jqka_forum": [
        "site:10jqka.com.cn A股 社区 热门 板块",
        "site:10jqka.com.cn ETF 社区 热门 讨论",
    ],
    "global_fred": [
        "site:fred.stlouisfed.org FRED CPI rates latest",
        "site:fred.stlouisfed.org SOFR treasury yield latest",
    ],
    "global_fed": [
        "site:federalreserve.gov FOMC latest statement",
        "site:federalreserve.gov federal reserve latest policy",
    ],
    "global_bls": [
        "site:bls.gov CPI latest release",
        "site:bls.gov payroll employment latest release",
    ],
    "global_bea": [
        "site:bea.gov GDP latest release",
        "site:bea.gov PCE latest release",
    ],
    "global_eia": [
        "site:eia.gov crude oil inventory latest",
        "site:eia.gov energy outlook latest",
    ],
    "global_reuters": [
        "site:reuters.com/markets semiconductors latest markets",
        "site:reuters.com/markets fed inflation markets latest",
    ],
    "global_bloomberg": [
        "site:bloomberg.com/markets sectors latest",
        "site:bloomberg.com/markets fed inflation latest",
    ],
    "global_ft": [
        "site:ft.com inflation markets latest",
        "site:ft.com semiconductors AI latest",
    ],
    "global_cme": [
        "site:cmegroup.com fedwatch latest",
        "site:cmegroup.com treasury futures latest",
    ],
    "global_imf": [
        "site:imf.org data outlook latest",
        "site:imf.org world economic outlook latest",
    ],
    "global_wallstreetcn": [
        "site:wallstreetcn.com 美联储 通胀 最新",
        "site:wallstreetcn.com 半导体 AI 最新",
    ],
    "global_cnbc": [
        "site:cnbc.com fed inflation latest",
        "site:cnbc.com semiconductor latest",
    ],
    "global_wsj": [
        "site:wsj.com markets inflation latest",
        "site:wsj.com semiconductors latest",
    ],
}


@dataclass
class ProbeItem:
    query: str
    matched_results: int
    total_results: int
    top_urls: List[str]


@dataclass
class ProbeResult:
    source_id: str
    source_name: str
    region: str
    category: str
    tier: str
    mode: str
    enabled: bool
    status: str
    recommendation: str
    matched_results: int
    total_results: int
    notes: str
    items: List[ProbeItem]


def _extract_expected_domains(source: SourceDefinition) -> List[str]:
    out: List[str] = []
    if source.base_url:
        try:
            netloc = urllib.parse.urlparse(source.base_url).netloc.lower().strip()
            if netloc:
                out.append(netloc)
                if netloc.startswith("www."):
                    out.append(netloc[4:])
        except Exception:
            pass
    return sorted(set(out))


def _duckduckgo_search(query: str, timeout: int = DEFAULT_TIMEOUT) -> List[Dict[str, str]]:
    payload = urllib.parse.urlencode({"q": query}).encode("utf-8")
    req = urllib.request.Request(
        DUCKDUCKGO_HTML,
        data=payload,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; AI-TraderSourceProbe/1.0)",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        html = resp.read().decode("utf-8", errors="replace")

    import re

    pattern = re.compile(r'<a[^>]*class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.IGNORECASE)
    results: List[Dict[str, str]] = []
    for href, title_html in pattern.findall(html):
        title = re.sub(r"<[^>]+>", "", title_html).strip()
        if href and title:
            results.append({"title": title, "url": href})
    return results


def _count_domain_matches(urls: Iterable[str], expected_domains: List[str]) -> int:
    if not expected_domains:
        return 0
    matched = 0
    for url in urls:
        netloc = urllib.parse.urlparse(url).netloc.lower().strip()
        if any(domain and domain in netloc for domain in expected_domains):
            matched += 1
    return matched


def _recommendation(*, mode: str, matched: int, total: int, expected_domains: List[str]) -> str:
    if total == 0:
        return "no_result: 需要调整 query，或改为 direct ingestion。"
    if expected_domains and matched == 0:
        if mode == "direct":
            return "search_miss: 当前 search 方式不可靠，更应优先实现 direct ingestion。"
        return "search_weak: 搜得到结果但命中目标站点差，建议优化 query 或改 direct。"
    if matched > 0 and mode == "search":
        return "search_ok: 当前 search 模式可用，后续可继续观察质量。"
    if matched > 0 and mode == "hybrid":
        return "hybrid_ok: 当前 search 有命中，后续仍可考虑 direct 增强。"
    if matched > 0 and mode == "direct":
        return "search_probe_ok: 作为 direct 源，搜索探测也能命中，适合后续做专用采集器。"
    return "needs_manual_review"


def probe_source(source: SourceDefinition, timeout: int = DEFAULT_TIMEOUT) -> ProbeResult:
    queries = SITE_QUERY_MAP.get(source.source_id, [])
    expected_domains = _extract_expected_domains(source)
    if not queries:
        return ProbeResult(
            source_id=source.source_id,
            source_name=source.name,
            region=source.region,
            category=source.category,
            tier=source.tier,
            mode=source.mode,
            enabled=source.enabled,
            status="no_query",
            recommendation="缺少 probe query，需要先补充 query 模板。",
            matched_results=0,
            total_results=0,
            notes="No query templates configured.",
            items=[],
        )

    items: List[ProbeItem] = []
    total_results = 0
    matched_results = 0
    errors: List[str] = []

    for query in queries:
        try:
            rows = _duckduckgo_search(query, timeout=timeout)
            urls = [row.get("url", "") for row in rows[:5]]
            matched = _count_domain_matches(urls, expected_domains)
            total_results += len(rows)
            matched_results += matched
            items.append(
                ProbeItem(
                    query=query,
                    matched_results=matched,
                    total_results=len(rows),
                    top_urls=urls,
                )
            )
            time.sleep(0.3)
        except Exception as exc:
            errors.append(f"{query}: {exc}")
            items.append(
                ProbeItem(
                    query=query,
                    matched_results=0,
                    total_results=0,
                    top_urls=[],
                )
            )

    if total_results == 0 and errors:
        status = "error"
        notes = "; ".join(errors[:3])
    elif total_results == 0:
        status = "no_result"
        notes = "Search returned no results for configured queries."
    elif matched_results == 0 and expected_domains:
        status = "mismatch"
        notes = f"No URLs matched expected domains: {', '.join(expected_domains)}"
    else:
        status = "ok"
        notes = f"Expected domains: {', '.join(expected_domains) if expected_domains else 'n/a'}"

    return ProbeResult(
        source_id=source.source_id,
        source_name=source.name,
        region=source.region,
        category=source.category,
        tier=source.tier,
        mode=source.mode,
        enabled=source.enabled,
        status=status,
        recommendation=_recommendation(
            mode=source.mode,
            matched=matched_results,
            total=total_results,
            expected_domains=expected_domains,
        ),
        matched_results=matched_results,
        total_results=total_results,
        notes=notes,
        items=items,
    )


def _filter_sources(args: argparse.Namespace) -> List[SourceDefinition]:
    return list_sources(
        region=args.region,
        category=args.category,
        tier=args.tier,
        enabled_only=args.enabled_only,
    )


def _print_human(results: List[ProbeResult]) -> None:
    for result in results:
        print(f"[{result.status.upper()}] {result.source_id} | {result.source_name} | tier={result.tier} | mode={result.mode}")
        print(f"  matched={result.matched_results} total={result.total_results}")
        print(f"  recommendation={result.recommendation}")
        print(f"  notes={result.notes}")
        for item in result.items:
            print(f"    - query={item.query}")
            print(f"      matched={item.matched_results} total={item.total_results}")
            if item.top_urls:
                print(f"      top={item.top_urls[0]}")
        print()


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe curated RAG sources.")
    parser.add_argument("--region", default=None, help="Filter by region, e.g. CN or GLOBAL")
    parser.add_argument("--category", default=None, help="Filter by category, e.g. media/policy/forum")
    parser.add_argument("--tier", default=None, help="Filter by tier, e.g. S/A/B")
    parser.add_argument("--enabled-only", action="store_true", help="Only probe enabled sources")
    parser.add_argument("--source-id", default=None, help="Probe a single source_id")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of human-readable text")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help="Per-query timeout in seconds")
    args = parser.parse_args()

    sources = _filter_sources(args)
    if args.source_id:
        sources = [src for src in sources if src.source_id == args.source_id]

    results = [probe_source(source, timeout=max(3, int(args.timeout))) for source in sources]
    if args.json:
        print(json.dumps([asdict(item) for item in results], ensure_ascii=False, indent=2))
    else:
        _print_human(results)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
