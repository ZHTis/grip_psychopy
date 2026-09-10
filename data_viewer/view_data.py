"""Read exported GripFlight sessions and plot grip + marker timing. No hardware access."""
from pathlib import Path
import argparse
import json
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

VIEWER_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = VIEWER_ROOT.parent


def data_path(value):
    path = Path(value).expanduser()
    return (PROJECT_ROOT / path).resolve() if not path.is_absolute() else path.resolve()

BASE = ['id', 'kind', 't_host_s', 'trial', 'block', 'phase']
NUMERIC = BASE[:1] + ['t_host_s', 'trial', 'block', 'event_id', 'code', 'voltage', 'raw',
    'temperature', 'smoothed', 'normalized', 'pulse_ms', 't_write_host_s', 'device_micros',
    'grip_age_s', 'grip_sample_id', 'a0_adc', 'loopback_pin']


def read_table(path):
    """Support both early JSON-only CSVs and newer flattened exports."""
    path = Path(path)
    if not path.exists():
        return pd.DataFrame(columns=BASE)
    frame = pd.read_csv(path, encoding='utf-8-sig')
    if 'payload_json' in frame:
        payloads = []
        for row, text in enumerate(frame['payload_json']):
            try:
                value = json.loads(text) if pd.notna(text) else {}
                if not isinstance(value, dict):
                    raise ValueError('payload must be an object')
                payloads.append(value)
            except (ValueError, TypeError) as exc:
                raise ValueError(f'{path.name}: invalid payload at CSV row {row+2}') from exc
        extra = pd.json_normalize(payloads)
        for col in extra:
            if col not in frame:
                frame[col] = extra[col]
            elif col not in BASE:
                frame[col] = frame[col].combine_first(extra[col])
    for col in NUMERIC:
        if col in frame:
            frame[col] = pd.to_numeric(frame[col], errors='coerce')
    for col in BASE:
        if col not in frame:
            frame[col] = np.nan
    return frame.sort_values(['t_host_s', 'id'], kind='stable').reset_index(drop=True)


def list_sessions(data_root):
    rows = []
    for path in sorted(data_path(data_root).glob('*/metadata.json'), reverse=True):
        try:
            m = json.loads(path.read_text(encoding='utf-8-sig'))
            p = m.get('parameters', {})
            rows.append({'session': path.parent.name, 'status': m.get('status'),
                'simulated': p.get('runtime', {}).get('simulate', False),
                'participant': p.get('participant'), 'duration_s': m.get('duration_s'),
                'csv_available': (path.parent/'grip.csv').exists()})
        except (OSError, ValueError):
            continue
    return pd.DataFrame(rows, columns=['session', 'status', 'simulated', 'participant', 'duration_s', 'csv_available'])


def load_session(data_root, name=None):
    root = data_path(data_root)
    if name is None:
        sessions = list_sessions(root)
        candidates = sessions[sessions.csv_available]
        if candidates.empty:
            raise FileNotFoundError(f'No exported session in {root}')
        name = candidates.iloc[0]['session']
    path = root/name
    metadata = json.loads((path/'metadata.json').read_text(encoding='utf-8-sig'))
    tables = {k: read_table(path/(k+'.csv')) for k in ['grip','events','task','trials','diagnostics']}
    return {'path': path, 'metadata': metadata, **tables}


def marker_table(events):
    """Join by request ID, never by code (codes repeat). Times stay in host clock."""
    columns = ['event_id', 'name', 'code', 'trial', 'mode', 'feedback_mode', 'request_s', 'write_s', 'ack_s', 'done_s',
               'status', 'simulated', 'request_to_write_ms', 'request_to_ack_ms', 'device_pulse_ms', 'error', 'a0_during_adc', 'a0_after_adc', 'a0_during_ok', 'a0_after_ok', 'readback_during_code', 'readback_after_code', 'readback_during_ok', 'readback_after_ok', 'mismatched_pins_during', 'mismatched_pins_after']
    output = []
    for _, request in events[events.kind.eq('marker_request')].iterrows():
        request_id = request['id']
        linked = events[events.get('event_id', pd.Series(index=events.index, dtype=float)).eq(request_id)]
        ack = linked[linked.kind.eq('marker_ack')]
        done = linked[linked.kind.eq('marker_done')]
        errors = linked[linked.kind.eq('marker_error')]
        def first(frame, field):
            return frame.iloc[0].get(field, np.nan) if len(frame) else np.nan
        def truth(v):
            return str(v).lower() in ('true', '1', '1.0')
        simulated = truth(request.get('simulated')) or truth(first(ack, 'simulated'))
        status = 'error' if len(errors) else ('done' if len(done) else ('ack_only' if len(ack) else 'no_ack'))
        onset, offset = first(ack, 'device_micros'), first(done, 'device_micros')
        device_width = (offset-onset) % (2**32) / 1000 if pd.notna(onset) and pd.notna(offset) else np.nan
        output.append(dict(event_id=request_id, name=request.get('name', 'unknown'), code=request.get('code'),
            trial=request['trial'], mode=request.get('mode','loopback'), feedback_mode=first(ack,'feedback_mode'), request_s=request['t_host_s'], write_s=first(ack,'t_write_host_s'),
            ack_s=first(ack,'t_host_s'), done_s=first(done,'t_host_s'), status=status,
            simulated=simulated, request_to_write_ms=(first(ack,'t_write_host_s')-request['t_host_s'])*1000,
            request_to_ack_ms=(first(ack,'t_host_s')-request['t_host_s'])*1000,
            device_pulse_ms=device_width, a0_during_adc=first(ack,'a0_adc'), a0_after_adc=first(done,'a0_adc'),
            a0_during_ok=first(ack,'a0_matches_expected'), a0_after_ok=first(done,'a0_matches_expected'),
            readback_during_code=first(ack,'readback_code'), readback_after_code=first(done,'readback_code'),
            readback_during_ok=first(ack,'readback_matches_expected'), readback_after_ok=first(done,'readback_matches_expected'),
            mismatched_pins_during=first(ack,'mismatched_output_pins'), mismatched_pins_after=first(done,'mismatched_output_pins'),
            error='; '.join(errors.get('error', pd.Series(dtype=str)).dropna().astype(str))))
    return pd.DataFrame(output, columns=columns)


