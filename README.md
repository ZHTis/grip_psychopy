> 更新（2026-09-08）：主任务现采用持续运行策略，仅完成全部 trial 或按 Esc 主动结束。握力无数据/过期时保持最后有效值，无历史值则用 grip_min；数据恢复后自动使用新值。打标端口或回执失败后，本次运行停用硬件打标但继续保存本地事件，不会补发旧事件或自动重新连接。延迟超过阈值时重新安排后续时间步并继续；运行中保存错误仅警告，可能造成记录缺失。metadata 记录 runtime_warnings / dropped_records，task 的 payload_json 标记 grip_input_status / grip_age_s。正常完成不代表硬件采集和打标成功。配置损坏、缺少依赖、画面无法创建等启动失败仍需修复。独立 test_module.py 测试仍严格报告硬件错误。下文早期的“超时中止”说明以本更新为准。
# GripFlight → PsychoPy

复用 BCI2000 GripFlight 的原始背景、小鸟 SVG 和两份 CSV 地图；握力读取、打标、数据保存各自独立。任务电脑运行 PsychoPy，脑电继续由脑电电脑自己的软件记录。

## 快速开始

先在目标电脑选择安装了 PsychoPy 的 Python 环境。启动脚本不再依赖固定安装路径，解释器选择及迁移步骤见 [PORTABILITY.md](PORTABILITY.md)。

1. 双击 `launch_simulation.bat`，无需 Arduino，按住鼠标左键增加握力，松开降低握力，Esc 中止。模拟数据明确标记为 simulated。
2. 修改 `config.json` 中 participant、session、grip.port 和 markers.port。两个串口必须不同。握力端口沿用 COM6 / 115200；打标端口当前为 COM10，迁移后请填写目标电脑的实际端口。
3. 将 `arduino/marker_board/marker_board.ino` 上传到**第二块打标 Arduino**。第一块握力 Arduino 的固件不需修改，串口格式仍为 `temperature,voltage\n`。
4. 先运行下面的两个串口独立测试，核对脑电软件收到的码及接线，再双击 `launch_hardware.bat`。

依赖：PsychoPy、pyserial、Pillow、PyQt6。请确认目标电脑的实验环境带有这些组件。若使用其他环境，在该环境安装 `requirements.txt`，并单独安装兼容的 PsychoPy。无需修改启动脚本路径，按 PORTABILITY.md 选择解释器即可。

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
