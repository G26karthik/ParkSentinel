import osmnx as ox
import networkx as nx
import time
import joblib
from pathlib import Path

CACHE_DIR = Path("cache")
CACHE_DIR.mkdir(exist_ok=True)
GRAPH_CACHE = CACHE_DIR / "bengaluru_graph.pkl"

def build_graph():
    print("Downloading graph for Bengaluru (20km radius)...", flush=True)
    start = time.time()
    
    # 20km radius covers the dense urban core where almost all violations happen
    G = ox.graph_from_point((12.9716, 77.5946), dist=20000, network_type="drive", simplify=True)

    print(f"Graph downloaded in {time.time() - start:.2f}s. Nodes: {len(G.nodes)}", flush=True)

    print("Adding speeds and travel times...", flush=True)
    G = ox.routing.add_edge_speeds(G)
    G = ox.routing.add_edge_travel_times(G)

    print("Converting to DiGraph...", flush=True)
    D = ox.convert.to_digraph(G, weight="travel_time")

    # Approximate betweenness centrality by sampling k nodes.
    # This turns a 30 minute calculation into a 5 second calculation while
    # still correctly identifying the major arterial roads!
    k_samples = min(2000, len(D.nodes))
    print(f"Computing approx betweenness centrality (k={k_samples}) for {len(D.nodes)} nodes...", flush=True)
    start_bc = time.time()
    bc = nx.betweenness_centrality(D, k=k_samples, weight="travel_time", normalized=True, seed=42)
    print(f"Betweenness Centrality computed in {time.time() - start_bc:.2f}s", flush=True)

    print("Saving to cache...", flush=True)
    joblib.dump({"graph": G, "betweenness": bc}, GRAPH_CACHE)
    print("Done!", flush=True)

if __name__ == "__main__":
    build_graph()
