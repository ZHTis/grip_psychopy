#!/bin/bash
set -e
project_dir="$(cd -- "$(dirname -- "$0")" && pwd)"
exec bash "$project_dir/run_python.sh" run_task.py --grip-device rx-g0505m "$@"
