#!/bin/bash
project_dir="$(cd -- "$(dirname -- "$0")" && pwd)"
# Resolve the boards by USB serial number from config.json at each launch.
exec /bin/bash "$project_dir/run_python.sh" "$project_dir/run_task.py" "$@"
