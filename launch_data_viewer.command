#!/bin/bash
set -e
project_dir="$(cd -- "$(dirname -- "$0")" && pwd)"
exec bash "$project_dir/run_python.sh" "$project_dir/data_viewer/view_multichannel.py" "$@"
