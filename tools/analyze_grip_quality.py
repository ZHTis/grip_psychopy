"""Read-only UNO acquisition audit; reports measured frames, not task refresh ticks."""
import argparse
import json
import sqlite3
from datetime import datetime
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties

FONT=Path('/System/Library/Fonts/STHeiti Light.ttc')
if FONT.exists():
    from matplotlib import font_manager
    font_manager.fontManager.addfont(str(FONT))
    plt.rcParams['font.family']=FontProperties(fname=str(FONT)).get_name()
plt.rcParams.update({'axes.unicode_minus':False,'font.size':10,'figure.facecolor':'#f6f8fc','axes.facecolor':'white','axes.spines.top':False,'axes.spines.right':False})


def metrics(rows):
    valid=[r for r in rows if r['p'].get('valid') is True and r['p'].get('device_timed') is True]
    if len(valid)<2: raise ValueError('At least two valid timed UNO frames required')
    host=np.array([r['t'] for r in valid]); volts=np.array([r['p']['voltage'] for r in valid])
    intervals=[]; gaps=[]; discontinuities=[]; cumulative=[0]; dev_times=[0.0]; total_missing=0
    for a,b in zip(valid,valid[1:]):
        same=a['p'].get('acquisition_id')==b['p'].get('acquisition_id')
        ds=(b['p']['device_sequence']-a['p']['device_sequence'])%(2**32)
        du=(b['p']['device_micros']-a['p']['device_micros'])%(2**32)
        if same and 0<ds<2**31 and 0<du<2**31:
            intervals.append({'t_host_s':b['t'],'sequence_step':ds,'device_interval_us':du,'per_sample_ms':du/ds/1000})
            dev_times.append(dev_times[-1]+du/1e6)
            if ds>1:
                total_missing+=ds-1
                gaps.append({'t_host_s':b['t'],'before_sequence':a['p']['device_sequence'],'after_sequence':b['p']['device_sequence'],'missing_points':ds-1,'host_interval_s':b['t']-a['t']})
        else:
            discontinuities.append({'t_host_s':b['t'],'reason':'acquisition change, duplicate/reset or ambiguous clock jump','sequence_step_mod32':ds,'micros_step_mod32':du})
            dev_times.append(dev_times[-1])
        cumulative.append(total_missing)
    diffs=np.diff(host); unit=np.array([x['per_sample_ms'] for x in intervals]); device_span=sum(x['device_interval_us'] for x in intervals)/1e6
    device_steps=sum(x['sequence_step'] for x in intervals)
    steady=host[host>=host[0]+2]
    invalid=[{'t_host_s':r['t'],**r['p']} for r in rows if r['kind']=='grip_invalid']
    full_bins=int(np.floor(host[-1]-host[0])); counts=np.histogram(host-host[0],bins=np.arange(full_bins+1))[0] if full_bins else np.array([])
    summary=dict(valid_frames=len(valid),placeholder_missing_rows=sum(r['kind']=='grip' and r['p'].get('valid') is False for r in rows),
        first_host_s=float(host[0]),last_host_s=float(host[-1]),host_span_s=float(host[-1]-host[0]),device_span_s=device_span,
        first_sequence=valid[0]['p']['device_sequence'],last_sequence=valid[-1]['p']['device_sequence'],
        inferred_missing_points=total_missing,missing_fraction=total_missing/(len(valid)+total_missing),
        sequence_discontinuities=discontinuities,sequence_gaps=gaps,
        device_sampling_hz=device_steps/device_span if device_span else None,
        observed_delivery_over_device_time_hz=len(intervals)/device_span if device_span else None,
        host_average_hz=(len(host)-1)/(host[-1]-host[0]),
        host_after_initial_2s_hz=(len(steady)-1)/(steady[-1]-steady[0]) if len(steady)>1 else None,
        device_period_ms={'min':float(unit.min()),'median':float(np.median(unit)),'max':float(unit.max()),'p99':float(np.percentile(unit,99))},
        host_interval_ms={'min':float(diffs.min()*1000),'median':float(np.median(diffs)*1000),'p99':float(np.percentile(diffs,99)*1000),'max':float(diffs.max()*1000)},
        host_gaps_over_500ms=[{'before_t_s':float(a),'after_t_s':float(b),'duration_s':float(b-a)} for a,b in zip(host,host[1:]) if b-a>.5],
        full_1s_host_counts={'count':len(counts),'min':int(counts.min()) if len(counts) else None,'max':int(counts.max()) if len(counts) else None},
        invalid_records=invalid,shutdown_partial_lines=sum(x.get('error')=='Incomplete line at shutdown' for x in invalid),
        a0_voltage_range=[float(volts.min()),float(volts.max())])
    return summary,dict(host=host,volts=volts,device_times=np.array(dev_times),cumulative=np.array(cumulative),intervals=intervals,counts=counts)


