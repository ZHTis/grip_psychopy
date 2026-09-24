"""Offline estimated device-to-session clock mapping; never an EEG alignment claim."""
import argparse
import csv
import json
import math
import sqlite3
from pathlib import Path


def fit_clock(exchanges):
    if not exchanges:
        return {'status': 'unavailable'}
    selected = sorted(exchanges, key=lambda s: s['net_rtt_s'])[:max(1, (len(exchanges)+2)//3)]
    x0 = sum(s['device_mid_s'] for s in selected)/len(selected)
    y0 = sum(s['host_mid_s'] for s in selected)/len(selected)
    span = max(s['device_mid_s'] for s in selected)-min(s['device_mid_s'] for s in selected)
    scale = 1.0
    status = 'offset_only'
    if len(selected) >= 4 and span >= 2:
        scale = sum((s['device_mid_s']-x0)*(s['host_mid_s']-y0) for s in selected)/sum((s['device_mid_s']-x0)**2 for s in selected)
        status = 'affine'
    rms = math.sqrt(sum((s['host_mid_s']-(y0+scale*(s['device_mid_s']-x0)))**2 for s in selected)/len(selected))
    return dict(status=status, device_origin_s=x0, host_origin_s=y0, scale=scale,
                selected_sync_ids=[s['sync_id'] for s in selected], residual_rms_s=rms,
                device_min_s=min(s['device_mid_s'] for s in selected),
                device_max_s=max(s['device_mid_s'] for s in selected))


def export_session(session, output):
    output.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(f'{(session/"session.sqlite3").resolve().as_uri()}?mode=ro', uri=True)
    try:
        rows = [(i,k,json.loads(p)) for i,k,p in db.execute('SELECT id,kind,payload FROM records ORDER BY id')]
    finally:
        db.close()
    samples, syncs, tasks = [], [], []
    previous = None
    unwrapped = 0
    for i,k,p in rows:
        if k == 'grip':
            p['record_id'] = i
            if p.get('valid', True) and p.get('device_timed'):
                us = p['device_micros']
                unwrapped = us if previous is None else unwrapped+((us-previous)&0xffffffff)
                previous = us
                p['device_unwrapped_s'] = unwrapped/1e6
            samples.append(p)
        elif k == 'grip_sync': syncs.append(p)
        elif k == 'task': tasks.append(p)
    timed = [s for s in samples if 'device_unwrapped_s' in s]
    for s in syncs:
        if not timed: continue
        near = min(timed, key=lambda p: abs(p['t']-s['host_t4_s']))
        delta = ((s['device_t2_us']-near['device_micros']+2**31)%2**32)-2**31
        t2 = near['device_unwrapped_s']+delta/1e6
        turnaround = ((s['device_t3_us']-s['device_t2_us'])&0xffffffff)/1e6
        s.update(device_mid_s=t2+turnaround/2,
                 host_mid_s=(s['host_t1_s']+s['host_t4_s'])/2,
                 net_rtt_s=s['host_t4_s']-s['host_t1_s']-turnaround)
    model = fit_clock([s for s in syncs if 'net_rtt_s' in s and s['net_rtt_s'] >= 0])
    for s in timed:
        if model['status'] != 'unavailable':
            x = s['device_unwrapped_s']
            s['estimated_sample_host_s'] = model['host_origin_s']+model['scale']*(x-model['device_origin_s'])
            s['extrapolated'] = not model['device_min_s'] <= x <= model['device_max_s']
    by_id = {s['record_id']: s for s in samples}
    for t in tasks:
        s = by_id.get(t.get('grip_sample_id'))
        t['sample_matched'] = s is not None
        if s and s.get('valid', True) and t.get('task_use_host_s') is not None:
            t['receive_to_use_s'] = t['task_use_host_s']-s['t']
            if 'estimated_sample_host_s' in s:
                t['estimated_sample_to_use_s'] = t['task_use_host_s']-s['estimated_sample_host_s']
    def write(name, items):
        keys = list(dict.fromkeys(k for item in items for k in item))
        with (output/name).open('w', newline='', encoding='utf-8-sig') as f:
            w=csv.DictWriter(f, fieldnames=keys);w.writeheader();w.writerows(items)
    write('samples.csv', samples);write('sync_exchanges.csv', syncs);write('task_use.csv', tasks)
    model['limitations'] = 'Software estimate; RTT/residuals are not absolute error bounds. EEG alignment is unverified.'
    (output/'timing_metadata.json').write_text(json.dumps(model, indent=2), encoding='utf-8')
    return model

if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('session', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args=parser.parse_args()
    export_session(args.session, args.output)
