import sqlite3
for db_path in [
    r"<project_root>\data\raw\core.db",
    r"<project_root>\data\messages.db",
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
