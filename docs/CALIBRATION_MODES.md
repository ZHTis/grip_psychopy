# 最大握力标定与任务记录

正式模式默认先采集零点和三次最大力度握紧，完成后按空格进入游戏。即使旧配置 `calibration.enabled=false`，正式入口也会要求标定。沿用当前时长：UNO 零点 5 秒、握紧 5 秒、两次休息各 15 秒；RX 零点 5 秒、握紧 1 秒、两次休息各 6 秒。此前讨论的 1500 ms / 60 s / 黑屏流程尚未接入。

## 启动

```bash
# 25 通道：正式任务，重新标定
bash "/Users/heting/Documents/grip_psychopy/launch_multichannel.command"

# 25 通道：实际设备调试，跳过标定
bash "/Users/heting/Documents/grip_psychopy/launch_multichannel.command" --debug

# 无硬件模拟；也属于调试数据
bash "/Users/heting/Documents/grip_psychopy/launch_multichannel.command" --simulate

# 明确复用先前的标定（用实际路径替换示例）
bash "/Users/heting/Documents/grip_psychopy/launch_multichannel.command" \
  --calibration-file "/实际数据目录/calibration_profile.json"
```

UNO 使用 `launch_hardware.command`，参数相同。正式模式不自动选择“最近一次”标定，避免误用其他参与者的参考。复用会检查参与者、设备类型、已配置序列号；UNO 还检查 gain，RX 检查协议手别和显示手别。RX 未配置序列号时不能仅凭文件识别同型号硬件是否更换；更换传感器、握持物或接触方式后应重新标定。`--debug` / `--simulate` 不与 `--calibration-file` 混用。

## 保存位置

每次正式任务在自己的数据目录保存 `calibration_profile.json`，其中含标定 ID、身份设置、原始标定记录及参考值；`experiment_setup.json` 同时保存参考快照与来源。RX 默认目录 `data/weighted/<session>/`，UNO 为 `data/<session>/`。保存失败或未成功标定时不进入正式任务。复用不重写旧标定文件，会复制到新任务目录。

## 数据字段

`task.csv` / SQLite 任务记录同时包含：

- `calibration_id`、`calibration_valid`、`debug_mode`：标定来源及有效性。
- `absolute_value` / `absolute_unit`：UNO 为 `abs(voltage * gain)`，未换算为 N/kg；RX 为各点设备上报 g 值的加权平均（未扣零点），并非测力计认证的全手总握力。
- `relative_calibrated`、`percent_calibrated`：相对实测标定范围的比例与百分比，不限制为 100%。
- `input_normalized`：供游戏使用的 0–1 输入，与未截断的测量比例分开记录。
- RX 另外导出 `point_01_g` … `point_25_g` 和 `point_01_relative` … `point_25_relative`。单点比例为 `(读数−零点)/参考范围`；无参考范围的通道留空。
- RX 原始每帧记录仍保存在 `grip_multichannel.csv`；UNO 原始电压及设备时间等仍在 `grip.csv`。`task.csv` 按控制步记录，可经 `grip_sample_id` 关联采集帧；RX 重复使用帧有 `input_reused` 标识。

UNO 相对值为 `(abs(raw)−零点)/(三次最大峰值−零点)`，低于零点可为负。RX 总体比例为 `Σ w·max(0,读数−零点) / Σ w·各点标定范围`，分母不包含调试面板的 `reference_scale`。每点参考范围沿用“三次中该点最大峰值−该点零点”，不同点峰值不一定同时发生，因此总体比例不是同步全手总力 MVC。

RX 权重可在游戏时修改，比例采用该控制步的权重，`weight_revision` 与 `weight_updates.csv` 记录修改依据。游戏的 `reference_scale` 可调整难度，但不改变保存的实测标定比例。

Debug 无实测参考时，相对标定字段为空，`calibration_valid=false`；游戏仍使用临时参考运行。不能把 Debug 的归一化游戏输入解释为实测最大握力百分比。


## UNO 的刺激屏与实时曲线窗口

默认启动 `launch_hardware.command` 即启用：

- 扩展桌面检测到两个以上屏幕：刺激（标定与游戏）在非主屏全屏显示，主屏显示独立曲线窗口。多个副屏优先使用配置中的 `display.screen`（必须不是主屏）。主屏按操作系统的默认主显示器识别。
- 单屏或镜像桌面仅呈现一个逻辑屏幕：两个窗口左右并排，刺激不会全屏遮住曲线。尺寸依据逻辑分辨率布局，兼容 Retina 缩放。
- `--windowed` 在双屏下仍保留外接屏位置，但刺激改成窗口。`--no-grip-monitor` 可关闭此监视功能并恢复原配置的显示方式。
- 标定阶段先显示绝对读数；三次测量完成后显示百分比，复用有效标定时直接显示百分比。Debug 无标定时不显示伪造的 MVC 曲线。
- 绿色直接显示串口第二列 A0 电压（V），不乘游戏 gain；同时显示电压数字和 `ADC≈round(V×1023/5)`（按当前固件 5 V／10 位假定换算，并非新增原始 ADC 字段）。橙色为 `(绝对读数−零点)/(最大值−零点) × 100%`，不截断负值或超过 100% 的值。
- 最近 12 秒滚动曲线，监视发送上限 10 Hz；这不是采样率。采集仍按原配置运行，独立有界缓存不消费任务／标定队列，显示背压时跳过显示更新。
- 曲线由独立 Qt 进程绘制，不与刺激窗口共用绘图事件循环。关闭曲线窗口不会退出实验；整个任务结束时自动清理曲线进程。

