> 更新（2026-09-08）：主任务现采用持续运行策略，仅完成全部 trial 或按 Esc 主动结束。握力无数据/过期时保持最后有效值，无历史值则用 grip_min；数据恢复后自动使用新值。打标端口或回执失败后，本次运行停用硬件打标但继续保存本地事件，不会补发旧事件或自动重新连接。延迟超过阈值时重新安排后续时间步并继续；运行中保存错误仅警告，可能造成记录缺失。metadata 记录 runtime_warnings / dropped_records，task 的 payload_json 标记 grip_input_status / grip_age_s。正常完成不代表硬件采集和打标成功。配置损坏、缺少依赖、画面无法创建等启动失败仍需修复。独立 test_module.py 测试仍严格报告硬件错误。下文早期的“超时中止”说明以本更新为准。
# GripFlight → PsychoPy

复用 BCI2000 GripFlight 的原始背景、小鸟 SVG 和两份 CSV 地图；握力读取、打标、数据保存各自独立。任务电脑运行 PsychoPy，脑电继续由脑电电脑自己的软件记录。

## 快速开始

Mac 使用 `bash launch_simulation.command` 模拟运行。串口可通过 `--grip-port` / `--marker-port` 为本次运行指定，使用 `--list-ports` 查询本机端口；Mac 与 Windows 完整命令见 [PORTABILITY.md](PORTABILITY.md#mac-启动与跨平台串口)。

先在目标电脑选择安装了 PsychoPy 的 Python 环境。启动脚本不再依赖固定安装路径，解释器选择及迁移步骤见 [PORTABILITY.md](PORTABILITY.md)。

1. 双击 `launch_simulation.bat`，无需 Arduino，按住鼠标左键增加握力，松开降低握力，Esc 中止。模拟数据明确标记为 simulated。
2. 修改 `config.json` 中 participant、session、grip.port 和 markers.port。两个串口必须不同。握力端口沿用 COM6 / 115200；打标端口当前为 COM10，迁移后请填写目标电脑的实际端口。
3. 将 `arduino/marker_board/marker_board.ino` 上传到**第二块打标 Arduino**。第一块握力 Arduino 的固件不需修改，串口格式仍为 `temperature,voltage\n`。
4. 先运行下面的两个串口独立测试，核对脑电软件收到的码及接线，再双击 `launch_hardware.bat`。

依赖：PsychoPy、pyserial、Pillow、PyQt6。请确认目标电脑的实验环境带有这些组件。若使用其他环境，在该环境安装 `requirements.txt`，并单独安装兼容的 PsychoPy。无需修改启动脚本路径，按 PORTABILITY.md 选择解释器即可。

## 实验前握力校准

默认开启 `config.json.calibration.enabled`。每次启动先等待传感器数据，然后按顺序：

1. “正在准备 请勿触碰”：采集 5 秒零握力。
2. “最大力度握紧”：1 秒计时进度条，采集第 1 次峰值。
3. “请松开握力器 休息”：倒计时 30 秒。
4. 再握紧 1 秒，休息 30 秒，再握紧 1 秒，共 3 次。
5. 显示零点、三个峰值、参考最大值、实际 lift_gain 及理论平衡比例；按空格进入原任务，Esc 结束并保留已采数据。

零点取 `abs(voltage × grip.gain)` 的中位数，三个峰值取各自测量窗口内全部有效采样的最大值，参考最大握力取三个峰值中的最大值。正式任务使用本次零点作为 `grip_min`、参考最大值作为 `grip_max`。记录仍是传感器电压/增益后的数值，没有标定成 N 或 kg；一秒窗口内的峰值不等同于经其他测量协议验证的生理最大力。

默认 `lift_mode="keep"` 保留配置中的 `task.lift_gain`。稳态参考公式为 `平衡握力比例 = gravity / lift_gain`。例如 gravity=25、lift_gain=140，对应本次校准范围的约 17.9%。这只表示持续归一化输入下升力与重力相等，不保证小鸟在任意速度或地图位置悬停。

如要按目标比例计算，可设 `calibration.lift_mode="target_fraction"`，并设置 `target_fraction`（例如 0.2 表示 20%）；此时实际 `lift_gain=gravity/target_fraction`。配置文件本身不会被运行过程改写。

每次 session 新增 **`experiment_setup.json`**：同一个文件包含零点/三次握力的完整采样（电压、raw、主机时间、记录 ID）、各次统计与峰值样本、校准参考、lift_gain 候选参考、实际 lift_gain、原始配置、生效配置、地图 CSV 全文/解析对象/SHA256、模拟标识和最终状态。校准中定期保存，结束后更新；原始 `grip.csv` / SQLite 仍保存完整采样，校准样本的 phase 为 `calibration_*`、trial=0。校准阶段事件仅保存为本地 `event`，不新增 Arduino 事件码；正式任务的打标规则保持原样。

校准不使用过期/保持值。采样不足、连续间断超过 `max_gap_s`（默认 0.3 秒），或任一次握力峰值没有超过零点至少 `max(min_range, 5×零点标准差)`，会停止进入正式实验；修复连接或重新测量后再启动。要求已创建可写的 session 目录，以保存这份实验配置。正式任务开始后的持续运行策略仍适用。

`zero_s`、`squeeze_s`、`rest_s` 可调整时长；`min_samples`、`max_gap_s`、`min_range` 可按实际传感器采样率设置。`font="auto"` 在 Mac 使用 PingFang SC、Windows 使用 Microsoft YaHei，也可指定已安装的中文字体。

模拟模式也显示校准：零点和休息时松开鼠标，三次握紧提示出现时按住鼠标左键，第三次结束后松开并按空格进入任务。模拟记录明确标记。`--simulate --headless` 是快速逻辑测试，跳过校准且在归档中标记 `skipped_headless`；不要把这类记录当作实际校准。

## 原任务逻辑及参数

迁移依据：`src/core/Application/GripFlightTask/GripFlightTask.cpp`、`FlightPhysics.cpp`、`SideScrollScene.cpp`、`MapLoader.cpp`，以及 `src/shared/modules/application/FeedbackTask.cpp`。

| 项目 | 保留行为 |
|---|---|
| run | 1 秒 Ready，然后 10 个 trial |
| trial | Prepare 1 秒 → 飞行最多 45 秒 → 结果 1 秒 |
| ITI | 非最后一个 trial 的结果结束后再等待 1 秒；最后一个 trial 无 ITI |
| 成功 | 到达地图终点，或反馈时间结束且未碰撞 |
| 失败 | 小鸟碰到世界上/下边界或地图矩形；碰撞优先于到达终点 |
| 反馈重置 | 每次飞行从 (20,50) 开始，垂直速度和平滑握力归零 |
| 输入 | abs(voltage × Gain)，按 0.81–1.20 归一化到 0–1，smoothing=1 |
| 物理 | forward=30，lift=150，gravity=15，damping=0.98，碰撞框 20×20 |
| 地图 | 默认 random.csv，直接加载固定 CSV，不在每 trial 重新随机生成 |
| 终点 | CSV 所有物体的最大右边缘再加 50 |
| 镜头 | worldHeight=90，宽度随窗口宽高比，鸟到视野 30% 后相机跟随 |
| 小鸟显示 | 维持原图比例；与 BCI2000 AdjustWidth 一致，碰撞框不随图像宽度缩小 |

**block 的源码含义：** 当前 GripFlight 没有实验 block 分组或 block 休息实现。共享 `GripForceTask_GripForceSource.prm` 内的 NumberBlocks / TrialsPerBlock / BlockLiftGains 属于另一个 GripForceTask，GripFlight 未使用。本迁移按实际 GripFlight 实现保留每 run 10 trial，数据中 block=1；没有擅自加入另一任务的 block 规则。若你实际运行的是另一版，需要以那版源码/参数为依据补充。

BCI2000 的 sample block 是信号处理时间步，不是实验 block。原 source 默认 SampleBlockSize=32、SamplingRate=256 Hz，因此物理步长为 0.125 秒。若你在 Operator 中改过这两项，需要同步修改 config。阶段时长按原代码截断为整数 sample block；原 FeedbackTask 的同一次处理中的阶段切换及“反馈至少一个数据块”规则也保留。PsychoPy 的画面刷新独立于此步长；这不代表串口数据被重采样到 256 Hz。

保存每条 Arduino 完整数据行，任务每个物理步使用当时最近的有效读数。与旧版一样任务用最新电压控制，但新版不会像旧 source 那样只留下最后一条读数并复制填满整个数据块。无效行、超长行及停止时未完整的行也记录；1 秒没有有效新读数则中止并保存错误，不会无限使用旧握力。

## 三个独立模块和测试

| 模块 | 实现 | 自动测试 |
|---|---|---|
| 握力串口 | gripflight/grip.py | tests/test_grip.py |
| Arduino 打标 | gripflight/markers.py | tests/test_markers.py |
| 数据/参数保存 | gripflight/recording.py | tests/test_recording.py |

在本目录 PowerShell 执行（测试均不依赖 PsychoPy 图形窗口）：

```powershell
$py = 'python'  # 使用目标电脑已激活的实验环境
& $py -m unittest tests.test_grip -v
& $py -m unittest tests.test_markers -v
& $py -m unittest tests.test_recording -v
& $py -m unittest discover -s tests -v
& $py run_task.py --simulate --headless
```

最后一项仅快速遍历任务逻辑，不模拟真实实验时间，不应用于时序验证。

实机独立测试（COM7 只是示例，替换为实际打标端口）：

```powershell
& $py test_module.py grip --port COM6 --seconds 20
& $py test_module.py markers --port COM7 --codes '1,2,4,8,16,32,64,128,255,1,1'
& $py test_module.py recording
```

没有硬件时给 grip / markers 测试加 `--simulate`。`test_data` 保存测试输出。打标测试逐一激活每个 bit，再发送全部高位及重复码；应同时核对脑电软件中的码值和逻辑分析仪/示波器读数。串口 ACK 仅证明固件执行，不能证明线缆和脑电系统收到信号。

## 打标协议和八位定义

| 引脚 | D2 | D3 | D4 | D5 | D6 | D7 | D8 | D9 |
|---|---|---|---|---|---|---|---|---|
| 位权 | 1 | 2 | 4 | 8 | 16 | 32 | 64 | 128 |

例如 5 对应 D2、D4 高，其余低；255 是全高。`config.json → markers.codes` 可自定义事件码。默认 run_start=1、trial_start=2、feedback_start=3、success=4、collision=5、trial_end=6、run_end=7、abort=255。success/collision 本身代表 feedback_end，不额外发送一个重复的结束码。

全部 0–255 组合均可编码；**0 是空闲全低电平，不能作为可与空闲区分的独立脉冲事件**。若脑电接口需要 256 个可区分的事件加空闲，就需要额外 strobe 线或脑电接口支持其他编码方式。当前默认事件均为非零码。

电脑发送 ASCII `M,event_id,code,pulse_ms\n`。固件输出八位电平、回 `ACK,event_id,code,micros\n`，保持默认 10 ms 后全低，回 `DONE,event_id,code,micros\n`，并保证至少 2 ms 零间隔。重复同码仍有独立脉冲。`HELLO\n` 用于握手，返回 `READY,1\n`。编号用于关联，送到脑电输入端的只有八位 code。

固件支持标准 Arduino digitalWrite；UNO R3 / 经典 Nano 的 ATmega328P 使用两个端口寄存器写入加快输出。D2–D9 跨两个寄存器，位变化仍有短暂先后差，其他型号逐脚写入更明显；如脑电接口对中间码敏感，需要硬件锁存/strobe。板型未知，固件尚需在你的实际板型上编译上传验证。

第二块 Arduino 的 D2–D9 接脑电打标接口对应位，参考地按设备接口要求连接。确认该接口允许板子输出电压及指定的隔离方式，避免直接接到不兼容输入。UNO R3 为 5V 逻辑；其他板型须按实际规格判断。

## 数据和同步

每次运行创建唯一目录 `data/日期时间_随机编号/`，不覆盖旧 session：

- `metadata.json`：所有配置、被试/session、模拟标识、素材/地图 SHA256、实际数据块时长、UTC 起始时间、运行状态。
- `session.sqlite3`：权威记录，WAL 模式、线程锁；运行中约每 250 ms 提交一次，结束导出 CSV。突然断电可能损失最后一个未提交事务。
- `grip.csv`：每条原始行、温度、电压、scaled raw、电脑接收时间，以及最近任务打标请求 ID/code。
- `events.csv`：完整请求/回执/结束/错误事件，保留每个打标；即使两个 marker 之间没有握力样本也不会丢事件。
- `task.csv`：每个物理步的 trial、phase、位置、速度、归一化/平滑握力、碰撞对象、使用的握力样本 ID 和调度迟到量。
- `trials.csv`：每 trial 结束结果、原因和任务状态。
- `diagnostics.csv`：中止原因、串口及清理错误。

CSV 已将电压、温度、raw、事件码、回执时间、位置和结果等常用数据展开为单独列，`payload_json` 额外保留该记录的完整字段。公共列包括 `t_host_s`、trial、block、phase、last_marker_request_id、last_marker_code。`last_marker_code` 是最近的任务事件码，**不是每个样本时刻实际 TTL 高低电平**，直到下一个请求才改变。

握力、任务和打标使用同一个 perf_counter 相对时间基准。显示相关事件通过 PsychoPy `Window.callOnFlip` 入队，独立打标线程发送串口，防止等待回执卡住绘图。记录区分：请求时间、`t_write_host_s`、ACK 到达电脑的时间、Arduino `device_micros`。队列内脉冲按顺序输出，同一帧内的 trial_end/run_end 等事件会依次发送，不会电气同时发生。

**这些时钟并不天然一致。** 握力时间是电脑收完整行的时间，不是 ADC 采样时刻；Arduino micros 是打标板自己的计时器（约 71.6 分钟回绕），ACK 接收时间也不是 EEG 采样时刻。EEG 与握力可按对应事件码/序列对齐；发送延迟、USB 缓冲、帧刷新偏差需要实测。若需要知道握力 ADC 的精确采样时刻，需要第一块板增加采样序号/硬件时间戳或接入同步线，当前旧格式没有该信息。

Esc 为 aborted；串口失败、无新握力、打标回执异常或严重调度停顿为 error，并尽量发送 abort，结束保存。运行 status=complete 才代表软件正常跑完，不能代替脑电接收链路验收。

中途进程退出后，可从已提交数据库重新导出：

```powershell
& $py test_module.py export --directory 'data\具体session目录'
```

## 参考

- [PsychoPy Window / callOnFlip](https://psychopy.org/api/visual/window.html)
- [PsychoPy ImageStim](https://psychopy.org/api/visual/imagestim.html)
- [pySerial API / timeout](https://pyserial.readthedocs.io/en/stable/pyserial_api.html)
- [Arduino UNO R3 官方规格](https://docs.arduino.cc/hardware/uno-rev3/)

`verification/REPORT.md` 记录本次实际做过的检查及尚未完成的实机验证。


### 日常打标与回读排查

任务配置 `markers.mode` 和独立打标测试默认使用 `output_only`：直接输出给外部设备，不需要回接线，不检测接线，也不发送启动探测码。串口 ACK/DONE 只是固件确认，不能证明外部设备已收到电平。

外部设备收不到标时，按 `arduino/marker_board/PinMap.h` 的输出/输入顺序接好八路回接线，手动运行回读测试：

```powershell
python test_module.py markers --port COM10 --mode loopback
```

测试终端会打印 TX/RX 及逐位回读比对，结果保存在测试会话的 `events.csv`。任务中需要回读时使用 `python run_task.py --marker-mode loopback`；正常任务直接运行 `python run_task.py`。请使用已安装 PsychoPy 的 Python 环境，并关闭其他占用该串口的软件。固件需支持本项目的 M（回读）和 O（仅输出）命令。

### 仅握力计运行（暂不硬件打标）

当前 config.json 的 markers.enabled 为 false：正常读取真实握力、进行校准和实验，不查找或连接打标板。所有事件仍在本地记录，但不生成硬件 ACK/DONE。启动命令不变，不要加 --simulate。

临时关闭硬件打标可加 --no-markers；恢复打标可将 markers.enabled 改为 true，或启动时加 --enable-markers。关闭期间事件 payload 标记 local_only=true，不能视为已向外部设备发送 TTL。

### 2026-09-24 握力采集协议升级

迁移来源：ZHTis/bci2000-grip 提交 26a037f7e1f6e01c7101e775472e177d0f13375b。
固件原样保存于 arduino/sketch_common_analog/sketch_common_analog.ino。
适用于经典 UNO AVR、A0、5 V / 10-bit ADC。请确认实际板型及接线再上传；本次未自动刷写设备。

现在握力串口为 250000 baud，固件平均采样率 256 Hz，输出
`0.00,voltage,sequence,device_micros`；第一项是占位值，不是真实温度。
设备时间记录在 analogRead 之前，电压只有固件传输的三位小数，不是原始 ADC counts。
启动等待 2 秒并清除串口缓存、丢弃第一条可能不完整的行。默认 require_timing=true，旧两列固件会明确报错。
兼容旧固件时需显式设 require_timing=false、baud 为原值，且 grip.sample_rate 和 task.sampling_rate 必须填写真实采样率。

每条采样保存到 SQLite 和 grip.csv；任务按采样顺序逐条消费，sample_block_size=1。
屏幕每帧可处理多个采样，事件仍在下一次显示翻转时发送，故非 256 Hz 显示或逐采样 TTL。
物理积分按秒，平滑参数按原 125 ms 时间尺度换算。数值轨迹可能与旧步长不同，请重新确认任务难度。
最多 10 个缺失序号保存为 valid=false，值和设备/接收时间为空；任务时间继续，缺口不驱动物理更新。
长缺口、重复/倒退序号、设备重置、不匹配的设备周期、超过 250 ms 的任务队列积压或 1 秒无数据会停止任务并保存。
不再用上一条读数无限继续。数据查看时必须排除 valid=false，不能把缺口填为零握力。

每次采集生成 acquisition_id；task.csv 的 grip_sample_id 精确关联 SQLite/grip.csv 记录 ID，
并保存 task_use_host_s、grip_task_used、设备序号。主机时间均为本 session 的 perf_counter 相对秒。
每 0.5 秒请求一次 Q,id，固件返回 S,id,t2,t3，四时间戳保存在 grip_sync.csv。
离线估计设备时钟到主机时钟：

```bash
python -m gripflight.timing /绝对路径/某次session --output /绝对路径/某次session/timing
```

导出 samples.csv、sync_exchanges.csv、task_use.csv、timing_metadata.json。
使用低 RTT 三分之一交换拟合仿射时钟；证据不足则只估偏移，无交换则 unavailable。
保留原始时间、处理 uint32 回绕并标注外推。RTT 和残差不是绝对误差上界；不代表 EEG 已同步。
当前 markers.enabled=false 继续有效：真实握力、本地事件、无硬件打标。
