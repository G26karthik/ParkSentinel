import osmnx as ox
import numpy as np

# Just a tiny mock test to see nearest_edges syntax
G = ox.graph_from_point((12.9716, 77.5946), dist=500, network_type="drive")
lons = np.array([77.5946, 77.5950])
lats = np.array([12.9716, 12.9720])

edges = ox.distance.nearest_edges(G, X=lons, Y=lats)
print("edges output:", edges[:2])
