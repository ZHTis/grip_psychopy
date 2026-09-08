# 自定义输出和回读顺序

只编辑 `arduino/marker_board/PinMap.h` 中的两行，然后重新编译上传打标板：

```cpp
constexpr uint8_t outputPins[]   = {2, 3, 4, 5, 6, 7, 8, 9};
constexpr uint8_t feedbackPins[] = {A5, A4, A3, A2, A1, A0, 12, 13};
```

已保留你手动修改的回读顺序。每列为一对独立连线：outputPins[i] → feedbackPins[i]。数组第 1 项是 bit0/码值1，第 8 项是 bit7/码值128；列表顺序可以独立修改。

例如把输出改成 `{9,8,7,6,5,4,3,2}`，码值1会从 D9 输出，仍由第一项 A5 回读；码值128从 D2输出，由最后一项 D13回读。不要依据“D2永远是bit0”的旧说明接线，以当前 PinMap.h 为准。

两组各需8项，不得重复、不得输入输出复用同一针脚。D0/D1保留给串口；针脚必须可作数字GPIO。固件检查失败会回 ERR,PIN_CONFIG，并且不启用输出。标准D2–D9顺序保留快速端口写入；自定义顺序使用逐脚 digitalWrite，因此输出位会有先后变化，不能视为电气同时输出。

固件握手主动回传两组针脚编号，Python 自动使用并保存，不需在Python中再写一套顺序。A0–A5 在UNO的回传数字编号为14–19，所以A5显示为19。终端的二进制显示统一标注bit7..bit0；错误列表按实际针脚编号显示。

### 串口占用

任务运行时由Python独占打标串口，并在同一个连接中接收回读。VS Code / Arduino IDE的Serial Monitor此时无法再次打开该端口，这是预期行为。保持监视器关闭，在任务结束后的events.csv或笔记本查看结果；需要实时逐条显示TX/RX时，用独立测试：

```powershell
python test_module.py markers --port COM10
```

若主任务确实在启动时报告端口被占用，请先结束独立测试或关闭监视器，再重新启动主任务。当前主任务在打标初始化失败后不会自动重连；关闭其他程序后需要重新运行任务。
