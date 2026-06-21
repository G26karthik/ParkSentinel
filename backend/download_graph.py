"""
download_graph.py — Overpass-free road graph builder using Geofabrik PBF.

Downloads Karnataka OSM data from Geofabrik (a static HTTP file, no Overpass),
clips it to the Bengaluru bounding box, computes betweenness centrality,
and saves pipeline_output/bengaluru_graph.pkl.

Run once before offline_pipeline.py:
    python download_graph.py
"""

import time
import logging
import requests
import osmnx as ox
import networkx as nx
import joblib
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ── paths ────────────────────────────────────────────────────────────────────
BACKEND_DIR = Path(__file__).parent
OUTPUT_DIR  = BACKEND_DIR.parent / "pipeline_output"
GRAPH_CACHE = OUTPUT_DIR / "bengaluru_graph.pkl"
PBF_PATH    = BACKEND_DIR / "karnataka-latest.osm.pbf"

# Bengaluru bounding box (99th-pct of violation data + 1km buffer)
NORTH, SOUTH, EAST, WEST = 13.1958, 12.8607, 77.7284, 77.4981

# Geofabrik static mirrors (try in order)
GEOFABRIK_URLS = [
    "https://download.geofabrik.de/asia/india/karnataka-latest.osm.pbf",
    "https://osm-internal.download.geofabrik.de/asia/india/karnataka-latest.osm.pbf",
]


def _download_pbf():
    if PBF_PATH.exists() and PBF_PATH.stat().st_size > 10_000_000:
        logger.info("PBF already on disk (%.0f MB). Skipping download.", PBF_PATH.stat().st_size / 1e6)
        return

    for url in GEOFABRIK_URLS:
        logger.info("Downloading Karnataka OSM PBF from: %s", url)
        try:
            headers = {
                "User-Agent": "ParkSentinel/1.0 (hackathon project)",
                "Accept": "application/octet-stream, */*",
            }
            r = requests.get(url, headers=headers, stream=True, timeout=300, allow_redirects=True)
            r.raise_for_status()
            total = int(r.headers.get("content-length", 0))
            logger.info("File size: %.0f MB", total / 1e6)

            downloaded = 0
            t0 = time.time()
            with open(PBF_PATH, "wb") as f:
                for chunk in r.iter_content(chunk_size=1024 * 1024):  # 1MB chunks
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        pct = downloaded / total * 100 if total else 0
                        if downloaded % (10 * 1024 * 1024) < 1024 * 1024:  # every ~10MB
                            logger.info("  %.0f / %.0f MB (%.0f%%)", downloaded / 1e6, total / 1e6, pct)

            size_mb = PBF_PATH.stat().st_size / 1e6
            logger.info("Download complete in %.1fs. File: %.1f MB", time.time() - t0, size_mb)
            if size_mb < 5:
                logger.error("Downloaded file is too small (%.1f MB) — likely an error page.", size_mb)
                PBF_PATH.unlink(missing_ok=True)
                continue
            return
        except Exception as e:
            logger.warning("Failed to download from %s: %s", url, e)
            continue

    raise RuntimeError("All Geofabrik URLs failed. Check your network connection.")


def _build_and_clip_graph():
    logger.info("Parsing PBF and building graph (this reads the full Karnataka file)…")
    t0 = time.time()
    # graph_from_xml reads OSM XML or PBF; loads entire file then we clip
    G_full = ox.graph_from_xml(str(PBF_PATH), simplify=False, retain_all=False)
    logger.info("Full Karnataka graph in %.1fs: %d nodes, %d edges", time.time() - t0, len(G_full.nodes), len(G_full.edges))

    logger.info("Clipping to Bengaluru bounding box…")
    G = ox.truncate.truncate_graph_bbox(G_full, bbox=(NORTH, SOUTH, EAST, WEST))
    G = ox.simplify_graph(G)
    logger.info("Bengaluru graph: %d nodes, %d edges", len(G.nodes), len(G.edges))
    return G


def _compute_betweenness(G):
    logger.info("Adding edge speeds and travel times…")
    G = ox.routing.add_edge_speeds(G)
    G = ox.routing.add_edge_travel_times(G)

    logger.info("Converting to DiGraph…")
    D = ox.convert.to_digraph(G, weight="travel_time")

    k = min(500, len(D.nodes))
    logger.info("Computing betweenness centrality (k=%d) for %d nodes…", k, len(D.nodes))
    t0 = time.time()
    bc = nx.betweenness_centrality(D, k=k, weight="travel_time", normalized=True, seed=42)
    logger.info("Betweenness centrality done in %.1fs", time.time() - t0)
    return G, bc


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if GRAPH_CACHE.exists():
        logger.info("bengaluru_graph.pkl already exists at %s — nothing to do.", GRAPH_CACHE)
        return

    _download_pbf()
    G, bc = _compute_betweenness(_build_and_clip_graph())

    logger.info("Saving graph pkl → %s", GRAPH_CACHE)
    joblib.dump({"graph": G, "betweenness": bc}, GRAPH_CACHE)
    logger.info("=" * 60)
    logger.info("SUCCESS! bengaluru_graph.pkl is ready.")
    logger.info("Now run: python offline_pipeline.py")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
