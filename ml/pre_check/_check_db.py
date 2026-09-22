import sqlite3
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
for db_path in [
    PROJECT_ROOT / "data" / "raw" / "core.db",
    PROJECT_ROOT / "data" / "messages.db",
]:
    try:
        conn = sqlite3.connect(db_path)
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        print(f"\n{db_path}:")
        print(f"  Tables: {tables}")
        for t in tables:
            cols = [r[1] for r in conn.execute(f"PRAGMA table_info({t})").fetchall()]
            cnt = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            print(f"    {t} ({cnt} rows): {cols[:12]}")
        conn.close()
    except Exception as e:
        print(f"\n{db_path}: ERROR - {e}")