def read_session(directory):
    metadata=json.loads((directory/'metadata.json').read_text())
    # Transaction snapshot includes committed WAL data without modifying session records.
    with sqlite3.connect((directory/'session.sqlite3').resolve().as_uri()+'?mode=ro',uri=True) as db:
        db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
        rows=[dict(id=i,kind=k,t=t,phase=phase,p=json.loads(p)) for i,k,t,phase,p in db.execute("SELECT id,kind,t,phase,payload FROM records WHERE kind IN ('grip','grip_invalid','event','diagnostic') ORDER BY id")]
    return metadata,rows


def plot_latest(summary,arrays,rows,out):
    h=arrays['host']; t=h-h[0];rate=summary['configured_rate_hz']
    fig,axs=plt.subplots(4,1,figsize=(13,12),constrained_layout=True)
    fig.suptitle(f"最新 UNO 采集质量｜{summary['session']}\n{summary['valid_frames']:,} 点 · 序号缺失 {summary['inferred_missing_points']} 点 · 设备 {summary['device_sampling_hz']:.3f} Hz · {summary['status']}",fontsize=15)
    ax=axs[0];ax.plot(t,arrays['volts'],color='#176ba0',lw=.75)
    shades=set()
    for r in rows:
        name=r['p'].get('name','')
        if r['kind']=='event' and name.endswith('_start'):
            if 'squeeze' in name:color,label='#f6b4b8','握紧阶段'
            elif 'rest' in name:color,label='#b4e7c4','休息阶段'
            else:continue
            start=max(0,r['t']-h[0]);end=min(t[-1],start+r['p'].get('duration_s',0))
            ax.axvspan(start,end,color=color,alpha=.45,label=label if label not in shades else None);shades.add(label)
    ax.set(ylabel='A0 电压（V）',title='原始握力信号与已记录阶段')
    if shades: ax.legend(loc='upper right',fontsize=9)
    ax=axs[1];ax.step(np.arange(len(arrays['counts']))+.5,arrays['counts'],where='mid',color='#176ba0',label='主机每整秒收到的有效帧')
    ax.axhline(rate,ls='--',color='#db7b21',label=f'配置 {rate:g} Hz')
    ax.set(ylabel='帧 / 秒',title='电脑接收速率（完整 1 秒窗口；不含末尾不足 1 秒）');ax.legend(fontsize=9)
    ax=axs[2];ax.plot(t[1:],np.diff(h)*1000,lw=.6,color='#788eab',alpha=.8,label='相邻帧主机接收间隔')
    intervals=arrays['intervals'];ax.plot([x['t_host_s']-h[0] for x in intervals],[x['per_sample_ms'] for x in intervals],lw=.7,color='#198452',label='设备间隔 / 序号步长')
    ax.axhline(1000/rate,color='#db7b21',ls='--',lw=.8)
    ax.set(ylabel='间隔（ms）',title='设备计时与主机接收计时分别检查');ax.legend(fontsize=9)
    ax=axs[3];ax.step(t,arrays['cumulative'],where='post',color='#c83e4d',label='由序号跳号确认的累计缺失点')
    for gap in summary['host_gaps_over_500ms']:
        ax.axvspan(gap['before_t_s']-h[0],gap['after_t_s']-h[0],color='#ffb95c',alpha=.5)
    ax.set(ylabel='累计缺失（点）',xlabel='从首个有效帧起的主机时间（秒）',ylim=(-.2,max(1,summary['inferred_missing_points']*1.2)),title='缺点位置：只统计首末已记录序号之间；接收间隔 > 0.5 秒用橙色标记')
    if not summary['inferred_missing_points']:
        ax.text(.5,.6,'未发现内部序号缺失',transform=ax.transAxes,ha='center',color='#198452',fontsize=14)
    for ax in axs:ax.grid(alpha=.18);ax.set_xlim(0,t[-1])
    fig.savefig(out/'latest_quality.png',dpi=160);plt.close(fig)


