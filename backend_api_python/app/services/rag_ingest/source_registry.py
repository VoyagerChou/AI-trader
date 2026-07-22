"""Curated source registry for the first-stage A-share RAG system.

This module defines high-value domestic and overseas sources with explicit
priority, ingestion mode, and research purpose. Ingestors should consume this
registry instead of hardcoding source lists.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass(frozen=True)
class SourceDefinition:
    """Static definition of an ingestion source."""

    source_id: str
    name: str
    region: str
    category: str
    tier: str
    mode: str
    priority: int
    enabled: bool
    rationale: str
    signal_types: tuple[str, ...] = ()
    notes: str = ""
    base_url: str = ""


SOURCES: tuple[SourceDefinition, ...] = (
    SourceDefinition(
        source_id="cn_csrc",
        name="中国证监会",
        region="CN",
        category="policy",
        tier="S",
        mode="direct",
        priority=100,
        enabled=True,
        rationale="资本市场监管、基金规则、信息披露制度等一手政策源。",
        signal_types=("policy", "regulation", "fund_rules"),
        base_url="http://www.csrc.gov.cn/csrc/",
    ),
    SourceDefinition(
        source_id="cn_sse",
        name="上海证券交易所",
        region="CN",
        category="exchange",
        tier="S",
        mode="direct",
        priority=99,
        enabled=True,
        rationale="沪市公告、基金公告、ETF规则与科创板制度的重要官方来源。",
        signal_types=("announcement", "etf_notice", "exchange_rule"),
        base_url="https://www.sse.com.cn/",
    ),
    SourceDefinition(
        source_id="cn_szse",
        name="深圳证券交易所",
        region="CN",
        category="exchange",
        tier="S",
        mode="direct",
        priority=98,
        enabled=True,
        rationale="深市公告、创业板、基金公告与交易所层面规则的重要官方来源。",
        signal_types=("announcement", "etf_notice", "exchange_rule"),
        base_url="https://www.szse.cn/",
    ),
    SourceDefinition(
        source_id="cn_cninfo",
        name="巨潮资讯",
        region="CN",
        category="disclosure",
        tier="S",
        mode="direct",
        priority=97,
        enabled=True,
        rationale="法定信息披露聚合入口，对上市公司和基金公告最具基础性价值。",
        signal_types=("disclosure", "fund_notice", "company_notice"),
        base_url="http://www.cninfo.com.cn/",
    ),
    SourceDefinition(
        source_id="cn_sse_etf",
        name="上交所 ETF 专栏",
        region="CN",
        category="etf_notice",
        tier="S",
        mode="direct",
        priority=96,
        enabled=True,
        rationale="ETF产品、规则、申购赎回清单和基金公告的重要入口。",
        signal_types=("etf_notice", "etf_rule", "pcf"),
        base_url="https://etf.sse.com.cn/",
    ),
    SourceDefinition(
        source_id="cn_cls",
        name="财联社",
        region="CN",
        category="media",
        tier="S",
        mode="search",
        priority=95,
        enabled=True,
        rationale="A股快讯能力强，适合捕捉盘中异动、政策转述与热点板块线索。",
        signal_types=("fast_news", "sector_heat", "market_breaking"),
        base_url="https://www.cls.cn/",
    ),
    SourceDefinition(
        source_id="cn_ndrc",
        name="国家发展改革委",
        region="CN",
        category="policy",
        tier="A",
        mode="direct",
        priority=90,
        enabled=True,
        rationale="产业政策、重大项目和宏观导向对板块轮动影响显著。",
        signal_types=("policy", "industry_support", "macro_guidance"),
        base_url="https://www.ndrc.gov.cn/",
    ),
    SourceDefinition(
        source_id="cn_miit",
        name="工业和信息化部",
        region="CN",
        category="policy",
        tier="A",
        mode="direct",
        priority=89,
        enabled=True,
        rationale="对半导体、算力、通信、新能源车等科技制造方向尤为关键。",
        signal_types=("policy", "industry_guidance", "technology"),
        base_url="https://www.miit.gov.cn/",
    ),
    SourceDefinition(
        source_id="cn_nea",
        name="国家能源局",
        region="CN",
        category="policy",
        tier="A",
        mode="direct",
        priority=88,
        enabled=True,
        rationale="能源、电力、储能、新型电力系统相关政策的重要信源。",
        signal_types=("energy_policy", "power_grid", "renewable"),
        base_url="https://www.nea.gov.cn/",
    ),
    SourceDefinition(
        source_id="cn_stcn",
        name="证券时报 / e公司",
        region="CN",
        category="media",
        tier="A",
        mode="search",
        priority=87,
        enabled=True,
        rationale="上市公司和板块跟踪价值高，适合作为正式投研媒体层的重要补充。",
        signal_types=("company_news", "sector_commentary", "market_theme"),
        base_url="https://www.stcn.com/",
    ),
    SourceDefinition(
        source_id="cn_cs",
        name="中国证券报 / 中证网",
        region="CN",
        category="media",
        tier="A",
        mode="search",
        priority=86,
        enabled=True,
        rationale="偏权威、正式，基金、券商与资本市场制度相关内容价值较高。",
        signal_types=("capital_market", "fund", "brokerage"),
        base_url="https://www.cs.com.cn/",
    ),
    SourceDefinition(
        source_id="cn_cnstock",
        name="上海证券报 / 中国证券网",
        region="CN",
        category="media",
        tier="A",
        mode="search",
        priority=85,
        enabled=True,
        rationale="政策、产业资讯和沪市相关内容较有价值，适合做正式补充源。",
        signal_types=("policy_commentary", "industry_news", "market_theme"),
        base_url="https://www.cnstock.com/",
    ),
    SourceDefinition(
        source_id="cn_fund_company",
        name="基金公司官网公告",
        region="CN",
        category="etf_notice",
        tier="A",
        mode="direct",
        priority=84,
        enabled=True,
        rationale="ETF/基金产品信息更直接，但来源分散，适合第二阶段接入。",
        signal_types=("fund_notice", "product_change", "manager_commentary"),
        notes="建议后续拆分为多家重点基金公司子源。",
    ),
    SourceDefinition(
        source_id="cn_wallstreetcn",
        name="华尔街见闻",
        region="CN",
        category="media",
        tier="B",
        mode="search",
        priority=70,
        enabled=True,
        rationale="全球宏观和科技链条的中文桥接层有价值，但不应替代官方/法定/快讯主源。",
        signal_types=("macro", "global_tech", "market_commentary"),
        base_url="https://wallstreetcn.com/",
        notes="更适合作为宏观与海外市场补充源。",
    ),
    SourceDefinition(
        source_id="cn_eastmoney_news",
        name="东方财富财经快讯",
        region="CN",
        category="media",
        tier="B",
        mode="search",
        priority=69,
        enabled=True,
        rationale="覆盖广但聚合色彩较强，适合作为补充而非核心判断源。",
        signal_types=("market_breadth", "headline_summary", "retail_attention"),
        base_url="https://kuaixun.eastmoney.com/",
    ),
    SourceDefinition(
        source_id="cn_xueqiu",
        name="雪球",
        region="CN",
        category="forum",
        tier="B",
        mode="hybrid",
        priority=60,
        enabled=True,
        rationale="社区讨论质量参差不齐，但适合做主题热度与ETF讨论的辅助情绪层。",
        signal_types=("sentiment", "topic_heat", "investor_discussion"),
        base_url="https://xueqiu.com/",
        notes="更适合第二阶段做情绪指标，不适合作为主判断源。",
    ),
    SourceDefinition(
        source_id="cn_guba",
        name="东方财富股吧",
        region="CN",
        category="forum",
        tier="B",
        mode="hybrid",
        priority=58,
        enabled=True,
        rationale="散户情绪极强，可作为反向情绪和噪声监测层。",
        signal_types=("retail_sentiment", "heat_spike", "contrarian_signal"),
        base_url="http://mguba.eastmoney.com/mguba/",
        notes="噪声高，仅建议用于情绪指标。",
    ),
    SourceDefinition(
        source_id="cn_10jqka_forum",
        name="同花顺社区",
        region="CN",
        category="forum",
        tier="B",
        mode="hybrid",
        priority=56,
        enabled=False,
        rationale="有一定技术派讨论价值，但整体不建议第一阶段纳入。",
        signal_types=("retail_sentiment", "technical_discussion"),
        base_url="https://www.10jqka.com.cn/",
    ),
    SourceDefinition(
        source_id="global_fred",
        name="FRED",
        region="GLOBAL",
        category="macro_data",
        tier="S",
        mode="direct",
        priority=100,
        enabled=True,
        rationale="海外宏观主入口，利率、通胀、就业、流动性、美元相关序列覆盖极强。",
        signal_types=("rates", "inflation", "employment", "liquidity", "fx"),
        base_url="https://fred.stlouisfed.org/",
    ),
    SourceDefinition(
        source_id="global_fed",
        name="Federal Reserve",
        region="GLOBAL",
        category="macro_policy",
        tier="S",
        mode="direct",
        priority=99,
        enabled=True,
        rationale="美联储政策对全球风险资产和A股风格传导最强。",
        signal_types=("fomc", "policy", "liquidity", "rate_guidance"),
        base_url="https://www.federalreserve.gov/",
    ),
    SourceDefinition(
        source_id="global_bls",
        name="BLS",
        region="GLOBAL",
        category="macro_data",
        tier="S",
        mode="direct",
        priority=98,
        enabled=True,
        rationale="CPI、PPI、非农和就业数据是全球风格切换的核心锚。",
        signal_types=("cpi", "ppi", "payrolls", "labor"),
        base_url="https://www.bls.gov/",
    ),
    SourceDefinition(
        source_id="global_bea",
        name="BEA",
        region="GLOBAL",
        category="macro_data",
        tier="S",
        mode="direct",
        priority=97,
        enabled=True,
        rationale="GDP、消费、收入与PCE等数据对A股出口链和成长风格都有映射。",
        signal_types=("gdp", "consumption", "income", "pce"),
        base_url="https://www.bea.gov/",
    ),
    SourceDefinition(
        source_id="global_eia",
        name="EIA",
        region="GLOBAL",
        category="commodity_data",
        tier="S",
        mode="direct",
        priority=96,
        enabled=True,
        rationale="原油、天然气和能源供需数据对化工、石化、电力等板块很关键。",
        signal_types=("oil", "gas", "inventory", "energy"),
        base_url="https://www.eia.gov/",
    ),
    SourceDefinition(
        source_id="global_reuters",
        name="Reuters Markets",
        region="GLOBAL",
        category="media",
        tier="A",
        mode="search",
        priority=92,
        enabled=True,
        rationale="全球市场快讯、中性程度高，适合补海外突发、商品和科技链条事件。",
        signal_types=("breaking_news", "macro", "commodities", "global_markets"),
        base_url="https://www.reuters.com/markets/",
    ),
    SourceDefinition(
        source_id="global_bloomberg",
        name="Bloomberg Markets",
        region="GLOBAL",
        category="media",
        tier="A",
        mode="search",
        priority=90,
        enabled=False,
        rationale="金融市场细节和资产联动信息价值极高，但付费墙和接入成本较高。",
        signal_types=("rates", "sectors", "global_markets", "technology"),
        base_url="https://www.bloomberg.com/markets",
        notes="建议后续有稳定接入方式后再启用。",
    ),
    SourceDefinition(
        source_id="global_ft",
        name="Financial Times",
        region="GLOBAL",
        category="media",
        tier="A",
        mode="search",
        priority=88,
        enabled=False,
        rationale="全球宏观与国际产业链分析质量高，适合做中期逻辑补充。",
        signal_types=("macro", "global_policy", "industry_chain"),
        base_url="https://www.ft.com/",
        notes="更偏分析型，时效弱于快讯型媒体。",
    ),
    SourceDefinition(
        source_id="global_cme",
        name="CME / 利率预期相关数据",
        region="GLOBAL",
        category="market_data",
        tier="A",
        mode="direct",
        priority=87,
        enabled=False,
        rationale="利率预期与衍生品市场定价对A股风格、黄金和商品影响明显。",
        signal_types=("rate_expectation", "futures", "risk_sentiment"),
        base_url="https://www.cmegroup.com/",
    ),
    SourceDefinition(
        source_id="global_imf",
        name="IMF Data",
        region="GLOBAL",
        category="macro_data",
        tier="A",
        mode="direct",
        priority=85,
        enabled=False,
        rationale="全球与跨国宏观背景数据完整，适合中长期宏观背景补充。",
        signal_types=("global_macro", "country_comparison", "fiscal"),
        base_url="https://www.imf.org/en/data",
    ),
    SourceDefinition(
        source_id="global_wallstreetcn",
        name="华尔街见闻（海外补充视角）",
        region="GLOBAL",
        category="media",
        tier="B",
        mode="search",
        priority=70,
        enabled=True,
        rationale="适合作为中文海外宏观和全球科技叙事补充层，而非底层原始信源。",
        signal_types=("macro", "global_tech", "market_wrap"),
        base_url="https://wallstreetcn.com/",
    ),
    SourceDefinition(
        source_id="global_cnbc",
        name="CNBC",
        region="GLOBAL",
        category="media",
        tier="B",
        mode="search",
        priority=66,
        enabled=False,
        rationale="美股盘中快讯和科技股情绪有价值，但噪声较高，不宜优先系统接入。",
        signal_types=("us_equity", "tech_sentiment", "intraday_news"),
        base_url="https://www.cnbc.com/",
    ),
    SourceDefinition(
        source_id="global_wsj",
        name="Wall Street Journal",
        region="GLOBAL",
        category="media",
        tier="B",
        mode="search",
        priority=64,
        enabled=False,
        rationale="商业与公司层报道有价值，但对第一阶段A股板块轮动不是最高优先。",
        signal_types=("business", "company_news", "macro_commentary"),
        base_url="https://www.wsj.com/",
    ),
)


def list_sources(
    *,
    region: Optional[str] = None,
    category: Optional[str] = None,
    tier: Optional[str] = None,
    enabled_only: bool = False,
) -> List[SourceDefinition]:
    items = list(SOURCES)
    if region:
        items = [item for item in items if item.region == region]
    if category:
        items = [item for item in items if item.category == category]
    if tier:
        items = [item for item in items if item.tier == tier]
    if enabled_only:
        items = [item for item in items if item.enabled]
    return sorted(items, key=lambda item: (-item.priority, item.source_id))


def get_source(source_id: str) -> Optional[SourceDefinition]:
    for item in SOURCES:
        if item.source_id == source_id:
            return item
    return None


def group_sources_by_region() -> Dict[str, List[SourceDefinition]]:
    out: Dict[str, List[SourceDefinition]] = {}
    for item in sorted(SOURCES, key=lambda source: (-source.priority, source.source_id)):
        out.setdefault(item.region, []).append(item)
    return out


def group_sources_by_category() -> Dict[str, List[SourceDefinition]]:
    out: Dict[str, List[SourceDefinition]] = {}
    for item in sorted(SOURCES, key=lambda source: (-source.priority, source.source_id)):
        out.setdefault(item.category, []).append(item)
    return out
