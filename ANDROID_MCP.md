# Android MCP Bridge 使用说明

这是 Skidc 的第一版 Android 目标扩展。它不是用来替代原来的 Web/API
测试能力，而是在现有系统上新增一个“移动端 App 控制面”，让原本的
`bootstrap -> reason -> explore -> fact` 调度流程也可以操作 Android 模拟器里的 App。

简单理解：

```text
原来：Agent 主要访问网页、接口、主机环境
现在：Agent 还可以启动 App、点击界面、读取 UI 树、截图、查看网络记录
```

## 它提供什么能力

推荐使用统一 Android Lab 入口：

```bash
./scripts/android-lab.sh init   # 首次执行一次
./scripts/android-lab.sh up
./scripts/android-lab.sh status
./scripts/android-lab.sh smoke
```

`up` 一次启动 Web Server、Dispatcher、Android Emulator 和 Android Bridge。
如果单独调试 Bridge，必须显式提供 `--token-file`；生产使用不要绕过
`android-lab.sh` 的 secret、资源限制和就绪检查。

它底层通过 `adb` 控制 Android 模拟器/真机，并暴露这些接口：

| 能力区域 | 接口 |
|---|---|
| 设备状态 | `GET /health`, `GET /devices` |
| App 控制 | `POST /app/install`, `/app/start`, `/app/stop`, `/app/clear` |
| 输入操作 | `POST /input/tap`, `/input/text`, `/input/swipe`, `/input/back`, `/input/home` |
| 页面观察 | `GET /observe/ui`, `/observe/activity`, `/observe/screenshot`, `POST /observe/logcat` |
| 网络记录 | `GET /network/history`, `POST /network/events`, `DELETE /network/history` |
| APK 静态分析 | `POST /reverse/analyze`, `GET /reverse/reports`, `DELETE /reverse/reports` |

第一版主要使用：

```text
ADB：连接设备、启动 App、输入点击、截图、读取日志
UIAutomator dump：导出当前 App 页面控件树
FastAPI：把这些能力包装成 HTTP 接口
```

### 受限 APK 静态分析

将授权 APK 放入 `datas/android-artifacts/` 后，可以请求：

```text
android-mcp POST /reverse/analyze '{"assessment_id":"proj_001","apk_path":"/artifacts/demo.apk"}'
```

Bridge 会先完成有界 ZIP/字符串扫描，再在一次性 `/tmp` 工作目录中调用：

```text
aapt：包名、版本、SDK 和权限
apktool：Manifest、安全配置、导出组件和 Deep Link
jadx：WebView、TLS、密码学、日志、存储、明文端点和疑似凭据线索
```

响应中的 `analysis_level` 表示是否获得工具增强结果，`tool_runs` 分别显示三个工具的
`completed`、`unavailable`、`timeout` 或 `failed` 状态。单个工具失败不会丢弃其他
结果。`code_findings` 只返回固定摘要和相对 `evidence_ref`，不会返回整份源码或完整
凭据值。所有静态结果都只是调查线索，必须结合 UI、网络、Logcat 或独立运行时复现后
才能形成漏洞结论。反编译目录在请求结束后立即删除。

后续可以继续叠加：

```text
Appium：更完整的自动化测试框架
OCR：识别截图里的文字
mitmproxy：自动导入 App 网络请求
Frida：更深层的 Hook、签名参数和运行时分析
```

## 怎么接入 Skidc

使用 [dispatch_android.example.yaml](dispatch_android.example.yaml)，关键配置是：

```yaml
runtime:
  prompt_group: "default"
  target_prompt_groups:
    android: "android"

android_bridge:
  url: "http://127.0.0.1:8765"
  token_file: "/run/secrets/android_mcp_token"
  worker_token_file: "/run/skidc/android-mcp-token"
  readiness_timeout: 15
```

这里的意思是：

```text
target_prompt_groups.android: "android"
只让 target_type 为 android 的项目使用 Android 专用提示词。

android_bridge
告诉 Dispatcher Bridge 地址和凭据文件位置。Token 值不会进入 Prompt、worker
环境或命令参数；Dispatcher 只给 Android worker 写入 mode 0600 的凭据文件。
```

创建项目时，`origin` 可以描述 App 目标，例如：

```text
APK: /artifacts/demo.apk
Package: com.example.demo
Test accounts: user_a / user_b
Proxy: mitmproxy or Burp if configured
```

创建项目时还要把 `recon_profile.target_type` 设为 `android`。APK 由操作者预先放入
`datas/android-artifacts/`，容器内统一引用 `/artifacts/<文件名>.apk`。

然后 Skidc 的流程仍然不变：

```text
reason 读取当前图谱
-> 生成 Android 相关 intent
-> explore 调用 Android bridge 操作 App
-> 把观察结果写回 fact
-> reason 再判断下一步或是否完成
```

Android prompt 组会引导 worker 在 `explore` 阶段调用 bridge，并把观察结果写成类似这样的 fact：

```json
{
  "description": "登录 user_a 后进入订单详情页，观察到 App 请求 /api/order/detail?order_id=1001，响应包含订单所有者信息",
  "scope": "mobile_api",
  "vuln_type": "business_logic",
  "severity": "medium"
}
```

## 第一版边界

这一版是最小可用版本，故意保持克制：

```text
不暴露任意 adb shell 执行
不默认做 Frida Hook
不默认做 OCR
不直接集成 Burp
不自动判断所有漏洞成立
```

它先解决最核心的问题：

```text
让 Agent 能控制 Android App
让 Agent 能观察 App 页面和状态
让 App 端发现可以写回 Skidc 的 fact-intent 图
```

这样就能和原有逻辑漏洞检测能力衔接起来：Android bridge 负责“进入和操作移动端业务流程”，reason/explore 负责“基于事实继续规划和判断”。

## 为什么它不是替代 Web 测试

这个模块的定位是新增目标类型：

```text
Web/API 测试：继续保留
Android App 测试：新增能力
混合目标：App 操作 + API 观察 + Web/API 验证
```

很多真实业务只有 App 入口，例如登录、订单、优惠券、积分、支付、设备绑定等。Android bridge 让 Skidc 可以覆盖这些移动端原生流程，而不是只停留在网页端。