可用 `--simulate` 测试无设备的双窗口，鼠标／按键需在刺激窗口操作。需测量有效标定后再核验真实百分比曲线。开发预览：

```bash
bash run_python.sh tools/preview_uno_monitor.py /private/tmp/uno_curve_preview.png
```

该 PNG 是合成数据的 UI 检查图，不是实验结果。双屏模式须在扩展桌面下验证，不能通过镜像模式让两屏显示不同内容。


## Esc 中止（UNO 双窗口）

刺激窗口或握力曲线窗口获得键盘焦点时，按 Esc 可中止整个任务，覆盖等待数据、标定、校准完成等待空格及游戏阶段。曲线窗口通过独立的进程事件传递中止请求；不会只关曲线而让游戏继续。退出沿用记录保存和串口／窗口清理流程，运行中的会话记为 `aborted`。标定未完成时不会生成有效标定文件。关闭曲线窗口的关闭按钮仍只关闭监视窗口。

Esc 是这两个应用窗口的快捷键，不是操作系统全局热键；若焦点在终端或其他软件，请先点回任一任务窗口。最终写盘和资源清理可能需要短暂等待。


## UNO 标定圆球反馈

UNO 的标定刺激使用原生 PsychoPy Circle 绘制，替代时间进度条。准备／零点采集显示灰色圆球及灰色提示文字，休息显示灰色小圆球和较小的灰色提示文字；握紧阶段显示红色圆球，用最新有效传感器读数控制圆球半径，不显示百分比或“已满”。完成页展示三次峰值圆球和读数，按空格进入游戏，Esc 可退出。

三次握紧共用零点测量后固定的显示尺度。仅用于视觉反馈：`delta=max(0,abs(raw)-baseline)`，`scale=max(0.05*abs(gain),0.1*max(0,5*abs(gain)-baseline))`，视觉量 `delta/(delta+scale)`；不是 MVC 百分比，不修改原始采集和参考值算法。若 A0 没有随用力变化，圆球不会虚构膨胀反馈。RX 标定界面沿用原实现。

复现界面检查（模拟读数，不连接硬件）：`bash run_python.sh tools/preview_uno_calibration.py /private/tmp/uno_orb_preview`。截图为实际 PsychoPy 渲染，不能当作真实实验记录。


### UNO 有效尝试与平滑动画（2026-11-02）

- 默认零点 5 秒 → 红球握紧 5 秒 → 灰球休息 15 秒 → 握紧 5 秒 → 休息 15 秒 → 握紧 5 秒。三次有效后显示峰值并等待空格进入游戏。
- 红球随实际读数平滑增长，增长响应时间常数 0.12 秒；松开或进入休息时连续缩小，归零目标下最多 0.8 秒回到原始半径。动画采用经过的时间，不依赖固定刷新率；显示卡顿时下一帧更新。动画只影响显示，不平滑保存的采集值或峰值。
- `calibration.squeeze_data_timeout_s=0.5`：握紧期间根据新采集帧的主机时间检测缺数，超过阈值在下一次界面轮询停止本次尝试；重复读取旧的 latest 值不能延长该窗口。握紧结束也检查样本覆盖和间隙。零点仍使用 `max_gap_s=0.3`。
- 无效尝试不计数。恢复到本次结束之后的新帧后，先休息 15 秒，再重做同一编号。峰值未超过零点及噪声门槛也重做，不将无用力的完整数据当作最大握力。只有三个有效记录才生成参考值。设备仍需正确握持；算法不能证明参与者已经达到生理最大用力。
- `experiment_setup.json` 的 `calibration.attempts` 保留所有握紧尝试，含编号、起止时间、原始样本、valid/invalid/interrupted 状态及无效原因；`segments` 在完成时仅含零点及三次有效握紧，运行／中止时也保留当前未完成段。事件记录增加 attempt、status 和 reason。
- 临时无新帧时可以等待恢复并重试；USB 断连、设备重置／序号异常等造成采集线程失败时，仍中止会话，需要检查设备并重新启动，不会绕过串口完整性检查。等待、休息和重试期间均可 Esc 退出。


## macOS 原生闪退修复（2026-11-02）

