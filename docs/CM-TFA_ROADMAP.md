# CM&TFA — 独立开发工程说明

## 目标

在官方 Clash Meta for Android v2.11.37 基础上，独立包名运行 CM&TFA；在保留代理和 Tailscale 出站的前提下，实现基于 Tailnet IP 的 TCP/5555 入站监听，转发到 Android 本机 `127.0.0.1:5555`，供原 Quicker《镜像设备 R9》按 USB → WLAN → Tailnet 顺序自动回退。

## 精确基线

- 官方应用标签：`MetaCubeX/ClashMetaForAndroid@v2.11.37`
- 官方标签指向 `f454fa8c569ea2a2396f2fe453ac8263832001d8`，构建使用紧随其后的版本号修正提交 `215e017ae88ac2a1edf24fdb520512c1423c89f4`
- Android Mihomo 子模块 commit：`0455d0d28c4526937380505153e65a843d8612e8`
- 独立包名：`com.jiang831.cmtfa`
- 测试分支：`cmtfa/v2.11.37-dev`
- 开发分支上的 Actions 对固定的 Mihomo 子模块应用项目补丁，并验证 R10 配置解析、APK 签名和 SHA-256。

## 开发闭环

1. **B0：独立应用构建。** 使用随包 GitHub Actions 编译官方内核 + 独立包名 APK，验证普通代理、Android VPNService、TUN、DNS、规则；原 CMFA 不卸载。该阶段不包含 Tailscale 入站。
2. **B1：内核源码适配。** `tools/cmtfa/mihomo-tailscale-adb.patch` 让 R10 的入站监听复用同一配置中 hostname 和 state-dir 匹配的 Tailscale 出站节点。支持 TCP 5555 到 Android 本机 127.0.0.1:5555 的单条 DIRECT 转发。
3. **B2：自动化与运行时验收。** 实测同一配置的出站和入站不会注册重复节点；配置重载不残留监听/身份；VPNService 切换不破坏代理；限制 5555 的 Tailnet 来源。
4. **B3：移动数据远程镜像。** 手机关闭 WiFi，启用 5G、CM&TFA 与 ADB TCP 5555；Windows 先 `Test-NetConnection <测试节点IP> -Port 5555`，再 `adb connect`、`adb devices -l` 和 `getprop ro.serialno`。成功后用镜像动作实测。

## 非功能要求

- R10 生成器预期 `listeners.type: tailscale` 和 `forwards`，但 **官方 CMFA 内核目前没有验证兼容该语法**。
- 不上传私有 Tailnet 的 state-dir、node key、auth key、签名私钥。独立包名意味着新 APP 的 Tailscale 身份一般不同，不保证原节点 `100.100.44.44` 保持。
- 端口 5555 为高权限 ADB 调试端口，必须由 Tailnet ACL/grants 限制受信来源；不要通过公网端口映射暴露。
- APK 必须先具备普通代理功能，之后才可验收入站，不能将 B0 的成功误报为 B3。
- 本工程以最小增量修改为原则，避免更动原镜像动作、R10 配置生成器和 CMFA 上游无关功能。
