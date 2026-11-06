# Lumerical Monitor · 手机端

Android 和 iOS 的中文只读监控应用。手机直接 SSH 连接用户自行配置的 Linux 服务器，复用仓库里的 Python 探针，不需要常驻服务或中转账号。

## 使用方式

1. 打开应用，点「连接服务器」。也可先点「查看演示」，查看完全虚构的数据。
2. 填入自己的主机、端口、SSH 用户名和远程项目绝对路径。
3. 从手机文件中导入 SSH 私钥，或主动点「粘贴」导入。加密私钥还需要填写口令。
4. 首次连接会显示主机密钥指纹；通过管理员或可信渠道核对后再信任。已记住的指纹变化会中止连接，可在设置中主动清除信任后重新核验。
5. 在前台查看概览、仿真、GPU/用户资源、许可证、文件和日志。文件下载完成后，可通过系统面板保存或导出。

手机必须能访问该服务器的 SSH 地址。如果服务器位于局域网或 VPN 内，应先连接相应网络。远程需 Python 3.10+；GPU 与许可证查询分别依赖远端可用的 `nvidia-smi` 和 `lmutil`。

应用离开前台时暂停刷新、关闭 SSH 并取消未完成下载；返回前台后恢复用户已请求的连接。此版本不包含锁屏持续监控或后台推送服务。

## 模型与仿真结果

任务详情提供模型预览入口；文件页中的 `.fsp` / `.lms` 可打开模型、电场、T 谱和参数页。它们复用桌面版的 `.preview.json` 缓存：先读取已保存结果；需要时由用户确认后在服务器生成缓存。生成会使用 Lumerical GUI 许可证，只写缓存，不启动求解、不覆盖原工程。运行中的任务只能读取已有缓存。

场图保留实际坐标、波长和截面位置，T 保留负值及大于 1 的值；只有单个波长时显示点。Layer Builder 无法提供材料截面时会明确标注 GDS 局部坐标俯视图。缺少已保存监视器结果时会说明原因，不填充示例数据。

服务器需有 NumPy、Lumerical Python API、相应 GUI 许可证和运行库；工具可复用已有 Lumerical 自带 Python，不会自动安装服务器依赖。独立载入的工程上限为 512 MiB。连接中断时缓存可能已生成，可恢复连接后再次读取。

## 密钥与数据

- 私钥、口令、连接参数和记住的指纹使用手机平台安全存储。iOS 使用本设备、解锁时可访问且不同步 iCloud 的 Keychain 项；Android 使用 Keystore 支持的加密存储，并关闭应用备份/迁移。
- 应用不会把真实参数写入源码或上传给开发者，不包含遥测。
- 导入时只显示密钥已导入的状态；不会自动读取剪贴板。
- 下载文件位于应用私有目录，只在用户主动导出时交给系统分享面板。卸载前如需保留文件，应先导出。
- 使用「清除连接」删除保存的连接和主机信任。源码、测试及构建配置不得加入真实服务器信息或私钥样本。

## 开发和验证

当前工程使用 Flutter 3.47.9 / Dart 3.13.7，并提交依赖锁文件。Android 最低 API 26；iOS 最低版本以 Flutter 工程要求为准。

```sh
flutter pub get --enforce-lockfile
flutter analyze
flutter test
```

项目根目录的 `tools/run_mobile_ssh_test.sh` 会在 Linux 上创建临时 SSH 服务和临时密钥，验证真实连接。它只对临时测试目录执行操作，不使用任何个人服务器信息。

`assets/remote_probe.py` 必须与项目根目录的 `remote_probe.py` 完全相同。修改共享探针后请同步副本并运行桌面 Python 测试。

`assets/preview_export.py` 也必须与根目录的同名文件一致。

## Android

```sh
flutter build apk --release --target-platform android-arm64
```

没有私有签名配置时，此命令只生成未签名的编译验证产物，不能直接安装。CI 的 Android 产物明确标记为 `UNSIGNED`。

需要签名时，在不入库的 `android/key.properties` 中配置 `storeFile`、`storePassword`、`keyAlias`、`keyPassword`。密钥库也必须保存在公开源码之外，并安全备份。release 构建不会再回退到临时调试签名。

**保留现有数据的覆盖升级必须使用现有安装对应的签名私钥，保持 applicationId 不变，并提高 versionCode。** 相同包名或相同证书显示名称无法替代相同签名密钥。找不到原私钥时，不应把新签名 APK 当作兼容更新，也不应要求用户先卸载旧版。

本次 Android 发布使用独立包名 `org.lumericalmonitor.mobile`，桌面名称为「Lumerical Monitor 新版」，可与旧测试包并存。首次需要重新连接服务器；旧 App 的私有数据不会自动共享到新版。后续更新应一直使用本次独立版本的固定签名。版本为 `0.2.0+2`。

## iPhone / iPad

需要 macOS、Xcode 及相应设备支持。在 `ios/Runner.xcworkspace` 中选择自己的开发团队，检查 Bundle ID 和 Keychain Sharing，再执行：

```sh
flutter run
```

模拟器可执行不签名编译检查：

```sh
flutter build ios --simulator --debug --no-codesign
```

不签名的模拟器构建不能直接安装到实体 iPhone。实体机和 TestFlight/App Store 分发需要相应 Apple 签名与分发设置；个人证书、描述文件及账号令牌不应提交到仓库。

本目录沿用项目根目录的 MIT 许可证。
