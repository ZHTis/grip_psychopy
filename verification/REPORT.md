# Verification — 2026-09-08

## Completed

- Python unit tests: serial split/batched lines, malformed/nonfinite values, no-data/stale-data failure; all 256 marker encodings, repeated marker ordering, ACK validation and timeout; concurrent SQLite recording, marker links, CSV columns, unique sessions and recovery export.
- Original task behavior tests: all 10 trials, 360 feedback updates over 45 seconds with 125 ms source blocks, 384 source blocks between consecutive trial starts in a no-collision run, collision priority/boundary, map finish, physical integration equation, original map finish calculation.
- Full original-duration logic run: `run_task.py --simulate --headless`, completed (accelerated logic only).
- Three independent module CLI tests: recording, simulated grip acquisition, simulated markers.
- Actual installed PsychoPy Python 3.10: rendered prepare/feedback/result with original SVGs via Qt; screenshots included and flight image visually inspected.
- Actual PsychoPy end-to-end session with shortened phases: 10 trials, 42 marker requests, 42 simulated ACKs, 42 DONE records, 697 continuously recorded simulated grip lines; completed successfully. Data included in session_data. This demonstrates software integration, not physical TTL output.
- Source assets/maps are copied without modification. `source_manifest.json` records source locations and SHA256 hashes.

## Not hardware-verified

- Actual grip-board streaming rate, COM assignments, actual gain/calibration.
- Second board model, firmware build/upload and electrical D2–D9 transitions.
- EEG receiver code mapping, polarity, accepted voltage, isolation and input sampling behavior.
- Physical pulse width, bit skew, USB delay, EEG/force alignment error; requires the actual equipment and, for quantitative timing, a scope/logic analyzer.
- Long-running stability and actual monitor timing. PsychoPy reported no calibrated monitor profile and used a temporary one; coordinate rendering uses pixels, but formal timing validation remains needed.

## Explicit task assumption

The available GripFlight source has one run of 10 trials and no experimental block grouping. Shared GripForceTask block parameters are not consumed by GripFlight. The migration retains this actual behavior (block=1). SampleBlockSize=32 / SamplingRate=256 are source defaults; any Operator overrides must be copied into config.json.

The default marker map is provisional and configurable; marker COM port is intentionally empty. Real mode refuses to start until configured.
