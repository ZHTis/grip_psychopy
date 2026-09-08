# D4 → A0 同板回读

在第二块打标 Arduino 上，用一根线把 **D4 接到 A0**。A0 保持 INPUT，不启用上拉。只连接一个输出到 A0，不要把 D2–D9 多个输出短接在一起。未接线的 A0 读数没有判定意义。

Python 已经占用打标串口时，不再另外打开 Arduino 串口监视器。新版固件在每个 marker 脉冲期间采一次 A0，回到低电平后再采一次，经同一个串口回传。Python 发送线程也负责接收，因此不存在第二个程序抢占串口的问题。

## 使用

1. 将 `arduino/marker_board/marker_board.ino` 上传到打标板（选择对应板型/串口）。第一块握力板不改。
2. 关闭 Arduino 串口监视器。
3. 在项目目录、已准备好 pyserial 的 Python 环境中运行：

```powershell
python test_module.py markers --port COM10 --loopback-pin 4 --codes '1,4,5,255,2'
```

主任务读取 config.json 的 `markers.loopback_pin=4`、`a0_threshold=512`。默认按 UNO 10-bit ADC，用 512 作为高低判定阈值。高电平通常接近 1023、低电平接近 0；这是辅助逻辑判定，不是精确电压或边沿时序测量。[Arduino analogRead 官方说明](https://github.com/arduino/reference-en/blob/master/Language/Functions/Analog%20IO/analogRead.adoc)

## 如何判断

D4 位权为 4，即 `code & 4` 非零时预期为高；其他码预期为低。例：4、5、255 在脉冲期间 D4 应高，1、2、3 应低。脉冲结束后全部应低。

新的回执为：

```text
ACK,event_id,code,output_onset_micros,a0_during_adc
DONE,event_id,code,output_offset_micros,a0_after_adc
```

为了不让串口打印干扰脉冲长度，两条回执都在采样完成、输出恢复全低后发送。ACK 中时间戳仍是输出码设置完成时刻，A0 是随后进行的一次 ADC 采样，并非该时刻的精确采样时间。电脑收到 ACK 的延迟包含脉冲持续时间；不要将其解读为 EEG 延迟。

独立测试终端显示 TX 命令、RX 原始回执以及 `A0 check=True/False/None`。False 表示与当前 D4 预期不一致；None 表示旧固件没回 A0、模拟运行或未配置检测引脚，不等于通过。

`events.csv` 的 ACK/DONE 新增：`a0_adc`、`loopback_pin`、`a0_expected_high`、`a0_measured_high`、`a0_matches_expected`。笔记本打标核对表新增 `a0_during_adc`、`a0_after_adc`、`a0_during_ok`、`a0_after_ok`。旧记录缺失这些字段时显示空值。

Python 兼容旧版四字段回执，但旧固件不会产生 A0 测量。回读不匹配不会自动停止任务。本功能只辅助核对 D4 上的一次高/低状态，不能证明整段脉冲宽度、其他七位或 EEG 接收链路正常。
