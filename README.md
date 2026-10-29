# AeroSOuDA — Local Cluster

**Aerospace Simulation Output Distributed Architecture** — local cluster prototype for distributed post-processing of aerospace simulation outputs.

> **Context:** This project is the intermediate validation step of the AeroSOuDA architecture proposed in the ITA graduation thesis *"Exploring Distributed Computing Architectures for Aerospace Simulation Environments"* (Marcelo Loiola Lopes Veras, 2026). It demonstrates that the MapReduce pipeline works correctly on a local containerised cluster before full integration with the production ASA infrastructure.

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [How It Fits the Thesis](#how-it-fits-the-thesis)
3. [Prerequisites](#prerequisites)
4. [Project Structure](#project-structure)
5. [Setup](#setup)
6. [Running the CLI](#running-the-cli)
7. [Folder Reference](#folder-reference)
8. [Private Libraries (asapy / asa-client)](#private-libraries-asapy--asa-client)
9. [Scenario YAML Files](#scenario-yaml-files)
10. [Troubleshooting](#troubleshooting)

---

## Architecture Overview

```
┌────────────────────────────────────────────────────────────────────┐
│  Host machine                                                      │
│                                                                    │
│  cli.py  ──────────────────────────────────────────────────────┐   │
│      │                                                         │   │
│      │  (optional) generate_simulation_csv.py                  │   │
│      │       │  asapy + asa-client ──► ASA server              │   │
│      │       └──────────────── CSV ──►  inputs/                │   │
│      │                                                         │   │
│      │  docker compose exec spark-master  ◄──────────────────┐ │   │
│      │       run_csv_processor.sh                            │ │   │
│      │                                                       │ │   │
│  ┌───▼────────────────────────────────────────────────────┐  │ │   │
│  │  Docker cluster (docker-compose.yml)                   │  │ │   │
│  │                                                        │  │ │   │
│  │  spark-master   ◄──────────────────────────────────────┘  │ │   │
│  │       │ schedules tasks                                   │ │   │
│  │       ├──► spark-worker-1  ─┐                             │ │   │
│  │       ├──► spark-worker-2  ─┤  MapReduce (mapPartitions)  │ │   │
│  │       ├──► spark-worker-3  ─┤  on CSV partitions          │ │   │
│  │       └──► spark-worker-4  ─┘                             │ │   │
│  │                                                           │ │   │
│  │  spark-history-server  (port 18080)                       │ │   │
│  └────────────────────────────────────────────────────────┘  │ │   │
│      │  results pulled via docker cp                                      │ │   │
│      └──────────────────────────────────────► outputs/       │ │   │
└────────────────────────────────────────────────────────────────────┘
```

**Processing pipeline (MapReduce):**

1. The input CSV (raw simulation results) is copied into the Spark master container.
2. `csv_processor.py` runs on the cluster via `spark-submit`.
3. **Map phase** — each worker processes its partition independently:parse payload → match entity selector → extract field → aggregate per-entity metric.
4. **Reduce phase** — driver merges partial results from all workers into global x/y dictionaries.
5. Three output artefacts are written: aggregated CSV, scatter plot PNG, JSON summary.

---

## How It Fits the Thesis

The thesis proposes AeroSOuDA to solve a bottleneck in the ASA workflow: simulation outputs are currently post-processed serially on a single machine. AeroSOuDA replaces this with:

- **Distributed storage** (HDFS-ready architecture, volume mounts for local cluster)
- **Parallel metric extraction** (Apache Spark MapReduce via PySpark)
- **Analyst-facing API** (YAML scenario files + interactive CLI)

This repository implements the *local cluster proof-of-concept* described in **Chapter 5** of the thesis. It validates the full pipeline end-to-end before integration with the production ASA infrastructure. The scenarios tested include:

- **Quick-Reaction (QR):** Pearson correlation between red radar longitude and blue fighter survival time
- **Damage Analysis:** Pearson correlation between red radar longitude and blue fighter max damage

---

## Prerequisites

### Disk Space Requirements

> ⚠️ **Read this before pulling images.** Docker's build cache can silently accumulate tens of gigabytes if left unmanaged.

| Component                                                  | Download (compressed)      | Installed (deduplicated)  |
| ---------------------------------------------------------- | -------------------------- | ------------------------- |
| `apache/spark:4.1.3-python3` (base image)                | ~970 MB                    | ~2.5 GB                   |
| Custom Spark build (6 containers, shared layers)           | ~50 MB                     | ~2.5 GB total             |
| `bde2020/hadoop-namenode` + `datanode` (shared layers) | ~590 MB                    | ~2.1 GB total             |
| Docker build cache (capped at 5 GB via daemon.json)        | —                         | up to 2.5 GB              |
| HDFS named volumes + outputs                               | —                         | ~1 GB                     |
| **Total on disk (with layer deduplication)**         | **~1.6 GB download** | **~8 GB installed** |

> **Verified numbers** (from `docker system df` after build): Images = **4.8 GB**, Build cache = **2.5 GB**, Total = **~7.3 GB**.
> Docker shares layers between containers — the 6 Spark containers together use ~2.5 GB, not 6 × 2.5 GB.

The Makefile's `make check-space` verifies available space **before** building or starting containers.

#### Limit Docker build cache (recommended)

Add this to `/etc/docker/daemon.json` to cap the build cache at 5 GB and prevent runaway disk usage:

```bash
sudo tee /etc/docker/daemon.json > /dev/null << 'EOF'
{
  "data-root": "/your/docker/path",
  "builder": {
    "gc": {
      "enabled": true,
      "defaultKeepStorage": "5GB"
    }
  }
}
EOF
sudo systemctl restart docker
```

#### Free disk space at any time

```bash
make prune               # removes stopped containers, dangling images, build cache
docker system prune -af  # nuclear option — removes ALL unused images too
```

### System Requirements

- **Operating System:** Linux (tested on Ubuntu 22.04+)
- **Python:** 3.8.20 (must match the `conda` environment specification)
- **Docker Engine:** 24.0+ with Compose v2 — works with:
  - **Docker Desktop** (Linux, macOS, Windows via WSL2)
  - **docker.io** Ubuntu package (`sudo apt install docker.io docker-compose-v2`)
- **RAM:** At least 8 GB recommended (4 workers × 2 GB each)
- **Disk:** At least 8 GB free on the Docker data-root partition

> **Docker Desktop vs docker.io:** Both are supported. The main difference is the user ID
> that runs inside containers — see the [Permission Setup](#permission-setup) section below.

### Install Python dependencies (host side)

```bash
pip install -r requirements.txt
```

> **Note:** The CLI runs on the host; computation runs inside Docker containers. The Docker image installs its own dependencies (matplotlib, pandas, pyyaml) via the `Dockerfile`.

---

## Project Structure

```
localcluster/
├── cli.py                          # Entry point — imports and calls cli.main()
├── cli/                            # CLI package (modular)
│   ├── config.py                   # Constants and path definitions
│   ├── console.py                  # Rich console singleton and error helpers
│   ├── docker.py                   # Docker daemon + HDFS management
│   ├── csv_source.py               # CSV picker + ASA simulation invocation
│   ├── inspector.py                # CSV validation + entity discovery
│   ├── scenario.py                 # YAML wizard + scenario loading
│   ├── job.py                      # Spark job submission + HDFS upload
│   └── results.py                  # Results display
├── docker-compose.yml              # Cluster definition (8 containers: Spark + HDFS)
├── Dockerfile                      # Custom Spark image with Python deps
├── Makefile                        # Convenience targets (up, down, fix-perms, run)
├── requirements.txt                # Host-side Python dependencies
│
├── scripts/
│   ├── csv_processor.py            # Entry point — imports processor.spark_job.main()
│   ├── processor/                  # Distributed processor package
│   │   ├── aggregator.py           # mapPartitions factory + merge helpers
│   │   ├── config.py               # Constants + argparse
│   │   ├── output.py               # DataFrame assembly, aggregation, plot
│   │   ├── payload.py              # Payload parsing + entity extraction
│   │   ├── scenario.py             # Scenario config loading/resolution
│   │   └── spark_job.py            # Spark session orchestrator (main)
│   ├── generate_simulation_csv.py  # ASA simulation batch runner (optional)
│   └── run_csv_processor.sh        # spark-submit wrapper (runs inside container)
│
├── scenarios/
│   ├── qr_correlation.yaml         # Quick-Reaction scenario config
│   └── damage_analysis.yaml        # Damage analysis scenario config
│
├── conf/
│   ├── spark-defaults.conf         # Spark configuration (incl. HDFS settings)
│   ├── core-site.xml               # Hadoop core config (fs.defaultFS for HDFS)
│   ├── hdfs-site.xml               # HDFS config (replication, block size)
│   └── hadoop.env                  # HDFS container environment variables
│
├── inputs/                         # Place your input CSV files here
│   └── results_tiny.csv            # Small sample file for testing
│
├── outputs/                        # Generated results (gitignored)
│   └── .gitkeep
│
└── events/                         # Spark event logs (gitignored)
    └── .gitkeep
```

---

## Setup

### 1. Clone the repository

```bash
git clone <repository-url>
cd localcluster
```

### 2. Install host dependencies

```bash
pip install -r requirements.txt
```

### 3. Verify disk space

```bash
make check-space
```

This checks that the Docker data-root partition has at least 8 GB free before downloading images (~1.6 GB compressed download, ~5–8 GB installed).

### 4. Build the Docker image

```bash
docker compose build
```

### 4. Permission setup (Linux / docker.io)

The Spark containers run as user `spark` (UID 185) inside the image. On Linux with the
`docker.io` package, bind-mounted directories must be writable by that UID:

```bash
chmod 777 events inputs outputs scenarios
```

Or use the provided `Makefile`:

```bash
make fix-perms
```

> **Docker Desktop users:** Docker Desktop on macOS/Windows handles permissions automatically
> via its VM layer — this step is not needed. On Linux, Docker Desktop also handles it via
> the rootless daemon; `chmod` may still be needed depending on your installation.

### 5. Start the cluster

```bash
docker compose up -d
```

Wait for all containers to be healthy:

```bash
docker compose ps
```

All eight services should show `running`:

- `namenode`, `datanode` — HDFS cluster
- `spark-master`
- `spark-worker-1` through `spark-worker-4`
- `spark-history-server`

> ⚠️ **Important:** Always start (or restart) the cluster before running the CLI.
> If you see "unregistered worker heartbeat" warnings in the logs, restart the cluster:
>
> ```bash
> docker compose down && docker compose up -d
> ```
>
> Or use: `make restart`

### 6. Run the CLI

From the `localcluster/` directory:

```bash
python cli.py
```

---

## Running the CLI

The CLI guides you through the full pipeline interactively. No manual Spark commands needed.

### Step-by-step walkthrough

```
1. Docker check         → verifies the daemon is accessible
2. Cluster check        → verifies spark-master is running
3. Data source          → choose: existing CSV  OR  generate via ASA simulation
4. CSV inspection       → validates columns, discovers entity types and fields
5. Scenario config      → load an existing YAML  OR  create one via wizard
6. Confirmation         → review selected options before processing
7. Spark job            → submits job, shows live progress
8. Results              → outputs saved to outputs/
```

### Quick test (no ASA account needed)

A small sample file is bundled at `inputs/results_tiny.csv`:

```bash
python cli.py
# → Choose "Use existing CSV"
# → Select results_tiny.csv
# → Choose "Load existing YAML scenario"  
# → Select qr_correlation.yaml
# → Confirm and run
```

Results will appear in `outputs/`.

---

## Folder Reference

### `scripts/`

| File                           | Purpose                                                                                                                                                                                                           |
| ------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `csv_processor.py`           | PySpark job executed inside the cluster. Reads the scenario YAML, runs the distributed map phase (payload parsing + entity/field extraction per partition), runs the reduce phase on the driver, writes results.  |
| `generate_simulation_csv.py` | Connects to the ASA server via `asapy`/`asa-client`, runs a simulation batch using a Design of Experiments (DOE), saves raw results as CSV in `inputs/`. Only needed if you want to generate your own data. |
| `run_csv_processor.sh`       | `spark-submit` wrapper that executes inside the `spark-master` container. Configures executor memory, cores, and shuffle partitions before calling `csv_processor.py`.                                      |

### `scenarios/`

YAML configuration files that define *what* to compute. Each file specifies:

- **`x_variable`** — the independent parameter that varies across simulation runs (e.g. radar longitude). Includes: entity selector (side + type), nested field path in the payload, frame-level aggregation (`max`/`min`/`last`/`first`), observation scope (`per_experiment` or `per_entity`).
- **`y_variable`** — the metric of interest (e.g. fighter survival time). Same structure as `x_variable`.
- **`batch_aggregation`** — how to combine all (x, y) pairs into a single result: `pearson_correlation`, `mean_y`, `count_y`, or `scatter_only`.

The CLI wizard can create new YAML files without you ever editing YAML manually.

### `conf/`

Spark configuration applied to all containers via volume mount. Key settings:

| Parameter                             | Value                        | Purpose                                          |
| ------------------------------------- | ---------------------------- | ------------------------------------------------ |
| `spark.eventLog.enabled`            | `true`                     | Enables event logging (written to `events/`)   |
| `spark.history.fs.logDirectory`     | `file:///opt/spark/events` | Where the history server reads events from       |
| `spark.executor.memory`             | `1536m`                    | Memory per executor                              |
| `spark.sql.adaptive.enabled`        | `true`                     | Adaptive query execution for better partitioning |
| `spark.sql.maxSinglePartitionBytes` | `128 MB`                   | Controls partition size for data distribution    |

To tune performance for your hardware, edit `conf/spark-defaults.conf` and restart the cluster.

### `events/`

Spark event logs, written automatically when `spark.eventLog.enabled = true`. These are binary/structured JSON files that the **Spark History Server** reads to render the job timeline UI.

**To view the job history:**
Open `http://localhost:18080` in your browser after running at least one job.

This folder is **gitignored** — event logs are machine-specific and can be large. The `.gitkeep` file ensures the folder exists in the repository so Docker volume mounts work correctly on a fresh clone.

### `inputs/`

Place your simulation result CSV files here before running the CLI. The CLI scans this folder and presents available files for selection.

**Required columns:** `id`, `frame`, `execution_id`, `mixr_type`, `asa_type`, `asa_custom_type`, `payload`, `sim_time`, `utc_time`, `execution_uuid`, `batch_id`, `experiment`.

Large CSV files (`results_quickreaction.csv`, `results_quickreaction_sample.csv`) are gitignored. Only `results_tiny.csv` (659 KB sample) is tracked.

### `outputs/`

Generated output files. For each processed CSV, three files are created:

| File                               | Content                                                                            |
| ---------------------------------- | ---------------------------------------------------------------------------------- |
| `<name>_aggregated.csv`          | One row per (experiment, entity) with extracted x/y values and the batch aggregate |
| `<name>_aggregated.png`          | Scatter plot of x vs y across all experiments                                      |
| `<name>_aggregated_summary.json` | Scenario metadata, aggregate value, and file paths                                 |

This folder is **gitignored** — outputs are generated artefacts, not source files.

---

## Private Libraries (asapy / asa-client)

**asapy** and **asa-client** are proprietary libraries developed by the ASA project team at DCTA/IEAv. They are **not** distributed in this repository.

These libraries are only required if you want to **generate new simulation CSVs** via the CLI's "generate from scenario" option. If you already have a CSV file (e.g. `results_tiny.csv`), you can run the full distributed processing pipeline without them.

### To use asapy / asa-client

1. Obtain the libraries from the ASA project team (IEAv/DCTA).
2. Install them in a dedicated conda environment:

   ```bash
   conda create -n asapy python=3.8.20
   conda activate asapy
   pip install /path/to/asapy /path/to/asa-client
   pip install -r requirements.txt  # host deps
   ```
3. Run the CLI from this environment:

   ```bash
   conda activate asapy
   python cli.py
   ```

   The CLI will automatically detect the `asapy` environment and enable the simulation generation option.

> **Note:** The simulation generator (`scripts/generate_simulation_csv.py`) requires an active network connection to the ASA server (`https://service.asa.dcta.mil.br`) and valid credentials.

---

## Scenario YAML Files

Two scenarios are included:

### `qr_correlation.yaml` — Quick-Reaction

Measures the Pearson correlation between the longitude of the red radar and the survival time (in frames) of blue fighters. This is the primary scenario from the thesis.

### `damage_analysis.yaml` — Damage Analysis

Measures the Pearson correlation between the longitude of the red radar and the maximum damage sustained by blue fighters.

### Creating a custom scenario

Run `python cli.py` and choose "Create new scenario (guided wizard)". The wizard asks questions in plain language and generates the YAML automatically.

---

## Troubleshooting

### Docker is not running

```
❌ Docker não está rodando ou não está acessível.
```

Start the Docker daemon:

```bash
sudo systemctl start docker
docker compose up -d
```

### Cluster is not running

```
❌ O cluster Spark não está rodando.
```

```bash
docker compose up -d
docker compose ps  # verify all containers are running
```

### Unregistered worker heartbeat warnings

In Spark logs: `WARN Master: Got heartbeat from unregistered worker`.

This happens when the master restarts independently of the workers. Fix:

```bash
docker compose down && docker compose up -d
```

### CSV column validation error

The input CSV must have exactly the 12 required columns listed above. If using custom CSV files, ensure the schema matches.

### No output generated

Check the Spark master logs:

```bash
docker compose logs spark-master
```

Or open the Spark History Server UI at `http://localhost:18080`.

### Docker credential error (migrating from Docker Desktop)

```
error getting credentials - err: exec: "docker-credential-desktop": executable file not found
```

This happens when `~/.docker/config.json` still references the Docker Desktop credential store.
Reset it:

```bash
echo '{"auths":{}}' > ~/.docker/config.json
```

### Permission denied on events/ or outputs/ (Linux / docker.io)

Spark containers run as UID 185. If bind-mounted directories are owned by another UID:

```bash
chmod 777 events inputs outputs scenarios
# or
make fix-perms
```

### `docker compose` command not found

If using an older Ubuntu or legacy Docker installation, install Compose v2:

```bash
sudo apt install docker-compose-v2
```

Or with the standalone v1 binary (deprecated):

```bash
sudo apt install docker-compose
```

The CLI detects and uses whichever variant is available.
