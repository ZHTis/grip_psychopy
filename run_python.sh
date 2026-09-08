#!/bin/bash
# Use an explicit interpreter, a local environment, or macOS PsychoPy Standalone.
set -e
project_dir="$(cd -- "$(dirname -- "$0")" && pwd)"
cd "$project_dir"
if [ -n "${GRIP_PYTHON:-}" ]; then
    task_python="$GRIP_PYTHON"
elif [ -x "$project_dir/.venv/bin/python" ]; then
    task_python="$project_dir/.venv/bin/python"
elif [ -x /Applications/PsychoPy.app/Contents/MacOS/python ]; then
    task_python=/Applications/PsychoPy.app/Contents/MacOS/python
else
    task_python=python3
fi
# Standalone bundles its standard library under Contents/Resources.
case "$task_python" in
    *.app/Contents/MacOS/python)
        task_resources="${task_python%/MacOS/python}/Resources"
        if [ -d "$task_resources/lib" ]; then
            export PYTHONHOME="$task_resources"
        fi
        ;;
esac
exec "$task_python" "$@"
