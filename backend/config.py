"""ParkSentinel configuration and constants."""

import os
from pathlib import Path

PROJECT_ROOT = Path(os.getenv("PARKSENTINEL_ROOT", Path(__file__).resolve().parent.parent))
DATA_DIR = Path(os.getenv("DATA_DIR", PROJECT_ROOT / "data"))
CACHE_DIR = Path(os.getenv("CACHE_DIR", PROJECT_ROOT / "pipeline_output"))
CSV_FILENAME = "jan_to_may_police_violation_anonymized791b166.csv.gz"
CSV_PATH = DATA_DIR / CSV_FILENAME
DUCKDB_PATH = CACHE_DIR / "parksentinel.duckdb"
OSM_CACHE_PATH = CACHE_DIR / "osm_road_cache.pkl"
PROPHET_CACHE_PATH = CACHE_DIR / "prophet_forecasts.pkl"

PRODUCT_NAME = "ParkSentinel"
API_HOST = "0.0.0.0"
API_PORT = 8000
CORS_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:3001",
    "http://127.0.0.1:3001",
    "https://park-sentinel.vercel.app",
    "*"  # Allow all for hackathon flexibility
]

# Geographic bounds for Bengaluru
LAT_MIN, LAT_MAX = 12.7, 13.4
LON_MIN, LON_MAX = 77.3, 77.9

# HDBSCAN parameters
HDBSCAN_MIN_CLUSTER_SIZE = 50
HDBSCAN_MIN_SAMPLES = 10
H3_RESOLUTION = 8
H3_PARENT_RESOLUTION = 7

# GPU acceleration (RTX 4060 / CUDA via RAPIDS cuML)
# Set USE_GPU=true after installing cuml — see README "GPU Setup"
USE_GPU = os.getenv("USE_GPU", "false").lower() in ("1", "true", "yes")

# Peak hours
PEAK_HOURS = (7, 8, 9, 17, 18, 19, 20)

# Vehicle severity weights
VEHICLE_SEVERITY: dict[str, float] = {
    "HGV": 5.0,
    "LORRY/GOODS VEHICLE": 5.0,
    "PRIVATE BUS": 4.5,
    "BUS (BMTC/KSRTC)": 4.5,
    "LGV": 3.0,
    "TEMPO": 3.0,
    "VAN": 3.0,
    "MAXI-CAB": 2.5,
    "PASSENGER AUTO": 2.0,
    "GOODS AUTO": 2.0,
    "CAR": 1.5,
    "JEEP": 1.5,
    "MOTOR CYCLE": 1.0,
    "SCOOTER": 1.0,
    "MOPED": 1.0,
}

# Violation severity weights
VIOLATION_SEVERITY: dict[str, float] = {
    "PARKING IN A MAIN ROAD": 5.0,
    "DOUBLE PARKING": 4.5,
    "PARKING NEAR TRAFFIC LIGHT OR ZEBRA CROSS": 4.5,
    "PARKING NEAR ROAD CROSSING": 4.0,
    "PARKING ON FOOTPATH": 3.5,
    "PARKING NEAR BUSTOP/SCHOOL/HOSPITAL ETC": 3.0,
    "PARKING OPPOSITE TO ANOTHER PARKED VEHICLE": 3.0,
    "WRONG PARKING": 2.0,
    "NO PARKING": 1.5,
    "DEFECTIVE NUMBER PLATE": 0.5,
}

DEFAULT_VEHICLE_SEVERITY = 1.0
DEFAULT_VIOLATION_SEVERITY = 1.0
MAX_POSSIBLE_SEVERITY = 5.0 * 5.0  # max vehicle × max violation

# OSM highway weights
HIGHWAY_WEIGHTS: dict[str, float] = {
    "motorway": 1.0,
    "trunk": 1.0,
    "primary": 1.0,
    "secondary": 0.8,
    "tertiary": 0.6,
    "residential": 0.3,
    "unclassified": 0.3,
    "service": 0.1,
    "living_street": 0.1,
}
DEFAULT_HIGHWAY_WEIGHT = 0.5

# CIS classification thresholds — calibrated against this dataset's observed CIS
# distribution (max ~75) so CRITICAL flags the worst ~2.5% (~17) of zones (p98≈62) instead of an empty band.
CIS_CRITICAL = 62
CIS_HIGH = 48
CIS_MODERATE = 32

# CIS colors (for reference)
CIS_COLORS = {
    "CRITICAL": "#DC2626",
    "HIGH": "#EA580C",
    "MODERATE": "#CA8A04",
    "LOW": "#16A34A",
}
