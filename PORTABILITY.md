# 换电脑运行

复制整个项目文件夹，保持 assets、maps、gripflight、data_viewer 与入口脚本的相对位置。项目可以放在任意盘符，文件夹名可以包含空格或中文。不需要修改 Python 源码中的路径。

## Python 环境

Python 解释器必须来自目标电脑上实际可用的环境；不能把开发电脑的虚拟环境目录直接复制过去当作已安装环境。

所有启动 bat 通过 `run_python.bat` 选择解释器，优先级为：

1. 当前环境变量 `GRIP_PYTHON`（可选，值为目标电脑解释器路径，不需要修改脚本）。
2. 项目自己的 `.venv\Scripts\python.exe`（应在目标电脑重新创建）。
3. 当前 PATH / 已激活环境中的 `python`。

使用已安装 PsychoPy 的环境时，激活该环境后执行 `python run_task.py`，或在 PsychoPy Coder 中打开 run_task.py。双击 bat 时，需保证上述选择能找到具有 PsychoPy 依赖的解释器。数据查看笔记本可使用另一个装有 pandas、numpy、matplotlib、ipykernel 的环境。

## 路径规则

| 设置 | 相对基准 |
|---|---|
| run_task.py 的 --config | 项目根目录 |
| config 内 assets、map、output | 项目根目录，与配置文件放在哪个子目录无关 |
| test_module.py 输出 test_data | 项目根目录 |
| view_data.py --data-root / 笔记本 DATA_ROOT | 项目根目录，默认 data |
| view_data.py --save | data_viewer 目录 |
| 笔记本 exports | data_viewer 目录 |

示例（在项目根目录，Python 来自已激活环境）：

```powershell
python run_task.py --simulate
python run_task.py
python run_task.py --config configs/experiment.json
python test_module.py markers --port COM10
python data_viewer/view_data.py --data-root data --save exports/overview.png
```

从其他工作目录执行入口也可以：给出入口脚本的路径，脚本内部仍按它所在的项目定位其他文件。

笔记本从项目或 data_viewer 文件夹打开即可，选择目标电脑的内核。交付的笔记本已清空开发电脑的缓存输出，运行全部单元格会重新显示该电脑的数据。

COM6 / COM10 是设备编号，不是文件路径；迁移后请按目标电脑识别结果修改 config.json。不要默认另一台电脑会分配相同 COM 号。

历史 data/test_data/verification 中已记录的机器路径是当时的来源信息，不参与运行路径解析，保留以便追溯。已有 .history 属于编辑器历史，也不参与当前运行。
