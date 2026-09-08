"""Rebuild the notebook template with nbformat; does not modify session data."""
from pathlib import Path
import nbformat as nbf

root = Path(__file__).resolve().parent
nb = nbf.v4.new_notebook()
md, code = nbf.v4.new_markdown_cell, nbf.v4.new_code_cell
nb.cells = [
md('''# GripFlight：握力与打标数据查看

## 使用目标
选择一次实验，检查握力变化、数据间断，以及任务事件的打标状态。所有读取来自原始导出的 CSV，不连接 Arduino，也不修改实验数据。

从上到下运行所有单元格；之后修改“选择数据”单元格，再重新运行后续单元格即可。图中英文标注避免不同电脑的中文字体缺失。
'''),
md('''## 数据与时间含义

- **Voltage (V)** 是握力设备的电压，没有力学校准，不能直接称为 N 或 kg。
- **Task smoothed input** 是任务使用的 0–1 输入；无新数据时可能保持旧值，图中橙色叉号标记已记录的 stale/missing/reader_error。
- 横轴统一使用 `t_host_s`。握力时间是电脑收到完整行的时间，不是 ADC 采样时间。
- ACK/DONE 的横坐标是电脑收到回执的时间，不是脑电采样时刻；模拟回执也会单独统计。
- `device_pulse_ms` 来自同一事件的 Arduino ACK/DONE 计数差，处理一次 micros 回绕；它不是示波器测量。
- 电压曲线不会跨越超过 stale_timeout_s 的采样间隔连线。橙色浅色区域表示采样过期区间。

### 关键假设
查看已结束并导出 CSV 的 session。`status=complete` 只表示任务流程完成，不代表握力和硬件打标全部成功。未找到 CSV 时明确报告缺失，不自动把 SQLite 中未导出的记录当成已查看。
'''),
md('### 1. 导入查看脚本'),
code('''from pathlib import Path
import sys
import pandas as pd
import matplotlib.pyplot as plt
from IPython.display import display

SEARCH_ROOTS = [Path.cwd(), *Path.cwd().parents]
VIEWER_DIR = next((p for base in SEARCH_ROOTS for p in [base, base / 'data_viewer']
                   if (p / 'view_data.py').exists()), None)
if VIEWER_DIR is None:
    raise RuntimeError('请从项目文件夹或 data_viewer 打开此笔记本，再选择目标电脑上的 Python 内核。')
if str(VIEWER_DIR) not in sys.path:
    sys.path.insert(0, str(VIEWER_DIR))
# Load the script beside this notebook, without reusing an old cached module.
import importlib.util
spec = importlib.util.spec_from_file_location('grip_data_viewer_current', VIEWER_DIR / 'view_data.py')
viewer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(viewer)
list_sessions = viewer.list_sessions
load_session = viewer.load_session
quality_summary = viewer.quality_summary
marker_table = viewer.marker_table
plot_session = viewer.plot_session
print('Loaded script:', viewer.__file__)
print('Python:', sys.executable)
print('Viewer:', VIEWER_DIR.resolve())'''),
md('### 2. 选择数据\n`SESSION_NAME=None` 默认选择最近一次**非模拟**且已导出 CSV 的 session；没有非模拟记录才选择模拟记录。可以从下面表格复制完整 session 名称。'),
code('''DATA_ROOT = 'data'   # 相对于项目根目录；独立测试数据可改成 'test_data'
SESSION_NAME = None  # 例如 '20260908_163647_ddebedaf'
TRIAL = None         # None=全部；例如 1=第一个 trial
START_S = None       # 例如 5.0；与 t_host_s 相同时间基准
END_S = None         # 例如 20.0

sessions = list_sessions(DATA_ROOT)
display(sessions.head(30))'''),
md('### 3. 读取与数据质量检查'),
code('''session = load_session(DATA_ROOT, SESSION_NAME)
print('Selected source:', session['path'])
display(quality_summary(session))
print('Runtime warnings:', session['metadata'].get('runtime_warnings', {}))
print('Dropped records:', session['metadata'].get('dropped_records', 0))'''),
md('### 4. 原始握力图叠加 event marker bars\n上图：原始电压曲线，事件请求时刻直接叠加竖条并标注事件名称和码值；灰色实线表示有 ACK，橙色虚线及 ! 表示失败或没有 ACK，(sim) 表示模拟事件。竖条表示事件时刻，不代表脉冲持续时间。下图保留任务使用的握力。不再单独绘制打标时间线；ACK/DONE 时间仍可在核对表查看。事件较密时设置 START_S / END_S 放大。'),
code('''fig = plot_session(session, trial=TRIAL, start=START_S, end=END_S)
plt.show()'''),
md('### 5. 打标核对表\n按 request 的 `id` 与回执的 `event_id` 关联，不按重复的 code 关联。`request_to_ack_ms` 包含队列、串口和回传延迟，不能解释为“EEG 同步误差”。'),
code('''markers = marker_table(session['events'])
selected_markers = markers if TRIAL is None else markers[markers.trial.eq(TRIAL)]
if START_S is not None:
    selected_markers = selected_markers[selected_markers.request_s >= START_S]
if END_S is not None:
    selected_markers = selected_markers[selected_markers.request_s <= END_S]
display(selected_markers.head(80))
display(selected_markers.groupby(['status', 'simulated'], dropna=False).size().rename('events').reset_index())'''),
md('### 6. 原始数据与异常行\n以下表格保留完整 session 范围，方便追查筛选范围之外的问题。异常行只用于检查，不作为有效握力画入曲线。'),
code('''grip = session['grip']
display(grip.head(12))
display(grip[grip.kind.eq('grip_invalid')].head(12))
display(session['diagnostics'].tail(15))'''),
md('### 7. 可选：导出当前图与筛选后的打标表\n默认不写入文件。设为 True 后写到 data_viewer/exports，不覆盖原始记录。'),
code('''EXPORT = False
if EXPORT:
    stamp = pd.Timestamp.now().strftime('%Y%m%d_%H%M%S_%f')
    output = VIEWER_DIR / 'exports' / f'{session["path"].name}_{stamp}'
    output.mkdir(parents=True, exist_ok=False)
    fig.savefig(output / 'grip_markers.png', dpi=180, bbox_inches='tight')
    selected_markers.to_csv(output / 'marker_summary.csv', index=False, encoding='utf-8-sig')
    print('Saved:', output.resolve())'''),
md('''## 阅读结果
先确认所选 session 是否为模拟、是否有有效握力、是否发生长采样间断，再检查每次打标的回执。请求存在但没有 ACK 时，不能判定硬件输出成功；即使有 ACK，也需要脑电软件记录来确认接收链路。重新运行笔记本会按当前参数重新读取数据，缓存的输出只对应上方打印的 Selected source。''')]
nb.metadata = {'kernelspec': {'display_name': 'Python 3 (data viewer)', 'language': 'python', 'name': 'python3'},
               'language_info': {'name': 'python'}}
nbf.validate(nb)
nbf.write(nb, root/'grip_markers.ipynb')
print(root/'grip_markers.ipynb')
