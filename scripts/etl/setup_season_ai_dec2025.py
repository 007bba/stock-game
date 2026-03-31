"""设置 AI 龙头股赛季并导入数据。

Usage:
    python scripts/etl/setup_season_ai_dec2025.py
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

# Load .env from project root
ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

LOGGER = logging.getLogger("setup_season")


def get_engine():
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required")
    return create_engine(database_url, future=True)


def load_ai_leaders():
    """加载筛选出的 AI 龙头股列表"""
    json_path = ROOT / "docs" / "reports" / "ai_leaders_dec2025.json"
    if not json_path.exists():
        raise FileNotFoundError(f"找不到文件: {json_path}")
    
    with open(json_path, "r", encoding="utf-8") as f:
        return json.load(f)


def setup_season():
    """设置 AI 龙头股赛季"""
    engine = get_engine()
    leaders = load_ai_leaders()
    
    with engine.begin() as conn:
        # 1. 创建赛季记录
        LOGGER.info("创建赛季记录...")
        result = conn.execute(
            text("""
                INSERT INTO seasons (season_code, season_name, status, total_game_days)
                VALUES ('AI_DEC2025', '2025年12月AI龙头股训练赛季', 'draft', 10)
                ON CONFLICT (season_code)
                DO UPDATE SET season_name = EXCLUDED.season_name
                RETURNING id
            """)
        )
        season_id = int(result.fetchone()[0])
        LOGGER.info(f"赛季 ID: {season_id}")
        
        # 2. 写入股票池（前12只作为龙头，中间8只跟风，后4只趋势）
        LOGGER.info("写入股票池...")
        for idx, stock in enumerate(leaders):
            # 前12只龙头
            if idx < 12:
                role = "leader"
            # 中间8只跟风
            elif idx < 20:
                role = "follower"
            # 后4只趋势
            else:
                role = "trend"
            
            conn.execute(
                text("""
                    INSERT INTO season_universe (
                        season_id, ts_code, role, event_tag, rank_in_theme, labels
                    ) VALUES (
                        :season_id, :ts_code, CAST(:role AS market_role), :event_tag, :rank, :labels
                    )
                    ON CONFLICT (season_id, ts_code)
                    DO UPDATE SET
                        role = EXCLUDED.role,
                        event_tag = EXCLUDED.event_tag,
                        rank_in_theme = EXCLUDED.rank_in_theme,
                        labels = EXCLUDED.labels
                """),
                {
                    "season_id": season_id,
                    "ts_code": stock["ts_code"],
                    "role": role,
                    "event_tag": "AI_龙头",
                    "rank": idx + 1,
                    "labels": [stock["industry"], "AI", "2025Q4"],
                },
            )
        
        LOGGER.info(f"已写入 {len(leaders)} 只股票到股票池")
        
        # 3. 查询当前股票池
        result = conn.execute(
            text("""
                SELECT ts_code, role, rank_in_theme
                FROM season_universe
                WHERE season_id = :season_id
                ORDER BY rank_in_theme
            """),
            {"season_id": season_id},
        )
        rows = result.fetchall()
        
        print(f"\n赛季 {season_id} 股票池（共 {len(rows)} 只）：\n")
        print(f"{'序号':<6} {'代码':<12} {'角色':<10}")
        print("-" * 30)
        for row in rows:
            print(f"{row[2]:<6} {row[0]:<12} {row[1]:<10}")
        
        return season_id


def run_etl(season_id: int):
    """运行 ETL 导入数据"""
    import subprocess
    import sys
    
    start_date = "2025-12-01"
    end_date = "2025-12-31"
    
    LOGGER.info(f"\n开始 ETL 导入: {start_date} ~ {end_date}")
    
    # 运行 ETL pipeline
    script_path = ROOT / "scripts" / "etl" / "tushare_pipeline.py"
    cmd = [
        sys.executable,
        str(script_path),
        "--season-id", str(season_id),
        "--start-date", start_date,
        "--end-date", end_date,
        "--mode", "all",
    ]
    
    LOGGER.info(f"执行命令: {' '.join(cmd)}")
    subprocess.run(cmd, check=True)
    
    LOGGER.info("ETL 导入完成")


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s"
    )
    
    print("=" * 60)
    print("设置 AI 龙头股训练赛季")
    print("=" * 60)
    
    # 1. 设置赛季
    season_id = setup_season()
    
    # 2. 运行 ETL
    run_etl(season_id)
    
    print("\n" + "=" * 60)
    print("设置完成！")
    print("=" * 60)
    print(f"\n赛季 ID: {season_id}")
    print(f"时间窗口: 2025-12-01 ~ 2025-12-31")
    print(f"股票数量: 24 只")
    print("\n下一步：在前端界面加入该赛季开始训练")


if __name__ == "__main__":
    main()