本机两份崩溃报告 `python-2026-11-02-145925.ips` 与 `python-2026-11-02-151536.ips` 都记录 `EXC_BAD_ACCESS / SIGSEGV`，出错于非主线程的 `libGL.dylib glDeleteTextures`；后者 PID 77308，与用户运行日志一致。会话没有正常收尾，因此 metadata 仍为 recording，已提交的 SQLite 数据仍可只读分析。

检查当前 PsychoPy 包内 pyglet 1.5.27 的 `gl/base.py`：`current_context` 是进程全局变量，纹理回收只检查对象空间，没有检查当前线程是否持有原生 OpenGL context。项目 `gripflight/gl_safety.py` 为 pyglet 1.x 加入运行期保护，后台或无当前 context 时使用其原有延迟释放队列，实际释放在主线程激活窗口 context 后进行。PsychoPy 的 TextStim/ImageStim 析构会绕过该队列，因此另外把这两类对象的后台析构延迟至主线程；窗口销毁后不再调用其 GL 清理函数。没有修改 PsychoPy 安装文件；其他 pyglet 大版本不套用这一兼容补丁。

`Display` 和 UNO 圆球避免重复设置不变的文字换行宽度、字号，减少旧文字布局和纹理对象回收。启动脚本增加 Python faulthandler，若以后再次发生原生异常可在终端输出线程堆栈。`resource_tracker` 的 semaphore 警告不等同于这次原生崩溃的原因；不通过隐藏警告代替资源清理。

开发验证：`bash run_python.sh tools/stress_uno_display.py`。该脚本无需硬件，打开真实 PsychoPy 刺激窗口和 Qt 曲线窗口，使用模拟输入完成三次标定后进入游戏，后台主动回收纹理与触发 GC，约 95 秒后自动走 Esc 退出。加 `--hidden` 可隐藏测试窗口；仅在该测试模式中关闭垂直同步及 macOS display-link 等待，并跳过原生键盘事件轮询，使用定时模拟 Esc。因此它验证原生 GL 资源生命周期、IPC 和保存清理，不代表外接屏显示时序或实际按键实测（正式任务设置不变）。结果位于 `data_viewer/exports/gl_stress`，不写入真实数据目录、不生成可复用的实测标定文件。

验证结果：122 项自动测试通过；隐藏原生窗口压力测试运行 95.80 秒，完成三次模拟标定并进入游戏，200 次后台纹理回收探针全部通过，保存 24,293 个模拟握力帧及 11,223 个任务步，定时模拟 Esc 后正常保存为 aborted。终端没有原生崩溃或 resource_tracker 警告；真实设备及可见双屏仍需重新运行确认。

休息提示无呼吸／闪烁动画；从握紧切换时仍保留不超过 0.8 秒的平滑缩回，随后固定小圆点。握紧时持续显示“最大力度握紧”，字号随圆点的实时用力量小幅变大／变小；字号按 0.0005 height 单位分档，只有变化时更新文字布局。


## UNO 曲线与打标日志合并窗口

默认 UNO 监视窗口现为“握力曲线与打标日志”：上方保留 A0 电压和相对最大握力两条曲线，下方可滚动查看最近 300 条打标、标定事件及诊断记录，包括相对会话起点的时间、事件名称、标记码和状态。悬停可看原始事件名、关联事件 ID 和完整状态。

- `marker_request` 在两条曲线上画虚线及标记码，位置为与磁盘事件记录一致的主机时间，不是 TTL 实测时间。ACK／DONE 在日志中独立列出；output_only 只能标为固件确认，无引脚回读。
- 打标关闭时标注“仅本地（硬件关闭）”；模拟打标明确标注不发硬件。发送错误、回读不匹配及未保存到磁盘会分别显示，不能视为已打标。
- 标定开始／结束／无效重试等原有本地事件也显示，不额外发送硬件标记码。
- 日志来自 `ContinuingRecorder` 的线程安全有界副本；监视进程不查询 SQLite、不消费采集队列。仍以最多 10 Hz 非阻塞发送完整快照，显示拥塞后下一帧补上最近事件；完整记录继续由 session.sqlite3 / events.csv 保存，不受 300 条显示上限影响。
- 查看旧行时保留滚动位置，在表尾时自动跟随新日志。鼠标点进表格后 Esc 仍中止整个任务。窗口关闭规则与以前一致。

预览：`bash run_python.sh tools/preview_uno_monitor.py /private/tmp/uno_curve_log.png`，使用明确标注的模拟曲线与本地事件。真机 ACK／DONE 和实际 TTL 输出仍需连接打标板检验。

三次峰值结果页去掉底部单位说明，保留三次读数和“按空格开始实验 · Esc 退出”。准备阶段先等待新串口数据，再采集配置指定的 5 秒空载读数；中位数作为软件零点、标准差用于后续有效握紧判定。
