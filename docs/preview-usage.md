# 模型与结果预览

选择任务后，详情区显示模型截面缩略图；点缩略图或「模型与结果」进入大图页面。在文件页单击 `.fsp` / `.lms` 会进入该工程的模型与结果页。

大图页包括模型截面、模场/电场、透射谱 T 和参数说明。场图标注实际选取的波长、坐标轴和单位；参数页列出原监视器名称、缓存时间和缺失数据原因。模型当前是 XY 截面，z 可配置，不是完整交互式三维 CAD。

## 读取与生成

普通选择操作通过现有 SSH 会话读取工程旁的 `<文件名>.preview.json`。没有缓存时显示缺失原因。对已保存、未运行的工程，可以点「生成 / 更新预览」；确认后服务器会新开一个隐藏 Lumerical 会话，读取结果并写入侧车缓存。此操作会使用相应 Lumerical 许可证。

生成器不调用 `run`、`runsweep`、`switchtolayout` 或 `save`，不覆盖原工程。缓存内容不匹配原文件大小/修改时间时，界面标明旧缓存。运行中的任务只显示已有缓存。

服务器需有能导入 NumPy 和 `lumapi` 的 Python。系统 Python 缺少 NumPy 时，生成工具会尝试使用已安装的 Lumerical 自带 Python。常用安装目录会被发现；非标准路径可通过服务器 `LUMERICAL_API_DIR` 指向含 `lumapi.py` 的目录，或用 `LUMERICAL_PYTHON` 指定解释器。监控程序不会自动安装依赖或修改服务器环境。

生成器使用 Lumerical `polystencil` 导出材料在指定 z 平面的真实轮廓，读取已保存 E/T 数据集。某版本不支持对应接口或工程未保存监视器结果时，会显示说明，不生成替代结果。总 T 保留方向符号，不会被强制限制在 0–1。

如果 Layer Builder 的工艺结构无法枚举，会显示首个 Layer Builder 已保存的 GDS 图形，并明确标注局部坐标及其局限：这类图不包含工艺厚度、偏置和旋转，不代表所填 z 的材料截面。

## 大型工程与仿真脚本集成

独立自动加载限制为 512 MiB，避免为预览重复加载巨型结果。场数组传入 Python 前也有大小检查。大型仿真可在原有 Lumerical Python 会话中，完成并保存结果后调用：

```python
from preview_export import export_from_session

# session 是现有的 lumapi.FDTD / lumapi.MODE 对象。
# root 和 project 由使用者自己的脚本提供，不在公共源码中预置。
export_from_session(session, root, project, wavelength_m=1.55e-6, z_m=0)
```

此函数复用已有会话，不会自行启动求解或保存工程。没有配置/保存场监视器的数据无法事后凭空恢复。

也可以在有 Lumerical API 的机器上手动执行：

```text
python preview_export.py project.fsp --root /srv/simulations --wavelength-nm 1550 --z-um 0
```

## 本地源码运行

基础监控继续使用 Python 标准库。绘图页面需要：

```text
python -m pip install -r requirements-preview.txt
```

Windows 打包版包含上述绘图依赖。真实连接配置、密钥、预览缓存及实验数据均不属于公开源码；`.preview.json` 已被 Git 忽略。
