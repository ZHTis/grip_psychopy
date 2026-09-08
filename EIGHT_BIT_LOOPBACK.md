> 针脚顺序现由 arduino/marker_board/PinMap.h 自定义，已保留你修改的 A5,A4,A3,A2,A1,A0,12,13 回读顺序。以下默认接线表仅为旧示例，实际以 PinMap.h 为准。见 [PIN_ORDER.md](PIN_ORDER.md)。

# 八路自发自收（UNO）

八根线各连一个独立输入。当前固件默认以下顺序；替换先前 D4→A0 的单路接线：

| 输出 | 回读输入 | 位权 |
|---|---|---|
| D2 | A0 | 1 |
| D3 | A1 | 2 |
| D4 | A2 | 4 |
| D5 | A3 | 8 |
| D6 | A4 | 16 |
| D7 | A5 | 32 |
| D8 | D10 | 64 |
| D9 | D11 | 128 |

A0–A5 在这里作为数字输入，不采集模拟电压；D10/D11 同样为输入。不要把多路输出短接在一起。接线必须与固件 `feedbackPins[8]` 按 D2 到 D9 的顺序一致。UNO 资料见 [官方引脚图](https://content.arduino.cc/assets/Pinout-UNOrev3_latest.pdf)。

上传更新后的 `arduino/marker_board/marker_board.ino` 到打标板，然后关闭串口监视器。在已配置好的 Python 环境中执行：

```powershell
python test_module.py markers --port COM10 --codes '1,2,4,8,16,32,64,128,255,0,1,1'
```

无需再传 `--loopback-pin`；此参数仅用于兼容旧的单路 A0 固件。config 的 loopback_pin=null，a0_threshold 也只对旧单路模拟回读有效。新版通过回执中的 B8 字段自动识别。

每次脉冲采两次八位输入：一次在输出码稳定后，另一次在恢复全低后。固件将八路电平编码为 0–255：

```text
ACK,event_id,sent_code,onset_micros,B8,readback_code
DONE,event_id,sent_code,offset_micros,B8,readback_code
```

ACK 的 readback_code 应等于 sent_code，DONE 的 readback_code 应为 0。终端显示 D9..D2 的八位二进制、预期值及 mismatch_pins（不匹配的输出引脚，例如 [4,9]）。两条回执仍在脉冲结束后通过 Python 已打开的同一个串口传输。0 仅测试全低状态，不构成可区别于空闲的 EEG 事件。

events.csv 增加 readback_code、expected_readback_code、readback_bits、mismatch_mask、readback_matches_expected 和 mismatched_output_pins；这些字段也保存在完整 payload_json。笔记本核对表分别显示脉冲期间/结束后的回读码、一致性和错误脚位。检测失败只标记，不自动停止任务，也不伪造为握手/传输失败。

这验证的是八个输入在两次读取时的逻辑状态，不是连续波形或严格同时采样；无法检测任意时刻毛刺，也不能代替 EEG 接收确认。八位由 digitalRead 依次读取，脉冲保持期间输出不变。未接线的输入可能浮动，回读结果没有保证。

旧记录及旧四字段/单A0固件仍能读取，但不产生八路检测结果，应显示未知而非通过。接线改变后必须同步修改 feedbackPins 并重新编译上传；更改事件码仍只需 config.json。
