# AeroSOuDA Local Cluster — convenience targets
# Compatible with Docker Desktop and docker.io (Ubuntu package).

COMPOSE    = docker compose
MIN_GB     = 8

.PHONY: help up down restart logs fix-perms status run check-space prune hdfs-usage clean-hdfs

help:
	@echo "AeroSOuDA Local Cluster"
	@echo ""
	@echo "  make check-space  — Verify enough disk space before pulling images"
	@echo "  make up           — Start all containers (runs check-space first)"
	@echo "  make down         — Stop all containers"
	@echo "  make restart      — Full down → up cycle"
	@echo "  make status       — Show running containers"
	@echo "  make logs         — Follow spark-master logs"
	@echo "  make fix-perms    — Fix directory permissions for Spark container user"
	@echo "  make prune        — Free Docker build cache and dangling images"
	@echo "  make hdfs-usage   — Show HDFS disk usage (files in /inputs and /outputs)"
	@echo "  make clean-hdfs   — Delete all files in HDFS /inputs and /outputs"
	@echo "  make run          — Launch the interactive CLI"
	@echo ""
	@echo "First time setup: make check-space && make fix-perms && make up"

# ── Pre-flight disk space check ───────────────────────────────────────────────
# Required space breakdown (verified via docker system df after build):
#   Spark images (6 containers, shared layers):  ~2.5 GB
#   Hadoop images (namenode + datanode, shared):  ~2.1 GB
#   ─── Total images on disk: ~4.8 GB ───────────────────────────────────────
#   Docker build cache (capped at 5 GB in daemon.json): up to 2.5 GB
#   HDFS named volumes + simulation outputs:            ~1 GB
#   ─────────────────────────────────────────────────────────────────────────
#   Total minimum recommended:  ~8 GB (MIN_GB below)

check-space:
	@echo "=== Disk space pre-flight check ==="
	@DOCKER_ROOT=$$(docker info --format '{{.DockerRootDir}}' 2>/dev/null); \
	if [ -z "$$DOCKER_ROOT" ]; then \
	  echo "ERROR: Docker is not running. Start it first: sudo systemctl start docker"; \
	  exit 1; \
	fi; \
	MOUNT=$$(df --output=target "$$DOCKER_ROOT" 2>/dev/null | tail -1); \
	AVAIL_GB=$$(df --output=avail -BG "$$DOCKER_ROOT" 2>/dev/null | tail -1 | tr -d 'G '); \
	echo "  Docker data-root : $$DOCKER_ROOT"; \
	echo "  Filesystem       : $$MOUNT"; \
	echo "  Available space  : $${AVAIL_GB} GB"; \
	echo "  Minimum required : $(MIN_GB) GB"; \
	if [ "$$AVAIL_GB" -lt "$(MIN_GB)" ]; then \
	  echo ""; \
	  echo "ERROR: Insufficient disk space!"; \
	  echo "  Available: $${AVAIL_GB} GB — Required: $(MIN_GB) GB"; \
	  echo ""; \
	  echo "  To free space, run:  make prune"; \
	  echo "  Or move Docker data-root to a larger partition."; \
	  exit 1; \
	else \
	  echo "  Status           : OK ($${AVAIL_GB} GB >= $(MIN_GB) GB required)"; \
	fi
	@echo ""
	@docker system df 2>/dev/null || true
	@echo ""

# ── Volume and directory setup ────────────────────────────────────────────────
fix-perms:
	@echo "Setting directory permissions for Spark container user (UID 185)..."
	chmod 777 events inputs outputs scenarios
	@echo "Done."

# ── Cluster lifecycle ─────────────────────────────────────────────────────────
up: check-space fix-perms
	$(COMPOSE) up -d
	@echo ""
	@echo "Cluster started. Web UIs:"
	@echo "  Spark master  : http://localhost:8080"
	@echo "  Spark history : http://localhost:18080"
	@echo "  HDFS NameNode : http://localhost:9870"

down:
	$(COMPOSE) down

restart: down up

status:
	$(COMPOSE) ps

logs:
	$(COMPOSE) logs -f spark-master

# ── HDFS management ───────────────────────────────────────────────────────────
hdfs-usage:
	@echo "=== HDFS disk usage ==="
	@docker exec namenode hdfs dfs -du -s -h / 2>/dev/null || echo "HDFS not running"
	@echo ""
	@echo "Breakdown by directory:"
	@docker exec namenode hdfs dfs -du -h / 2>/dev/null || true

clean-hdfs:
	@echo "=== Cleaning HDFS /inputs and /outputs ==="
	@echo "WARNING: this deletes all files stored in HDFS."
	@echo "Files in localcluster/inputs/ (host) are NOT affected."
	@read -p "Continue? [y/N] " ans; [ "$$ans" = "y" ] || exit 1
	@docker exec namenode hdfs dfs -rm -r -skipTrash /inputs/* 2>/dev/null || true
	@docker exec namenode hdfs dfs -rm -r -skipTrash /outputs/* 2>/dev/null || true
	@docker exec namenode hdfs dfs -expunge 2>/dev/null || true
	@echo "Done. Current HDFS usage:"
	@docker exec namenode hdfs dfs -du -s -h / 2>/dev/null || true

# ── Docker cleanup ────────────────────────────────────────────────────────────
prune:
	@echo "=== Freeing Docker disk space ==="
	@echo "Removing stopped containers, dangling images, and build cache..."
	docker system prune -f
	@echo ""
	@echo "To also remove ALL unused images (not just dangling):"
	@echo "  docker system prune -af"
	@echo ""
	@docker system df

# ── Run CLI ───────────────────────────────────────────────────────────────────
run:
	python3 cli.py
