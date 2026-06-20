"""Quick pipeline smoke test."""

import h3

from anomaly_detector import detect_anomalies
from clustering import add_dominant_violations, compute_h3_aggregation, run_hdbscan_clustering
from data_loader import get_clean_violations_df, get_data_stats, load_csv_to_duckdb
from osm_enricher import enrich_clusters_with_road_weights, enrich_h3_with_road_weights
from scoring import score_clusters, score_h3_cells

conn = load_csv_to_duckdb()
df = get_clean_violations_df(conn)
print(f"DF: {len(df)} records")

df, clusters = run_hdbscan_clustering(df)
print(f"Clusters: {len(clusters)}")

h3_df = compute_h3_aggregation(df)
df["h3_cell"] = df.apply(
    lambda r: h3.latlng_to_cell(r["latitude"], r["longitude"], 8), axis=1
)
h3_df = add_dominant_violations(h3_df, conn)

total_days = (df["violation_date"].max() - df["violation_date"].min()).days + 1
cw = enrich_clusters_with_road_weights(clusters) if len(clusters) else {}
hw = enrich_h3_with_road_weights(h3_df, max_fetch=20)

if len(clusters):
    clusters = score_clusters(clusters, df, cw, total_days)
h3_df = score_h3_cells(h3_df, df, hw, total_days)

anomalies = detect_anomalies(df)
critical = (h3_df["classification"] == "CRITICAL").sum()
print(f"H3 cells: {len(h3_df)}, Critical: {critical}")
print(f"Anomalies: {len(anomalies)}")
print("Pipeline OK")
conn.close()
