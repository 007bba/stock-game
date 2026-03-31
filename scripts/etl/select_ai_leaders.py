"""筛选 AI 龙头股并创建赛季股票池。

Usage:
    python scripts/etl/select_ai_leaders.py --start-date 2025-12-01 --end-date 2025-12-31 --output ai_leaders.json
"""
from __future__ import annotations

import argparse
import json
import logging
import os
from datetime import date
from decimal import Decimal

import pandas as pd
from dotenv import load_dotenv
from pathlib import Path

# Load .env from project root
ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

try:
    import tushare as ts
except ImportError:
    print("请安装 tushare: pip install tushare")
    raise

LOGGER = logging.getLogger("select_ai_leaders")

# AI 相关概念板块关键词
AI_KEYWORDS = [
    "人工智能", "AI", "ChatGPT", "AIGC", "大模型", "算力",
    "GPU", "芯片", "半导体", "光模块", "CPO", "数据中心",
    "云计算", "智算", "机器人", "智能", "算法", "深度学习",
]

# 知名 AI 龙头股白名单（可作为补充）
AI_WHITE_LIST = [
    "300750.SZ",  # 宁德时代（算力相关）
    "002475.SZ",  # 立讯精密
    "002415.SZ",  # 海康威视
    "300033.SZ",  # 同花顺
    "002230.SZ",  # 科大讯飞
    "300144.SZ",  # 宋城演艺（AI演艺）
    "002405.SZ",  # 四维图新
    "300454.SZ",  # 深信服
    "002416.SZ",  # 爱施德
    "300170.SZ",  # 汉得信息
    "002312.SZ",  # 三泰控股
    "300367.SZ",  # 东方网力
    "002409.SZ",  # 雅克科技
    "300377.SZ",  # 赢时胜
    "002408.SZ",  # 齐翔腾达
]


def get_tushare_pro():
    token = os.getenv("TUSHARE_TOKEN")
    if not token:
        raise RuntimeError("TUSHARE_TOKEN is required")
    try:
        return ts.pro_api(token=token)
    except TypeError:
        ts.set_token(token)
        return ts.pro_api()


def fetch_daily_data(pro, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
    """获取日线数据"""
    try:
        df = pro.daily(ts_code=ts_code, start_date=start_date.replace("-", ""),
                       end_date=end_date.replace("-", ""))
        return df if df is not None and not df.empty else pd.DataFrame()
    except Exception as e:
        LOGGER.warning(f"获取 {ts_code} 日线失败: {e}")
        return pd.DataFrame()


def check_limit_up(df: pd.DataFrame) -> bool:
    """检查是否有涨停"""
    if df.empty:
        return False
    # 涨幅 >= 9.9% 视为涨停（考虑四舍五入）
    df = df.copy()
    df["pct_chg"] = pd.to_numeric(df["pct_chg"], errors="coerce")
    return (df["pct_chg"] >= 9.9).any()


def check_consecutive_limit(df: pd.DataFrame, min_days: int = 2) -> bool:
    """检查是否有连续涨停"""
    if df.empty or len(df) < min_days:
        return False
    df = df.sort_values("trade_date").copy()
    df["pct_chg"] = pd.to_numeric(df["pct_chg"], errors="coerce")
    df["is_limit"] = df["pct_chg"] >= 9.9
    
    consecutive = 0
    for is_limit in df["is_limit"]:
        if is_limit:
            consecutive += 1
            if consecutive >= min_days:
                return True
        else:
            consecutive = 0
    return False


def calc_avg_amount(df: pd.DataFrame) -> float:
    """计算平均成交额"""
    if df.empty:
        return 0.0
    df = df.copy()
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0)
    return float(df["amount"].mean() * 10000)  # Tushare amount 单位是万元


def fetch_concept_stocks(pro, concept_name: str) -> list[str]:
    """获取概念板块成分股"""
    try:
        df = pro.concept_detail(id=concept_name, fields="ts_code")
        if df is not None and not df.empty:
            return df["ts_code"].tolist()
    except Exception as e:
        LOGGER.warning(f"获取概念 {concept_name} 失败: {e}")
    return []


def fetch_all_stocks(pro) -> pd.DataFrame:
    """获取所有A股股票列表"""
    try:
        df = pro.stock_basic(exchange="", list_status="L", fields="ts_code,symbol,name,area,industry,list_date")
        return df if df is not None else pd.DataFrame()
    except Exception as e:
        LOGGER.error(f"获取股票列表失败: {e}")
        return pd.DataFrame()


