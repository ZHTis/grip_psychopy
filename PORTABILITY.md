# 换电脑运行

复制整个项目文件夹，保持 assets、maps、gripflight、data_viewer 与入口脚本的相对位置。项目可以放在任意盘符，文件夹名可以包含空格或中文。不需要修改 Python 源码中的路径。

## Python 环境

### Mac 启动与跨平台串口

串口名称直接交给 pyserial：Windows 使用 `COM6` 等名称，Mac 使用 `/dev/cu.usbmodem…` 或 `/dev/cu.usbserial…`。无需修改 Python 源码。

Mac 在项目目录中执行：

```bash
bash run_python.sh run_task.py --list-ports
bash launch_simulation.command
# 默认已配置：握力 /dev/cu.usbmodem1301，打标 /dev/cu.usbmodem1401
bash launch_hardware.command
# 更换接口后，可以覆盖默认端口：
bash launch_hardware.command --grip-port /dev/cu.usbmodem1301 --marker-port /dev/cu.usbmodem1401
```

Windows 在项目目录的 PowerShell 中执行：

```powershell
.\run_python.bat run_task.py --list-ports
.\launch_simulation.bat
.\launch_hardware.bat --grip-port COM6 --marker-port COM10
```

命令行端口优先于 `config.json` 中的 `grip.port` / `markers.port`，只影响本次运行，不改写文件；实际使用的值会保存到会话 metadata。不传端口参数时仍使用配置文件。也可以为每台电脑准备配置文件，通过 `--config` 指定。两块板应使用不同端口，逐块插入并列出端口可以确认对应关系；程序不会自动猜测板子的用途。`--list-ports` 只列设备，不启动实验或创建数据会话。

Mac 的 `run_python.sh` 依次选择 `GRIP_PYTHON`、项目 `.venv/bin/python`、`/Applications/PsychoPy.app` 内置 Python、PATH 中的 `python3`。使用内置 Python 时自动为子进程设置 `PYTHONHOME`。两个 `.command` 文件也可双击启动。`launch_hardware.command` 默认传入已确认的 Mac 端口：握力板（原 COM6）为 `/dev/cu.usbmodem1301`，打标板（原 COM10）为 `/dev/cu.usbmodem1401`；用户追加的端口参数可覆盖这些默认值，包括使用 `--config` 时。Windows 启动脚本仍使用配置文件中的 COM6 / COM10。

Python 解释器必须来自目标电脑上实际可用的环境；不能把开发电脑的虚拟环境目录直接复制过去当作已安装环境。

所有启动 bat 通过 `run_python.bat` 选择解释器，优先级为：

1. 当前环境变量 `GRIP_PYTHON`（可选，值为目标电脑解释器路径，不需要修改脚本）。
2. 项目自己的 `.venv\Scripts\python.exe`（应在目标电脑重新创建）。
3. 当前 PATH / 已激活环境中的 `python`。

使用已安装 PsychoPy 的环境时，激活该环境后执行 `python run_task.py`，或在 PsychoPy Coder 中打开 run_task.py。双击 bat 时，需保证上述选择能找到具有 PsychoPy 依赖的解释器。数据查看笔记本可使用另一个装有 pandas、numpy、matplotlib、ipykernel 的环境。

## 显示器

默认 `config.json` 设置 `display.fullscreen=true`、`display.screen=1`，在第二块显示器全屏运行（PsychoPy 从 0 开始编号）。请将外接屏设为扩展显示；如果外接屏被系统排列为第 0 块屏幕，则将 `screen` 改为 `0`。按 Esc 退出实验。硬件模式和模拟模式共用此设置。

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
