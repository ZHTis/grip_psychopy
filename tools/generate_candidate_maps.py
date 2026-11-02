"""Generate reproducible candidate maps without changing the active task."""
import csv,json,random,hashlib,sys
from pathlib import Path
from collections import Counter
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from gripflight.task import load_map
def generate():
    config=json.loads((ROOT/'config.json').read_text())
    source=ROOT/config['map'];original,finish=load_map(source)
    rows=sorted(original,key=lambda o:o['x'])
    gaps=[b['x']-a['x'] for a,b in zip(rows,rows[1:])]
    world=config['task']['world_height'];start=config['task']['player_start'][0]
    speed=config['task']['forward_speed'];duration=config['task']['durations']['feedback']
    preview_end=start+speed*duration
    dest=ROOT/'maps/candidates_20261102'
    dest.mkdir(parents=True,exist_ok=True)
    maps=[dict(id='Original',seed=None,objects=rows)]
    for i in range(1,11):
        seed=2026110200+i;rng=random.Random(seed)
        order=[dict(o) for o in rows];rng.shuffle(order)
        steps=list(gaps);rng.shuffle(steps);x=rows[0]['x']
        for j,o in enumerate(order):
            if j:x+=steps[j-1]
            o['x']=x
            o['y']=world-o['height']/2 if o['type']=='top' else o['height']/2
        name=f'map_{i:02d}.csv';path=dest/name
        with path.open('w',newline='') as f:
            f.write(f'# Candidate map; seed={seed}; source={config["map"]}\n')
            w=csv.DictWriter(f,fieldnames=['type','x','y','width','height','assetId']);w.writeheader();w.writerows(order)
        checked,new_finish=load_map(path)
        assert new_finish==finish
        assert Counter((o['type'],o['width'],o['height']) for o in checked)==Counter((o['type'],o['width'],o['height']) for o in rows)
        assert sorted(b['x']-a['x'] for a,b in zip(checked,checked[1:]))==sorted(gaps)
        assert all(0<=o['y']-o['height']/2 and o['y']+o['height']/2<=world for o in checked)
        assert min(gaps)>max(o['width'] for o in rows)+config['task']['player_size'][0]
        maps.append(dict(id=f'M{i:02d}',seed=seed,path=str(path.relative_to(ROOT)),objects=checked))
    assert len({json.dumps(m['objects'],sort_keys=True) for m in maps})==11
    session_order=[m['id'] for m in maps[1:]];random.Random(2026110299).shuffle(session_order)
    data=dict(world_height=world,finish_x=finish,start_x=start,travel_length=finish-start,
        speed=speed,duration_s=duration,preview_end=preview_end,player_size=config['task']['player_size'],
        source=str(source),source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        method='shuffle original gap multiset and obstacle (side,height,width) pairs independently',
        example_session_seed=2026110299,example_session_order=session_order,maps=maps)
    (dest/'manifest.json').write_text(json.dumps(data,ensure_ascii=False,indent=2))
    print(json.dumps(dict(count=len(rows),finish=finish,prefix=preview_end,order=session_order)))
    return data
if __name__=='__main__':generate()
