# Windows 一键编译 ClashMeta-T

在 64 位 Windows 上双击仓库根目录的 [Build-ClashMeta-T.cmd](../Build-ClashMeta-T.cmd)。需要 Python 3.11 或更新版本、Git 和 Windows 自带的 curl。构建工具和依赖会缓存到仓库上一级的 `.clashmeta-build`，首次下载需要联网和数 GB 磁盘空间。

脚本读取 Clash Meta for Android 的最新稳定版，并使用该版本随源码固定的 Android Mihomo 提交。Tailscale 库版本由 Mihomo 的 `go.mod` 决定。脚本会打印三者的实际版本，应用应用层和 Mihomo 的两份补丁，运行入站配置与转发测试，然后编译 ARM64 APK。

成功后，安装包位于仓库下的 `dist`，文件名包含应用版本和 Mihomo 提交短号。脚本会校验包名、桌面名称、应用内全名、ARM64 库、入站代码和 APK 签名，并打印 SHA-256。

## 常用命令

在仓库目录打开命令提示符。

```bat
Build-ClashMeta-T.cmd --check
Build-ClashMeta-T.cmd --tag v2.11.37
Build-ClashMeta-T.cmd --local
```

第一条只检查官方标签、依赖版本和补丁是否能应用。第二条编译指定的官方稳定版。第三条使用已验证的 v2.11.37 基线，省去在线查询最新版。缺失的构建依赖及地理数据仍可能需要下载。

## 什么时候需要人工处理

官方更新界面或其固定的 Mihomo 版本时，只要补丁能干净地应用、入站测试通过、Android 编译和 APK 校验成功，脚本就会自动导出 APK。Android JNI 接口、Mihomo 入站结构、Tailscale 库 API 或 Gradle 构建方式改变时，可能需要更新对应补丁或编译脚本。检测到 Mihomo 似乎已加入官方 Tailscale 入站时，脚本会提示先核对现有 YAML 和旧 ADB 5555 配置的兼容性。Go 测试和 Gradle 编译的完整输出保存在 `.clashmeta-build/windows-build.log`。

脚本使用 `.clashmeta-build/android-user/debug.keystore` 中的本地测试签名。保留这个文件，后续同包名且版本号允许升级的 APK 可以覆盖安装。当前已有的 ClashMeta-T 签名可直接复用。通过脚本成功打包代表构建和静态校验通过，Tailnet 连通性和 Android VPNService 行为仍需在设备上验证。
