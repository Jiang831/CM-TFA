# Clash Meta & Tailscale 入站配置

把 `type: tailscale` 和 `forwards` 放在当前配置的 `listeners` 下。每项转发在 Tailnet 上监听一个端口。修改端口、协议、目标或规则之后，保存配置并重新加载即可生效。

## 独立入站

```yaml
listeners:
  - name: tailnet-services
    type: tailscale
    hostname: android-services
    # 首次注册可填写 auth-key，或者根据应用日志完成登录
    # auth-key: <your-auth-key>
    # control-url: https://headscale.example.com
    proxy: DIRECT
    forwards:
      - listen: 8443
        target: 127.0.0.1:8080
        network: tcp
      - listen: 5353
        target: '[::1]:5353'
        network: udp
```

| 入站字段 | 含义 |
| --- | --- |
| `name`、`type` | 必填。名称在配置内唯一，类型为 `tailscale` |
| `forwards` | 必填，至少一条。每条设置 `listen` 和 `target` |
| `hostname` | Tailscale 节点名。独立入站省略时，由监听器名称生成 |
| `state-dir` | 节点持久化目录。相对路径以 Mihomo 工作目录为基准。独立入站默认使用 `tailscale/<hostname>` |
| `control-url`、`auth-key` | 可选的控制面地址和注册密钥。保留持久化状态时可以复用既有身份 |
| `ephemeral`、`accept-routes` | 独立入站默认分别为 `false` 和 `true`。共享节点继承出站设置 |
| `rule` | 可选的 Mihomo `sub-rules` 名称 |
| `proxy` | 可选的默认出站。设为 `DIRECT` 直连，也可填代理或代理组名。省略时使用 Mihomo 路由 |

`forwards.listen` 接受 1–65535，`target` 接受域名、IPv4 或带方括号的 IPv6 加端口。每条转发可用 `proxy` 覆盖监听器的出站。协议支持 `tcp`、`udp` 和默认的 `auto`，其中 `auto` 同时绑定 TCP 与 UDP。同一节点上的协议和端口组合必须唯一。入站登录和绑定在后台进行，应用日志显示端口何时可用。

## 与现有 Tailscale 出站共用节点

监听器可以用 `hostname` 匹配同一配置中唯一的 Tailscale 出站。也可以显式指定相同的 `state-dir` 来匹配，同名节点有多个状态目录时需要这样指定。共享节点的 `auth-key`、`control-url`、`ephemeral` 和 `accept-routes` 设在出站上。多个独立入站共用状态目录时，这些节点级选项设在该节点第一个监听器上。

现有的 ADB 配置仍可直接使用。以下示例假设已有同名出站，且使用相同状态目录。

```yaml
listeners:
  - name: tailscale-adb-5555
    type: tailscale
    hostname: android-services
    state-dir: tailscale/android-services
    forwards:
      - listen: 5555
        target: 127.0.0.1:5555
        network: tcp
        proxy: DIRECT
```

Tailnet 的 ACL 或 grants 决定哪些来源可以访问节点端口。ADB 5555 等管理端口宜仅授权给受信设备。

## 构建基线

- Android 应用基线为 Clash Meta for Android v2.11.37 的版本修正提交 `215e017ae88ac2a1edf24fdb520512c1423c89f4`。
- Mihomo Android 子模块固定为 `0455d0d28c4526937380505153e65a843d8612e8`，构建时应用 [入站补丁](../tools/cmtfa/mihomo-tailscale-inbound.patch)。
- [测试 APK 工作流](../.github/workflows/cmtfa-android-test.yml) 使用包名 `com.jiang831.cmtfa`，并校验配置解析、转发、APK 签名和 SHA-256。
