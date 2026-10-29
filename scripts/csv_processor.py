#!/usr/bin/env python3
"""
This file is the spark-submit target called by run_csv_processor.sh.
All logic lives in the processor/ package (same directory).
"""
import os
import sys

# Ensure the scripts/ directory is on sys.path so the processor package
# is importable by all Spark executors (which share the same volume mount).
_scripts_dir = os.path.dirname(os.path.abspath(__file__))
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

from processor.spark_job import main

if __name__ == "__main__":
    main()
