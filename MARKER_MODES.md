# 可选择的打标模式

先上传更新后的 `arduino/marker_board/marker_board.ino`（同一文件夹内保留 PinMap.h）。之后两种模式只需修改配置或命令行，不用反复换固件。

在 config.json 的 markers 中设置：

```json
"mode": "loopback"
```

`loopback`：按 outputPins 输出、读取 feedbackPins 八路输入；保存回读码和一致性。需要八根回接线。保持原有默认行为。

```json
"mode": "output_only"
```

`output_only`：只输出事件码，维持 pulse_ms 后全部恢复低电平。固件不读取反馈针脚，无需回接线。反馈脚配置仍留在 PinMap.h 中供切回 loopback 时使用，不能与输出脚重复。

主任务也可以临时选择（优先于 config.json，仅本次运行）：

```powershell
python run_task.py --marker-mode loopback
python run_task.py --marker-mode output_only
```

独立测试：

```powershell
python test_module.py markers --port COM10 --mode loopback
python test_module.py markers --port COM10 --mode output_only
```

`verbose` 独立控制打印，两种模式都可以开关。输出模式依然返回 ACK/DONE 软件执行确认，但不是引脚电平回读；终端标为 `output_only: firmware confirmation; no pin readback`。如果你希望连串口确认也不接收，那是另一个需求，当前设计保留确认来发现发送和执行失败。

命令协议：M 为自发自收，O 为仅输出。输出模式的 ACK/DONE 末尾为 `OUT,-`，不会伪造测量值。events.csv/笔记本记录 mode、feedback_mode；output_only 的 feedback_mode=disabled，readback_code 和检测结果为空（不是通过，也不是失败）。没有回接线不会因电平回读触发错误。

旧固件不支持 O 命令，需要先更新固件；不能只修改Python而继续使用旧固件。针脚顺序仍在 PinMap.h 自定义，事件码仍在 config.json 的 markers.codes 中定义。任务的异常继续运行策略保持不变。
