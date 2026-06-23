import time
import logging
import duckdb
import osmnx as ox
import networkx as nx
import joblib
import h3
from pathlib import Path

from config import CACHE_DIR, H3_RESOLUTION
from data_loader import get_clean_violations_df, get_data_stats, load_csv_to_duckdb
from clustering import run_hdbscan_clustering, compute_h3_aggregation, add_dominant_violations
from osm_enricher import enrich_clusters_with_road_weights, enrich_h3_with_road_weights
from scoring import score_clusters, score_h3_cells
from anomaly_detector import detect_anomalies
from forecaster import fit_prophet_forecasts

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

GRAPH_CACHE = CACHE_DIR / "bengaluru_graph.pkl"
PIPELINE_CACHE = CACHE_DIR / "pipeline_state.pkl"

def build_road_graph(conn: duckdb.DuckDBPyConnection):
    """Dynamically pull road graph based on actual violation dataset bounds."""
    logger.info("Computing geographic bounds of dataset...")
    
    # Get exact min/max lat/lon of the violations
    bounds = conn.execute("""
        SELECT 
            quantile_cont(latitude, 0.01) as min_lat, 
            quantile_cont(latitude, 0.99) as max_lat,
            quantile_cont(longitude, 0.01) as min_lon, 
            quantile_cont(longitude, 0.99) as max_lon
        FROM violations_clean
        WHERE latitude BETWEEN 12.0 AND 14.0
        AND longitude BETWEEN 77.0 AND 78.5
    """).fetchone()
    
    min_lat, max_lat, min_lon, max_lon = bounds
    
    # Add a ~1km buffer (1 deg ~ 111km, so 1km ~ 0.009 deg)
    buffer = 0.01
    north = max_lat + buffer
    south = min_lat - buffer
    east = max_lon + buffer
    west = min_lon - buffer
    
    logger.info(f"Building road graph for dataset BBox: N={north:.4f}, S={south:.4f}, E={east:.4f}, W={west:.4f}...")
    start = time.time()

    # ── PKL-FIRST CACHE ─────────────────────────────────────────────────────────
    # If we already downloaded + processed the graph once, just load it.
    if GRAPH_CACHE.exists():
        logger.info("Loading road graph from local pkl cache (no download needed)...")
        cached = joblib.load(GRAPH_CACHE)
        logger.info(f"Graph loaded from cache in {time.time() - start:.2f}s. Nodes: {len(cached['graph'].nodes)}")
        return cached["graph"], cached["betweenness"]
    # ────────────────────────────────────────────────────────────────────────────

    # ── FAST PATH: if no cache exists, skip download and use heuristics ─────────
    # Overpass API is currently rate-limited/unreachable. The pipeline runs fine
    # with heuristic road weights (osm_enricher.py fallback).
    # To attempt a live download, set ATTEMPT_GRAPH_DOWNLOAD=true env var.
    import os
    if os.getenv("ATTEMPT_GRAPH_DOWNLOAD", "false").lower() not in ("1", "true", "yes"):
        logger.warning("ATTEMPT_GRAPH_DOWNLOAD not set — skipping Overpass download. Using heuristic enrichment.")
        logger.warning("Run 'python download_graph.py' separately to build the road graph once Overpass is accessible.")
        return None, None

    # Configure OSMnx — tile into 100 sq km chunks so no single request is too big
    cache_path = Path(__file__).parent / "cache"
    cache_path.mkdir(parents=True, exist_ok=True)
    ox.settings.use_cache = True
    ox.settings.cache_folder = str(cache_path)
    ox.settings.max_query_area_size = 100000000
    # Force TCP socket timeout via requests_kwargs (ox.settings.timeout only sets query timeout)
    ox.settings.requests_kwargs = {"timeout": 30}

    # Mirror rotation — 30s socket timeout each
    OVERPASS_MIRRORS = [
        "https://lz4.overpass-api.de/api/interpreter",
        "https://overpass-api.de/api/interpreter",
        "https://overpass.kumi.systems/api/interpreter",
        "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    ]

    G = None
    for mirror in OVERPASS_MIRRORS:
        try:
            logger.info(f"Trying Overpass mirror: {mirror}")
            ox.settings.overpass_url = mirror
            try:
                G = ox.graph_from_bbox(bbox=(west, south, east, north), network_type="drive", simplify=True)
            except TypeError:
                G = ox.graph_from_bbox(north, south, east, west, network_type="drive", simplify=True)
            logger.info(f"Graph downloaded from {mirror} in {time.time() - start:.2f}s")
            break
        except Exception as e:
            logger.warning(f"Mirror {mirror} failed: {type(e).__name__}")
            continue

    if G is None:
        logger.warning("All Overpass mirrors failed — road graph unavailable. Heuristic fallback will be used.")
        return None, None


    logger.info(f"Graph downloaded in {time.time() - start:.2f}s. Nodes: {len(G.nodes)}")

    logger.info("Adding edge speeds and travel times...")
    G = ox.routing.add_edge_speeds(G)
    G = ox.routing.add_edge_travel_times(G)

    logger.info("Converting to DiGraph...")
    D = ox.convert.to_digraph(G, weight="travel_time")

    # k=500 → ~2 mins on local machine, statistically equivalent to k=5000 for scoring
    k_samples = min(500, len(D.nodes))
    logger.info(f"Computing betweenness centrality (k={k_samples}) for {len(D.nodes)} nodes...")
    start_bc = time.time()
    bc = nx.betweenness_centrality(D, k=k_samples, weight="travel_time", normalized=True, seed=42)
    logger.info(f"Betweenness Centrality computed in {time.time() - start_bc:.2f}s")

    # Save pkl immediately so future runs never need to download again
    GRAPH_CACHE.parent.mkdir(parents=True, exist_ok=True)
    logger.info("Saving graph pkl to %s", GRAPH_CACHE)
    joblib.dump({"graph": G, "betweenness": bc}, GRAPH_CACHE)
    logger.info("Graph pkl saved. Future runs will load from cache (instant).")
    return G, bc

def run_offline_pipeline():
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    logger.info("Starting Offline ML Pipeline...")
    
    start_total = time.time()
    
    # 1. Database ingestion
    logger.info("Step 1: Loading CSV to DuckDB...")
    conn = load_csv_to_duckdb()
    
    # 2. Road Graph — pkl-first (loads from cache or downloads fresh, graceful fallback if offline)
    logger.info("Step 2: Building Road Network Graph (optional — heuristic fallback if unavailable)...")
    try:
        G, bc = build_road_graph(conn)
    except Exception as e:
        logger.warning("Road graph step failed (%s) — using heuristic fallback.", e)
        _G, _bc = None, None
    
    # 3. Main Data load
    logger.info("Step 3: Fetching Clean Data...")
    df = get_clean_violations_df(conn)
    logger.info("Total records: %d", len(df))
    
    # 4. HDBSCAN Clustering
    logger.info("Step 4: Running HDBSCAN Clustering...")
    df, clusters_df = run_hdbscan_clustering(df)
    
    # 5. H3 Aggregation
    logger.info("Step 5: Computing H3 Grid Aggregations...")
    h3_df = compute_h3_aggregation(df, H3_RESOLUTION)
    df["h3_cell"] = df.apply(
        lambda r: h3.latlng_to_cell(r["latitude"], r["longitude"], H3_RESOLUTION),
        axis=1,
    )
    h3_df = add_dominant_violations(h3_df, conn)
    
    total_days = (df["violation_date"].max() - df["violation_date"].min()).days + 1
    
    # 6. OSM Enrichment & Scoring
    logger.info("Step 6: Enriching with Road Centrality and Scoring...")
    cluster_road_weights = {}
    if not clusters_df.empty:
        cluster_road_weights = enrich_clusters_with_road_weights(clusters_df)
        clusters_df = score_clusters(clusters_df, df, cluster_road_weights, total_days)
        
    h3_road_weights = enrich_h3_with_road_weights(h3_df)
    h3_df = score_h3_cells(h3_df, df, h3_road_weights, total_days)
    
    # 7. Anomalies & Forecasting
    logger.info("Step 7: Detecting Anomalies and Fitting Prophet Models...")
    anomalies = detect_anomalies(df)
    forecasts = fit_prophet_forecasts(h3_df, df)
    
    # 8. Stats
    stats = get_data_stats(conn)
    critical_count = int((h3_df["classification"] == "CRITICAL").sum()) if not h3_df.empty else 0
    
    _state = {
        "df": df,
        "clusters_df": clusters_df,
        "h3_df": h3_df,
        "anomalies": anomalies,
        "forecasts": forecasts,
        "stats": stats,
        "critical_count": critical_count,
        "total_days": total_days,
    }
    
    logger.info("Step 8: Caching Final Pipeline State...")
    joblib.dump(_state, PIPELINE_CACHE)
    
    logger.info("=========================================")
    logger.info("OFFLINE PIPELINE COMPLETE in %.2fs", time.time() - start_total)
    logger.info("Total Clusters Found: %d", len(clusters_df))
    logger.info("Critical Zones Found: %d", critical_count)
    logger.info("Artifacts saved to: %s", CACHE_DIR.resolve())
    logger.info("=========================================")

if __name__ == "__main__":
    run_offline_pipeline()
