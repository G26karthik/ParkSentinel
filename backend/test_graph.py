import osmnx as ox
import time

LAT_MIN, LAT_MAX = 12.7, 13.4
LON_MIN, LON_MAX = 77.3, 77.9

print("Downloading graph...")
start = time.time()
G = ox.graph_from_bbox(bbox=(LAT_MIN, LAT_MAX, LON_MIN, LON_MAX), network_type="drive", simplify=True)
print(f"Graph downloaded in {time.time() - start:.2f}s. Nodes: {len(G.nodes)}")

print("Adding speeds and travel times...")
G = ox.routing.add_edge_speeds(G)
G = ox.routing.add_edge_travel_times(G)

print("Converting to DiGraph...")
D = ox.convert.to_digraph(G, weight="travel_time")

# If nodes > 10,000, betweenness_centrality will take hours.
# Let's see the node count first.
print("Done.")