def select_ai_leaders(pro, start_date: str, end_date: str, top_n: int = 24) -> list[dict]:
    """筛选 AI 龙头股"""
    
    # 获取所有股票
    all_stocks = fetch_all_stocks(pro)
    if all_stocks.empty:
        raise RuntimeError("无法获取股票列表")
    
    LOGGER.info(f"获取到 {len(all_stocks)} 只股票")
    
    # 筛选条件
    candidates = []
    
    start_n = start_date.replace("-", "")
    end_n = end_date.replace("-", "")
    
    for idx, row in all_stocks.iterrows():
        ts_code = row["ts_code"]
        name = row.get("name", "")
        industry = row.get("industry", "")
        
        # 先检查是否在白名单或名称/行业匹配 AI 关键词
        is_ai_related = (
            ts_code in AI_WHITE_LIST or
            any(kw in name.upper() for kw in AI_KEYWORDS) or
            any(kw in str(industry) for kw in ["软件", "电子", "通信", "计算机"])
        )
        
        if not is_ai_related:
            continue
        
        # 获取日线数据
        df = fetch_daily_data(pro, ts_code, start_date, end_date)
        if df.empty:
            continue
        
        # 计算指标
        has_limit = check_limit_up(df)
        has_consecutive = check_consecutive_limit(df, min_days=2)
        avg_amount = calc_avg_amount(df)
        
        # 计算涨幅
        if len(df) >= 2:
            df_sorted = df.sort_values("trade_date")
            first_close = float(df_sorted.iloc[0]["close"])
            last_close = float(df_sorted.iloc[-1]["close"])
            total_return = (last_close - first_close) / first_close * 100
        else:
            total_return = 0.0
        
        # 只保留有涨停或高成交额的股票
        if has_limit or avg_amount >= 500_000_000:  # 5亿日均成交额
            candidates.append({
                "ts_code": ts_code,
                "name": name,
                "industry": industry,
                "has_limit_up": bool(has_limit),
                "has_consecutive_limit": bool(has_consecutive),
                "avg_amount": float(avg_amount),
                "total_return": float(round(total_return, 2)),
                "score": float(
                    (100 if has_consecutive else 0) +
                    (50 if has_limit else 0) +
                    min(avg_amount / 1_000_000_000 * 10, 30) +  # 成交额因子
                    max(total_return, 0) * 0.5  # 涨幅因子
                )
            })
        
        # 进度提示
        if (idx + 1) % 100 == 0:
            LOGGER.info(f"已处理 {idx + 1}/{len(all_stocks)} 只股票，候选 {len(candidates)}")
    
    # 按评分排序
    candidates.sort(key=lambda x: x["score"], reverse=True)
    
    # 返回前 top_n
    return candidates[:top_n]


def main():
    parser = argparse.ArgumentParser(description="筛选 AI 龙头股")
    parser.add_argument("--start-date", required=True, help="开始日期 YYYY-MM-DD")
    parser.add_argument("--end-date", required=True, help="结束日期 YYYY-MM-DD")
    parser.add_argument("--top-n", type=int, default=24, help="返回前 N 只股票")
    parser.add_argument("--output", default="ai_leaders.json", help="输出文件名")
    args = parser.parse_args()
    
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    
    LOGGER.info(f"开始筛选 AI 龙头股: {args.start_date} ~ {args.end_date}")
    
    pro = get_tushare_pro()
    leaders = select_ai_leaders(pro, args.start_date, args.end_date, args.top_n)
    
    # 输出结果
    print(f"\n筛选出 {len(leaders)} 只 AI 龙头股:\n")
    print(f"{'代码':<12} {'名称':<10} {'行业':<8} {'涨停':<6} {'连板':<6} {'日均成交(亿)':<12} {'涨幅%':<8} {'评分':<8}")
    print("-" * 80)
    for s in leaders:
        print(f"{s['ts_code']:<12} {s['name']:<10} {s['industry']:<8} "
              f"{'是' if s['has_limit_up'] else '否':<6} "
              f"{'是' if s['has_consecutive_limit'] else '否':<6} "
              f"{s['avg_amount']/1_000_000_00:.2f}亿    "
              f"{s['total_return']:>6.2f}%   "
              f"{s['score']:>6.1f}")
    
    # 保存到 JSON
    output_path = ROOT / "docs" / "reports" / args.output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(leaders, f, ensure_ascii=False, indent=2)
    
    print(f"\n已保存到: {output_path}")


if __name__ == "__main__":
    main()
