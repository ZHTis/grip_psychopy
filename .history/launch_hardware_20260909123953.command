#!/bin/bash
project_dir="$(cd -- "$(dirname -- "$0")" && pwd)"
# Confirmed Mac mapping: COM6 -> 1301 (grip), COM10 -> 1401 (markers).
# Arguments supplied by the caller come last and can override these defaults.
exec /bin/bash "$project_dir/run_python.sh" "$project_dir/run_task.py" \
    --grip-port /dev/cu.usbmodem11301 \
    --marker-port /dev/cu.usbmodem11401 "$@"
