# ParkSentinel

**AI-powered parking enforcement intelligence for Bengaluru**

Built for Gridlock Hackathon 2.0 (Flipkart × Bengaluru Traffic Police) — Problem Statement 1: Parking-Induced Congestion Intelligence.

## What It Does

ParkSentinel analyzes 115,400+ approved parking violation records from Bengaluru Traffic Police to:

1. **Detect illegal parking hotspots** using HDBSCAN clustering + H3 hexagonal aggregation
2. **Quantify congestion impact** via the explainable Congestion Impact Score (CIS, 0–100)
3. **Enable targeted enforcement** with officer deployment recommendations, forecasts, and NL queries

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.11+, FastAPI |
| Database | DuckDB |
| ML | HDBSCAN, H3, Prophet, scikit-learn, OSMnx |
| LLM | OpenAI GPT-4o-mini / Anthropic Claude |
| Frontend | Next.js 14, TypeScript, Deck.gl, MapLibre GL |
| Charts | Recharts |

## Quick Start

### Prerequisites

- Python 3.11+
- Node.js 18+
- CSV data at `data/jan_to_may_police_violation_anonymized791b166.csv`

### Backend

```bash
cd parksentinel/backend
pip install -r requirements.txt
uvicorn main:app --reload
```

**First startup takes 2–5 minutes** while the system:
- Loads 298K records into DuckDB
- Runs HDBSCAN clustering (cached after first run)
- Computes H3 hexbins and CIS scores
- Trains Prophet forecasts for top 20 zones
- Detects anomaly dates

You'll see: `System ready. N clusters found. N critical zones.`

API docs: http://localhost:8000/docs

### Frontend

```bash
cd parksentinel/frontend
npm install
npm run dev
```

Open http://localhost:3000

### Optional: LLM Query Panel

Create `backend/.env`:

```
OPENAI_API_KEY=sk-...
# or
ANTHROPIC_API_KEY=sk-ant-...
```

## API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /health` | System status |
| `GET /hotspots` | HDBSCAN cluster hotspots with CIS |
| `GET /h3-grid` | H3 hexagon GeoJSON for map |
| `GET /enforcement-plan` | Ranked deployment recommendations |
| `GET /forecast/top` | 14-day Prophet forecasts |
| `GET /anomalies` | Spike detection results |
| `GET /summary/*` | Dashboard analytics |
| `POST /query` | Natural language SQL queries |

## Congestion Impact Score (CIS)

| Component | Weight | Source |
|-----------|--------|--------|
| Frequency | 0–25 | log-normalized violation count |
| Severity | 0–25 | vehicle × violation severity weights |
| Road Criticality | 0–25 | OSM highway type at centroid |
| Temporal Persistence | 0–25 | days active × peak/junction multipliers |

| Score | Classification |
|-------|---------------|
| 80–100 | CRITICAL (red) |
| 60–79 | HIGH (orange) |
| 40–59 | MODERATE (yellow) |
| 0–39 | LOW (green) |

## Project Structure

```
parksentinel/
├── backend/          # FastAPI + ML pipeline
├── frontend/         # Next.js dashboard
├── data/             # Violation CSV
├── cache/            # DuckDB, OSM, Prophet, HDBSCAN caches
└── docker-compose.yml
```

## GPU Acceleration (RTX 4060 / NVIDIA CUDA)

Your GPU helps with the **heaviest step: HDBSCAN clustering** on 115,400 violation points. Everything else (DuckDB, Prophet, H3, OSM) runs on CPU.

| Component | GPU? | Notes |
|-----------|------|-------|
| HDBSCAN clustering | **Yes** | cuML — ~10–30× faster first startup |
| H3 / CIS scoring | No | Fast on CPU |
| Prophet forecasts | No | CPU-only library |
| DuckDB queries | No | Already sub-second |
| LLM `/query` | No | Cloud API |

### Enable GPU (recommended: WSL2 Ubuntu)

RAPIDS cuML runs best on **Linux/WSL2**. On Windows 11:

```bash
# In WSL2 Ubuntu terminal
conda create -n parksentinel-gpu -c rapidsai -c conda-forge -c nvidia \
  cuml=24.10 python=3.11 cuda-version=12.0
conda activate parksentinel-gpu
cd /mnt/c/Users/.../parksentinel/backend
pip install -r requirements.txt
export USE_GPU=true
uvicorn main:app --reload
```

Verify GPU is detected:

```bash
python -c "import cupy; print(cupy.cuda.runtime.getDeviceCount(), 'GPU(s)')"
```

Check API header after startup: `X-GPU-Enabled: true`

### Without GPU (current default)

CPU HDBSCAN takes ~3 minutes on first run, then results are **cached** in `cache/clusters_cache.pkl`. Subsequent startups load in seconds — fine for demo day.

To force re-cluster with GPU after installing cuML:

```bash
rm cache/clusters_cache.pkl cache/pipeline_state.pkl
set USE_GPU=true
uvicorn main:app --reload
```


1. **Main dashboard** — click hexagons at Safina Plaza / KR Market areas; show CIS breakdown
2. **Time scrubber** — switch Nov → Jan to show peak month evolution
3. **Enforcement plan** — "Deploy 3 officers to CRITICAL zone, morning shift"
4. **Forecast** — proactive 14-day violation prediction
5. **Ask AI** — "Which junction has the most HGV violations?"

## License

Built for Gridlock Hackathon 2.0 prototype phase.
