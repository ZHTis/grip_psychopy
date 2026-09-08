#!/bin/bash
project_dir="$(cd -- "$(dirname -- "$0")" && pwd)"
exec /bin/bash "$project_dir/run_python.sh" "$project_dir/run_task.py" --simulate "$@"
