import duckdb
from pathlib import Path
import pandas as pd

CSV_PATH = Path("data/jan_to_may_police_violation_anonymized791b166.csv.gz")

conn = duckdb.connect()
conn.execute(f"CREATE TABLE violations AS SELECT * FROM read_csv_auto('{CSV_PATH}')")

# Filter out obvious bad coordinates
res = conn.execute("""
    SELECT 
        MIN(latitude), MAX(latitude),
        MIN(longitude), MAX(longitude)
    FROM violations
    WHERE latitude BETWEEN 12.0 AND 14.0
    AND longitude BETWEEN 77.0 AND 78.5
""").fetchone()

print(f"Bounding Box: {res}")