def quality_summary(session):
    grip, events, task = session['grip'], session['events'], session['task']
    valid = grip[grip.kind.eq('grip')]
    dt = valid.t_host_s.diff()
    stale = session['metadata'].get('parameters', {}).get('grip', {}).get('stale_timeout_s', 1)
    markers = marker_table(events)
    return pd.DataFrame({'item': ['session_status', 'simulated_session', 'valid_grip_lines',
        'invalid_grip_lines', 'largest_receive_gap_s', f'receive_gaps_over_{stale}s',
        'marker_requests', 'hardware_ack_events', 'simulated_ack_events', 'marker_error_events',
        'requests_without_ack', 'task_steps_with_stale_or_missing_input', 'missing_csv_files'],
        'value': [session['metadata'].get('status'),
            session['metadata'].get('parameters', {}).get('runtime', {}).get('simulate', False),
            len(valid), int(grip.kind.eq('grip_invalid').sum()), dt.max(), int((dt>stale).sum()),
            len(markers), int((markers.ack_s.notna() & ~markers.simulated).sum()),
            int((markers.ack_s.notna() & markers.simulated).sum()), int(events.kind.eq('marker_error').sum()),
            int(markers.ack_s.isna().sum()),
            int(task.get('grip_input_status', pd.Series(dtype=str)).isin(['missing','stale','reader_error']).sum()),
            ', '.join(k+'.csv' for k in ['grip','events','task','trials','diagnostics'] if not (session['path']/(k+'.csv')).exists())]} )


