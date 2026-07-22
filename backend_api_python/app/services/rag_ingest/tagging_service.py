"""Unified sector and ETF tagging helpers for first-stage A-share RAG.

Second-stage rule enhancement:
1. larger sector keyword dictionaries
2. title/body weighted scoring
3. multi-signal attribution instead of simple keyword hit

The goal is still lightweight and deterministic, but strong enough to turn
financial text into usable sector evidence for weekly sector rotation reports.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List


INDUSTRY_KEYWORDS: Dict[str, List[str]] = {
    "半导体": [
        "半导体", "芯片", "晶圆", "光刻", "封装", "存储芯片", "先进制程", "晶圆代工", "EDA", "HBM", "NAND", "DRAM",
        "硅片", "设备", "刻蚀", "光刻胶", "模拟芯片", "MCU", "国产替代",
    ],
    "算力": [
        "算力", "光模块", "CPO", "GPU", "AI服务器", "液冷", "数据中心", "英伟达", "铜缆", "交换机", "高速连接",
        "算力租赁", "AIDC", "光通信", "InfiniBand", "AI硬件", "服务器链",
    ],
    "新能源车": [
        "新能源车", "锂电", "电池", "充电桩", "智驾", "智能驾驶", "汽车链", "固态电池", "整车", "电驱", "热管理",
        "电解液", "正极", "负极", "隔膜",
    ],
    "券商": ["券商", "证券", "两融", "投行", "资本市场", "并购重组", "IPO", "财富管理", "经纪业务", "北交所"],
    "军工": ["军工", "航空发动机", "卫星", "导弹", "国防", "兵器", "航天", "舰船", "低空防务"],
    "医药": ["医药", "创新药", "CRO", "医疗器械", "生物制药", "减肥药", "ADC", "CXO", "创新医疗"],
    "消费电子": ["消费电子", "苹果链", "折叠屏", "面板", "手机链", "电子代工", "AR眼镜", "VR", "果链", "折叠机"],
    "电力设备": ["电网", "特高压", "储能", "风电", "光伏", "新型能源体系", "电力设备", "变压器", "逆变器", "电改", "配网"],
    "黄金有色": ["黄金", "有色", "铜价", "铝价", "稀土", "贵金属", "工业金属", "锑", "锂矿", "小金属"],
    "石油": ["原油", "油价", "石油", "天然气", "炼化", "中海油", "中石油", "中石化"],
    "化工": ["化工", "石化", "煤化工", "烯烃", "PX", "尿素", "化肥", "农药", "化学制品", "化纤", "塑料"],
    "银行": ["银行", "存款利率", "信贷", "净息差", "房贷", "LPR", "拨备", "城商行", "农商行"],
    "保险": ["保险", "险资", "寿险", "财险", "车险", "健康险"],
    "计算机": ["计算机", "软件", "信创", "操作系统", "数据库", "中间件", "信息安全", "国产软件"],
    "通信": ["通信", "5G", "6G", "卫星通信", "光缆", "基站", "运营商", "物联网"],
    "传媒": ["传媒", "游戏", "影视", "广告", "出版", "短剧", "IP", "院线"],
    "食品饮料": ["白酒", "茅台", "食品", "饮料", "乳业", "啤酒", "调味品", "预制菜"],
    "房地产": ["房地产", "地产", "楼盘", "房价", "销售面积", "土拍", "开发商", "物业"],
    "钢铁": ["钢铁", "钢材", "螺纹钢", "铁矿石", "高炉", "产能", "粗钢"],
    "煤炭": ["煤炭", "煤价", "焦煤", "焦炭", "动力煤", "煤电"],
    "光伏": ["光伏", "太阳能", "硅料", "硅片", "组件", "逆变器", "分布式", "PERC", "TOPCon"],
    "汽车": ["汽车", "乘用车", "商用车", "重卡", "轻卡", "经销商", "车市"],
    "机械": ["机械", "工程机械", "挖掘机", "装载机", "工业母机", "数控机床", "轨交", "油服"],
    "农业": ["农业", "猪肉", "种植", "养殖", "种业", "饲料", "水产", "粮食"],
    "家电": ["家电", "空调", "冰箱", "洗衣机", "白电", "黑电", "厨电", "扫地机"],
    "旅游": ["旅游", "景区", "酒店", "免税", "出境游", "航空", "机场"],
    "基建": ["基建", "铁路", "公路", "水利", "地下管网", "保障房", "旧改", "城中村"],
    "环保": ["环保", "环保设备", "污水处理", "固废", "大气治理", "碳中和", "碳交易"],
    "建材": ["建材", "水泥", "玻璃", "防水", "管材", "石膏板", "涂料"],
}


THEME_KEYWORDS: Dict[str, List[str]] = {
    "人工智能应用": ["AI应用", "AIGC", "大模型", "AI Agent", "智能体", "办公AI", "AI软件"],
    "机器人": ["机器人", "人形机器人", "伺服", "减速器", "丝杠", "机器视觉", "工业机器人"],
    "低空经济": ["低空经济", "低空", "eVTOL", "飞行汽车", "无人机", "通航"],
    "数据要素": ["数据要素", "数据资产", "数据确权", "数据交易", "公共数据", "可信数据空间"],
    "高股息红利": ["红利", "高股息", "央企红利", "股息率", "分红"],
}


ETF_KEYWORDS: Dict[str, List[str]] = {
    "512480": ["半导体", "芯片"],
    "515230": ["新能源车", "锂电", "电池"],
    "512000": ["券商", "证券"],
    "515000": ["科技", "芯片", "算力"],
    "588000": ["科创", "半导体", "科技"],
    "159915": ["创业板", "成长", "科技"],
    "159949": ["创业板50", "成长", "科技"],
    "159995": ["芯片", "半导体"],
    "516160": ["新能源", "电池", "储能"],
}


def clean_text(text: Any) -> str:
    value = str(text or "")
    value = value.replace("\r", "\n")
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def _score_keywords(text: str, title: str) -> Dict[str, int]:
    text_norm = clean_text(text)
    title_norm = clean_text(title)
    scores: Dict[str, int] = {}
    for sector, keywords in INDUSTRY_KEYWORDS.items():
        score = 0
        for kw in keywords:
            if kw in text_norm:
                score += 1
            if title_norm and kw in title_norm:
                score += 2
        if score > 0:
            scores[sector] = score
    return scores


def extract_sector_tags(text: str, *, title: str = "", top_k: int = 3) -> List[str]:
    scores = _score_keywords(text=text, title=title)
    ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    return [name for name, score in ranked[: max(1, top_k)] if score >= 2]


def extract_theme_tags(text: str, *, title: str = "", top_k: int = 3) -> List[str]:
    text_norm = clean_text(text)
    title_norm = clean_text(title)
    scores: Dict[str, int] = {}
    for theme, keywords in THEME_KEYWORDS.items():
        score = 0
        for kw in keywords:
            if kw in text_norm:
                score += 1
            if title_norm and kw in title_norm:
                score += 2
        if score > 0:
            scores[theme] = score
    ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    return [name for name, score in ranked[: max(1, top_k)] if score >= 2]


def extract_etf_tags(text: str) -> List[str]:
    haystack = clean_text(text)
    out: List[str] = []
    for etf_code, keywords in ETF_KEYWORDS.items():
        if any(keyword in haystack for keyword in keywords):
            out.append(etf_code)
    return out


def build_tags(text: str, *, title: str = "") -> Dict[str, List[str]]:
    industry_tags = extract_sector_tags(text, title=title)
    theme_tags = extract_theme_tags(text, title=title)
    etf_tags = extract_etf_tags("\n".join([title, text] + industry_tags + theme_tags))
    return {
        "sector_tags": industry_tags,
        "industry_tags": industry_tags,
        "theme_tags": theme_tags,
        "etf_tags": etf_tags,
    }
