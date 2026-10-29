#!/usr/bin/env bash
# AeroSOuDA — Spark job launcher
# Handles both local container paths and HDFS URIs transparently.
set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "Usage: $0 <input_csv> <output_dir> [scenario_config]"
  echo "  input_csv may be a local path OR hdfs://namenode:9000/..."
  exit 1
fi

INPUT_CSV="$1"
OUTPUT_DIR="$2"
SCENARIO_CONFIG="${3:-/opt/spark/scenarios/qr_correlation.yaml}"

SPARK_EXECUTOR_INSTANCES="${SPARK_EXECUTOR_INSTANCES:-2}"
SPARK_EXECUTOR_MEMORY="${SPARK_EXECUTOR_MEMORY:-512m}"
SPARK_DRIVER_MEMORY="${SPARK_DRIVER_MEMORY:-1g}"
SPARK_SQL_SHUFFLE_PARTITIONS="${SPARK_SQL_SHUFFLE_PARTITIONS:-8}"
SPARK_CORES_MAX="${SPARK_CORES_MAX:-2}"
SPARK_EXECUTOR_CORES="${SPARK_EXECUTOR_CORES:-1}"

SCRIPTS_DIR="$(dirname "$(readlink -f "$0")")"

# When HADOOP_CONF_DIR is set (for HDFS connectivity), core-site.xml sets
# fs.defaultFS=hdfs://namenode:9000, which would redirect ALL file reads to HDFS
# even for local paths. We therefore:
#   - HDFS input: keep the HDFS default FS, use the path as-is
#   - local input: override fs.defaultFS back to file:/// so Spark reads locally
if [[ "$INPUT_CSV" == hdfs://* ]]; then
  FS_CONF="--conf spark.hadoop.fs.defaultFS=hdfs://namenode:9000 --conf spark.hadoop.dfs.client.use.datanode.hostname=true"
else
  # Validate local path existence
  if [[ ! -f "$INPUT_CSV" ]]; then
    echo "ERROR: Input CSV not found: $INPUT_CSV"
    exit 1
  fi
  # Override any HADOOP_CONF_DIR-inherited default back to local filesystem
  FS_CONF="--conf spark.hadoop.fs.defaultFS=file:///"
fi

# shellcheck disable=SC2086  # word splitting intentional for FS_CONF
/opt/spark/bin/spark-submit \
  --master spark://spark-master:7077 \
  --conf "spark.executor.instances=${SPARK_EXECUTOR_INSTANCES}" \
  --conf "spark.executor.memory=${SPARK_EXECUTOR_MEMORY}" \
  --conf "spark.executor.cores=${SPARK_EXECUTOR_CORES}" \
  --conf "spark.cores.max=${SPARK_CORES_MAX}" \
  --conf "spark.driver.memory=${SPARK_DRIVER_MEMORY}" \
  --conf "spark.sql.shuffle.partitions=${SPARK_SQL_SHUFFLE_PARTITIONS}" \
  $FS_CONF \
  "${SCRIPTS_DIR}/csv_processor.py" \
  --input-file "$INPUT_CSV" \
  --output-path "$OUTPUT_DIR" \
  --scenario-config "$SCENARIO_CONFIG"
