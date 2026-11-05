# Lumerical Monitor

通过 SSH 查看远程 Linux 服务器上的 Ansys Lumerical 仿真状态的 Windows 桌面应用。使用 Python、Tkinter 和系统 OpenSSH，界面为中文。

Android / iOS 手机端位于 [`mobile/`](mobile/README.md)：手机直接 SSH 连接、平台安全存储、前台刷新，复用同一个只读服务器探针。具体构建和 iPhone 签名要求见手机端说明。

支持 FDTD、varFDTD、EME、FDE、CHARGE、HEAT 等求解器的进程识别与日志解析。运行时无需安装第三方 Python 包；远程探针通过 SSH 发送给 Python 执行，无需部署常驻服务。

## 功能

- 服务器概览：CPU、内存、磁盘、GPU 及历史曲线。
- 仿真任务：运行状态、进度、剩余时间、Auto Shutoff、求解器日志与资源占用。
- GPU 和用户资源占用：在服务器权限允许的范围内查看共享资源。
- 项目文件：浏览限定目录、读取日志尾部、跟踪日志、下载文件。
- FlexLM 许可证：通过远端 `lmutil lmstat` 查询状态和占用，支持关闭查询。
- 自动刷新、浅色/深色主题、Windows 桌面通知。

应用面向只读监控，不提供远程命令控制台或任务终止按钮。日志读取和文件下载限制在配置的项目目录内；路径检查会拒绝目录穿越和越界符号链接。查询会产生短暂远程进程，下载及设置保存会写入本地文件。

## 环境要求

- 客户端：Windows 10/11、Python 3.10+（包含 Tkinter）和 Windows OpenSSH Client。
- 服务器：Linux、Python 3.10+、可用的 SSH 密钥登录权限。
- GPU 信息可选依赖远端 `nvidia-smi`；许可证信息可选依赖远端 `lmutil`。

源码中的 SSH 传输也兼容类 Unix 命令名，但桌面界面和通知以 Windows 为主要目标平台。

## 开始使用

下载源码后，在源码目录执行：

```powershell
Copy-Item profile.example.json profile.json
python app.py
```

打开设置，填入自己的服务器地址、SSH 用户名、端口、私钥文件绝对路径及远程项目绝对路径，然后保存。也可以先编辑本地 `profile.json`。

仓库只提供虚构示例：主机为保留的 `.invalid` 域名，用户名为示例账号，密钥路径为占位路径。示例中的端口为通用协议示例值；没有预置可用连接或任何密钥内容。

首次连接前，应使用系统 OpenSSH 建立并核验该主机的信任关系。应用启用 `StrictHostKeyChecking=yes`，不会自动接受未知主机指纹。私钥需要口令时，请先通过系统 SSH agent 解锁。

`profile.json` 中的 `key` 是本地私钥文件的路径，不是公钥或私钥文本。不要把密钥内容粘贴到配置中。

## 配置与隐私

实际连接参数只保存在本地 `profile.json`，该文件已被 Git 忽略。配置文件应位于源码目录，或打包程序的可执行文件旁。

运行时的 `monitor.log`、`last-*.json`、下载文件和截图可能包含服务器用户名、主机名、项目路径或仿真结果。分享问题报告前请先脱敏；这些运行记录不属于源码发布内容。应用不包含遥测或外部 AI 服务调用。

许可证查询使用远程进程的 `ANSYSLMD_LICENSE_FILE` / `LM_LICENSE_FILE` 环境变量，未设置时采用本地许可证服务的通用默认值。程序不读取或分发许可证文件。SSH 账号看到的信息仍受服务器本身的权限控制。

## 测试

```powershell
python -m unittest discover -v
```

测试使用临时目录、合成日志和本地子进程，不需要连接真实服务器。覆盖路径边界、日志解析、持久连接、下载完整性、取消清理、许可证解析及公开分发配置。Windows 环境不支持创建符号链接时，相关测试会跳过该部分检查。

`python app.py --check` 会连接你配置的真实服务器，并把包含运行信息的快照写入本地；请不要把快照提交到仓库。`--ui-smoke` 用于读取本地快照验证界面，需先在本地生成快照。

## 打包 Windows 应用

在 Windows 的 PowerShell 中运行：

```powershell
python -m pip install -r requirements-build.txt
.\build_app.ps1
```

也可以指定 Python 命令及输出目录：

```powershell
.\build_app.ps1 -Python python -OutputDirectory dist
```

生成位置为 `dist/LumericalMonitor/LumericalMonitor.exe`。保留整个输出文件夹和 `_internal`。构建脚本只复制示例配置和许可证；实际连接信息需要使用者自行设置。分享已经使用过的打包目录时，应先移除本地配置和运行记录。

## 源码结构

| 文件 | 用途 |
| --- | --- |
| `app.py` | Tkinter 桌面界面 |
| `ui_kit.py` | 主题和界面组件 |
| `client.py` | SSH 传输、配置及下载 |
| `remote_probe.py` | Linux 只读探针与日志解析 |
| `test_monitor.py` | 功能和安全边界测试 |
| `test_distribution.py` | 公开分发配置检查 |
| `profile.example.json` | 虚构连接配置 |
| `make_icon.py` | 生成应用图标 |
| `build_app.ps1` | Windows 打包脚本 |

## 许可证

本项目使用 [MIT License](LICENSE)。Ansys、Lumerical 和其他产品名称属于各自权利人；本项目为独立工具，不包含或分发商业求解器、许可证文件或密钥。