def plot_overview(summaries,out):
    fig,axs=plt.subplots(3,1,figsize=(13,10),constrained_layout=True)
    labels=[s['session'][:8]+'\n'+s['session'].split('_')[1][:2]+':'+s['session'].split('_')[1][2:4]+':'+s['session'].split('_')[1][4:] for s in summaries];x=np.arange(len(labels));width=.24
    for offset,key,label,color in [(-width,'device_sampling_hz','设备时钟采样率','#158058'),(0,'host_average_hz','全部有效帧的主机平均接收率','#6393c5'),(width,'host_after_initial_2s_hz','排除最初 2 秒的主机接收率','#db903a')]:
        values=[s[key] if s[key] is not None else np.nan for s in summaries];axs[0].bar(x+offset,values,width,label=label,color=color)
        for xx,v in zip(x+offset,values):
            if np.isfinite(v):axs[0].text(xx,v+.12,f'{v:.2f}',ha='center',fontsize=9)
    axs[0].set(ylim=(250,max(s['host_average_hz'] for s in summaries)+2),ylabel='Hz',title='采样率对比（纵轴从 250 Hz 起；初始缓冲会抬高主机平均值）');axs[0].axhline(256,ls='--',color='#999',lw=.8);axs[0].legend(loc='upper left',fontsize=9)
    axs[1].bar(x-.16,[s['inferred_missing_points'] for s in summaries],.3,color='#ca495a',label='内部序号缺失点数')
    axs[1].bar(x+.16,[s['shutdown_partial_lines'] for s in summaries],.3,color='#dc9c44',label='退出时残留半行（不计作内部丢点）')
    axs[1].set(ylim=(0,2),ylabel='点 / 行',title='丢失与退出边界分开统计');axs[1].legend(fontsize=9)
    for i,s in enumerate(summaries):axs[1].text(i-.16,.06,str(s['inferred_missing_points']),ha='center')
    axs[2].bar(x,[s['host_interval_ms']['max'] for s in summaries],color='#6d82ae')
    for i,s in enumerate(summaries):
        axs[2].text(i,s['host_interval_ms']['max']+.15,f"{s['host_interval_ms']['max']:.2f} ms\n{s['valid_frames']:,} 点 / {s['device_span_s']:.2f} s",ha='center',fontsize=9)
    axs[2].set(ylabel='ms',title=f"最大主机帧间隔；超过 0.5 秒的接收间断共 {sum(len(s['host_gaps_over_500ms']) for s in summaries)} 处",ylim=(0,max(s['host_interval_ms']['max'] for s in summaries)*1.45))
    for ax in axs:ax.set_xticks(x,labels);ax.grid(axis='y',alpha=.15)
    fig.suptitle(f'最近 {len(summaries)} 次含真实 UNO 数据的记录（最新在左）\n首末有效帧之间的质量审计，不代表会话完整完成',fontsize=15)
    fig.savefig(out/'recent_five_quality.png',dpi=160);plt.close(fig)


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--data-root',type=Path,required=True);ap.add_argument('--output',type=Path,required=True);ap.add_argument('--count',type=int,default=5);args=ap.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    summaries=[];skipped=[];latest=None
    for d in sorted(args.data_root.iterdir(),reverse=True):
        if not d.is_dir() or not d.name[:8].isdigit() or not (d/'session.sqlite3').exists():continue
        meta,rows=read_session(d)
        if meta.get('parameters',{}).get('runtime',{}).get('simulate'):skipped.append({'session':d.name,'reason':'simulated'});continue
        if sum(r['kind']=='grip' and bool(r['p'].get('valid')) and bool(r['p'].get('device_timed')) for r in rows)<2:
            skipped.append({'session':d.name,'reason':'no valid timed UNO frames','status':meta.get('status'),'diagnostics':[r['p'] for r in rows if r['kind']=='diagnostic']});continue
        s,a=metrics(rows);s.update(session=d.name,source=str((d/'session.sqlite3').resolve()),status=meta.get('status'),configured_rate_hz=meta['parameters'].get('grip',{}).get('sample_rate',256))
        s['snapshot_last_record_id']=max(r['id'] for r in rows)
        s['event_records']=[dict(t_host_s=r['t'],**r['p']) for r in rows if r['kind']=='event']
        summaries.append(s)
        if latest is None:latest=(s,a,rows)
        if len(summaries)>=args.count:break
    if not summaries:raise SystemExit('No measured timed UNO sessions found')
    report=dict(snapshot_local_time=datetime.now().astimezone().isoformat(),selection='latest sessions containing real timed UNO frames',sessions=summaries,skipped=skipped,
        limits=['No inference of missing points before first or after last recorded sequence.', 'An open recording is a committed snapshot, not evidence of session completion.', 'Shutdown incomplete lines are counted separately from internal sequence gaps.', 'Device sampling rate uses sequence steps / device elapsed time; host average uses observed intervals / host elapsed time.'])
    (args.output/'quality_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    plot_latest(*latest,args.output);plot_overview(summaries,args.output)
    for s in summaries:print(json.dumps({k:s[k] for k in ['session','status','valid_frames','device_span_s','inferred_missing_points','device_sampling_hz','host_average_hz','host_after_initial_2s_hz','host_interval_ms','shutdown_partial_lines']},ensure_ascii=False))
    print('OUTPUT',args.output.resolve())

if __name__=='__main__':main()