def plot_session(session, trial=None, start=None, end=None, raw_only=False):
    """Event marker bars over raw voltage, with task input in a second panel."""
    grip = session['grip'][session['grip'].kind.eq('grip')].copy()
    task = session['task'].copy()
    markers = marker_table(session['events'])
    if trial is not None:
        grip = grip[grip.trial.eq(trial)]
        task = task[task.trial.eq(trial)]
        markers = markers[markers.trial.eq(trial)]
    times = pd.concat([grip.t_host_s, task.t_host_s, markers.request_s]).dropna()
    left = float(times.min()) if start is None and len(times) else (0 if start is None else start)
    right = float(times.max()) if end is None and len(times) else (left+1 if end is None else end)
    if trial is None and end is None:
        right = max(right, session['metadata'].get('duration_s', right) or right)
    if right <= left:
        right = left+1
    grip = grip[grip.t_host_s.between(left,right)]
    task = task[task.t_host_s.between(left,right)]
    shown = markers[markers.request_s.between(left,right)]
    stale = session['metadata'].get('parameters', {}).get('grip', {}).get('stale_timeout_s',1)
    blue, orange, gray = '#27649B', '#C17525', '#777777'
    with plt.rc_context({'font.family': 'DejaVu Sans', 'font.size': 10, 'axes.spines.top': False,
                         'axes.spines.right': False, 'axes.titlelocation': 'left'}):
        if raw_only:
            fig, ax = plt.subplots(figsize=(16,9), layout='constrained')
            axes = [ax]
        else:
            fig, axes = plt.subplots(2,1,figsize=(13,8),sharex=True,gridspec_kw={'height_ratios':[3,1]},layout='constrained')
        simulated = session['metadata'].get('parameters',{}).get('runtime',{}).get('simulate',False)
        fig.suptitle(f'Grip and marker timeline | {session["path"].name}\n'
                     f'{"SIMULATED" if simulated else "Hardware session"} | trial={trial if trial is not None else "all"} | '
                     f'host time {left:.2f}–{right:.2f} s'
                     + (f' | status={session["metadata"].get("status", "unknown")}' if raw_only else ''),
                     fontsize=13,ha='left',x=.06)
        for ax in axes:
            ax.grid(axis='y',color='#E8E8E8',linewidth=.6)
            ax.set_xlim(left,right)
        if len(grip) and 'voltage' in grip:
            groups = (grip.t_host_s.diff()>stale).cumsum()
            for i, (_, part) in enumerate(grip.groupby(groups)):
                axes[0].plot(part.t_host_s,part.voltage,'o-',color=blue,markersize=2,linewidth=1,
                             label='Received voltage' if i==0 else None)
            previous = grip.t_host_s.shift()
            for idx in grip.index[(grip.t_host_s-previous)>stale]:
                axes[0].axvspan(previous.loc[idx]+stale,grip.loc[idx,'t_host_s'],color=orange,alpha=.12)
            if right-grip.t_host_s.iloc[-1]>stale:
                axes[0].axvspan(grip.t_host_s.iloc[-1]+stale,right,color=orange,alpha=.12)

        else:
            axes[0].text(.5,.5,'No valid grip samples in this selection',transform=axes[0].transAxes,ha='center')
        axes[0].set(title='Raw grip voltage with event marker bars (host request times)',ylabel='Voltage (V)')
        if not raw_only and len(task) and 'smoothed' in task:
            axes[1].step(task.t_host_s,task.smoothed,where='post',color=blue,label='Task smoothed input')
            flags = task.get('grip_input_status',pd.Series('',index=task.index)).isin(['missing','stale','reader_error'])
            axes[1].scatter(task.loc[flags,'t_host_s'],task.loc[flags,'smoothed'],color=orange,marker='x',s=20,label='Stale / missing / reader error')
            axes[1].legend(loc='upper right',fontsize=8)
        elif not raw_only:
            axes[1].text(.5,.5,'No task steps in this selection',transform=axes[1].transAxes,ha='center')
        if not raw_only:
            axes[1].set(title='Input used by the task (held between updates; reset each trial)',ylabel='Normalized (0–1)',ylim=(-.05,1.05))
        # Bars denote request instants, not TTL pulse widths or EEG onset times.
        from matplotlib.lines import Line2D
        finite = grip.get('voltage', pd.Series(dtype=float)).dropna()
        if len(finite):
            low, high = float(finite.min()), float(finite.max())
            span = max(high-low, .01)
            axes[0].set_ylim(low-.08*span, high+.85*span)
        label_lanes = [-float('inf')] * 5
        for index, (_, row) in enumerate(shown.iterrows()):
            failed = row.status in ('error','no_ack') or row.readback_during_ok == False or row.readback_after_ok == False
            color = orange if failed else gray
            line = axes[0].axvline(row.request_s,color=color,ls='--' if failed else '-',
                                   alpha=.85,lw=1.2,zorder=3)
            line.set_gid('event-marker-bar')
            code = str(int(row.code)) if pd.notna(row.code) else '?'
            label = f"{row['name']} [{code}]" if len(shown)<=25 else code
            if failed:
                label += ' !'
            elif row.simulated:
                label += ' (sim)'
            near_right = row.request_s > left+.9*(right-left)
            label_y = .98
            if raw_only:
                # Separate labels for requests emitted close together; keep every bar.
                lane = next((i for i, last in enumerate(label_lanes)
                             if row.request_s-last > .014*(right-left)),
                            min(range(len(label_lanes)), key=label_lanes.__getitem__))
                label_lanes[lane] = row.request_s
                label_y -= lane*.12
            axes[0].annotate(label,xy=(row.request_s,label_y),xycoords=('data','axes fraction'),
                xytext=(-4 if near_right else 4,0),textcoords='offset points',rotation=90,
                va='top',ha='right' if near_right else 'left',fontsize=8,color=color)
        handles, labels = axes[0].get_legend_handles_labels()
        handles += [Line2D([0],[0],color=gray,lw=1.2,label='Event request with ACK'),
                    Line2D([0],[0],color=orange,lw=1.2,ls='--',label='Error / no ACK / feedback mismatch')]
        fig.legend(handles=handles,loc='outside lower center',ncol=3,fontsize=8,framealpha=.95)
        axes[-1].set_xlabel('Seconds since recording started (host clock)')
    return fig


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-root',type=Path,default=Path('data'),help='Relative to project root')
    parser.add_argument('--session',default=None)
    parser.add_argument('--trial',type=int)
    parser.add_argument('--start',type=float)
    parser.add_argument('--end',type=float)
    parser.add_argument('--save',type=Path)
    args = parser.parse_args()
    session = load_session(args.data_root,args.session)
    print('Source:',session['path'])
    print(quality_summary(session).to_string(index=False))
    fig = plot_session(session,args.trial,args.start,args.end)
    if args.save:
        if not args.save.is_absolute():
            args.save = VIEWER_ROOT / args.save
        args.save.parent.mkdir(parents=True,exist_ok=True)
        fig.savefig(args.save,dpi=150)
        print('Saved:',args.save.resolve())
    else:
        plt.show()


if __name__=='__main__':
    main()
