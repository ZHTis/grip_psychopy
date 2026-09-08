"""End-to-end PsychoPy smoke test with shortened phases; separate verification data."""
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

root = Path(__file__).resolve().parent
c = json.loads((root/'config.json').read_text())
c['output'] = 'verification/session_data'
c['task']['durations'] = dict(pre_run=.125, prepare=.125, feedback=.25, result=.125, iti=.125)
c['task'].update(gravity=0, lift_gain=0, forward_speed=.01)
config_file = root/'verification_config.json'
config_file.write_text(json.dumps(c), encoding='utf-8')
try:
    environment = dict(os.environ, APPDATA=str(root/'verification/appdata'))
    subprocess.run([sys.executable, str(root/'run_task.py'), '--simulate', '--config', str(config_file)],
                   env=environment, check=True, timeout=90)
finally:
    config_file.unlink(missing_ok=True)
session = max((root/'verification/session_data').iterdir(), key=lambda p: p.name)
db = sqlite3.connect(session/'session.sqlite3')
try:
    counts = dict(db.execute('SELECT kind,count(*) FROM records GROUP BY kind'))
    assert counts['trial'] == 10, counts
    assert counts['marker_request'] == counts['marker_ack'] == counts['marker_done'] == 42, counts
    assert counts['grip'] > 100, counts
    assert counts.get('marker_error', 0) == 0, counts
    assert json.loads((session/'metadata.json').read_text())['status'] == 'complete'
    print('PASS: PsychoPy 10-trial session, 42 markers acknowledged, grip continuously saved:', counts)
finally:
    db.close()
