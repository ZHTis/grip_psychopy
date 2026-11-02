"""Static geometry previews; axes are game units, not screen pixels."""
import json,os
from pathlib import Path
os.environ.setdefault('MPLCONFIGDIR','/private/tmp/grip-map-mpl')
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle,Patch
from matplotlib import font_manager
ROOT=Path(__file__).resolve().parents[1]
data=json.loads((ROOT/'maps/candidates_20261102/manifest.json').read_text())
out=ROOT/'data_viewer/exports/outputs/grip-map-candidates-20261102'
out.mkdir(parents=True,exist_ok=True)
font=Path('/System/Library/Fonts/STHeiti Light.ttc')
if font.exists():
    font_manager.fontManager.addfont(str(font))
    plt.rcParams['font.family']=font_manager.FontProperties(fname=str(font)).get_name()
plt.rcParams.update({'font.size':10,'axes.spines.top':False,'axes.spines.right':False,'axes.unicode_minus':False})
colors={'top':'#7554A3','bottom':'#168A80'}
def draw(ax,objects,end,number=False):
    ax.set_facecolor('#F5F8FC')
    for i,o in enumerate(objects,1):
        left=o['x']-o['width']/2
        if left>end:continue
        ax.add_patch(Rectangle((left,o['y']-o['height']/2),o['width'],o['height'],facecolor=colors[o['type']],edgecolor='none'))
        if number:ax.text(o['x'],o['y']-o['height']/2-5 if o['type']=='top' else o['y']+o['height']/2+3,str(i),ha='center',va='center',fontsize=8,color='#46536B')
    ax.plot(data['start_x'],50,'o',color='#E69B39',markersize=5)
    ax.set_xlim(0,end);ax.set_ylim(0,data['world_height'])
    ax.set_yticks([0,45,90]);ax.set_ylabel('Y')
    ax.grid(axis='x',color='#DCE3EB',lw=.5);ax.set_axisbelow(True)
    ax.tick_params(axis='both',labelsize=9)
for m in data['maps']:
    fig,axes=plt.subplots(2,1,figsize=(12,4.8),dpi=120)
    draw(axes[0],m['objects'],data['finish_x'])
    axes[0].axvspan(0,data['preview_end'],color='#B9D8F4',alpha=.22,zorder=0)
    axes[0].axvline(data['preview_end'],color='#3B75AA',ls='--',lw=1)
    axes[0].set_title('全长：终点 X = 9729（横轴压缩）',loc='left',fontsize=11)
    draw(axes[1],m['objects'],data['preview_end'],True)
    axes[1].set_title('前 45 秒放大：X = 0–1370；数字为障碍物编号',loc='left',fontsize=11)
    axes[1].set_xlabel('横向位置 X（游戏坐标单位）')
    fig.subplots_adjust(left=.055,right=.99,top=.90,bottom=.12,hspace=.65)
    fig.legend(handles=[Patch(color=colors['top'],label='顶部障碍'),Patch(color=colors['bottom'],label='底部障碍')],loc='upper right',ncol=2,frameon=False,bbox_to_anchor=(.995,1.01))
    fig.savefig(out/(m['id']+'.png'),facecolor='white');plt.close(fig)
fig,axes=plt.subplots(10,1,figsize=(12,15),dpi=120)
for ax,m in zip(axes,data['maps'][1:]):
    draw(ax,m['objects'],data['preview_end'])
    ax.set_ylabel(m['id'],rotation=0,labelpad=22,fontweight='bold')
    ax.set_xticks(range(0,1400,200))
axes[-1].set_xlabel('横向位置 X（游戏坐标单位）')
fig.suptitle('10 张候选地图：当前前 45 秒路段对比',fontsize=17,x=.055,ha='left')
fig.subplots_adjust(left=.08,right=.99,top=.95,bottom=.04,hspace=.50)
fig.savefig(out/'ten_maps_preview.png',facecolor='white');plt.close(fig)
print(out)
