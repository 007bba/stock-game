from sqlalchemy import create_engine, text
import os

db_url = os.getenv("DATABASE_URL")
engine = create_engine(db_url)

with engine.connect() as conn:
    # 检查raw_minute_bars表结构
    rows = conn.execute(text("""
        SELECT column_name 
        FROM information_schema.columns 
        WHERE table_name = 'raw_minute_bars' 
        ORDER BY ordinal_position
    """)).fetchall()
    print("raw_minute_bars columns:", [r[0] for r in rows])
    
    # 检查数据量
    count = conn.execute(text("SELECT COUNT(*) FROM raw_minute_bars")).fetchone()
    print(f"raw_minute_bars count: {count[0]}")
    
    # 检查market_ticks表数据量
    count = conn.execute(text("SELECT COUNT(*) FROM market_ticks WHERE season_id = 39")).fetchone()
    print(f"market_ticks count for season 39: {count[0]}")
    
    # 检查market_tick_quotes表数据量
    count = conn.execute(text("SELECT COUNT(*) FROM market_tick_quotes WHERE season_id = 39")).fetchone()
    print(f"market_tick_quotes count for season 39: {count[0]}")
