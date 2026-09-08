# 握力与打标数据查看

打开 `grip_markers.ipynb`，选择 Python 内核，按顺序运行。参数集中在“选择数据”单元格：session 名称、trial、起止时间。默认选择最近一次非模拟且已导出 CSV 的 session。

使用目标电脑上安装了 pandas、numpy、matplotlib、ipykernel 的 Python 内核。可在 VS Code 中选择该内核；需要网页界面时，在选用的分析环境安装 notebook，然后运行 `python -m notebook grip_markers.ipynb`。实验运行和数据查看可以选择不同的环境，均不需要在代码中写死解释器路径。见上级目录 PORTABILITY.md。

脚本也可以直接画图（在本文件夹执行）：

```powershell
python view_data.py
python view_data.py --session 20260908_163647_ddebedaf --trial 1
python view_data.py --start 5 --end 20 --save exports\overview.png
```

文件说明：

- `grip_markers.ipynb`：主笔记本；为便于换电脑，交付时清空输出，在目标电脑重新运行即可。
- `view_data.py`：数据读取、按事件编号关联回执、质量摘要和绘图。
- `test_view_data.py`：重复码关联、计时回绕、旧版 CSV 和无数据情况测试。
- `build_notebook.py`：重新生成空白笔记本模板；会覆盖当前笔记本，日常查看不需要运行。
- `preview.png`：交付时所选 session 的静态预览。

只读原项目的 CSV，不读取串口、不修改原始数据。电压单位为 V，尚未转换成实际力。超时期间任务可能保持旧值，任务输入图与原始采样图分开显示。打标请求、硬件/模拟 ACK、DONE 和失败分别展示。所有横轴是电脑时钟；Arduino micros 不直接叠加到该横轴。

图形设计：两张共享时间轴的图：上图在原始电压上叠加 event marker 竖条和名称/码值，下图显示任务输入；ACK/DONE 详细时间保留在核对表；蓝色表示采样/正常事件，橙色和叉号表示异常，灰色辅助标记。数据过少时仍显示样本点，空数据明确标为空；不插值填补丢失数据。
