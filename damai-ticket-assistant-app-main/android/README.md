# 大麦抢票助手 · 安卓版（手机内运行）

把抢票逻辑整合进一个安卓 App，**在手机本地直接运行**，不需要电脑、不需要 Appium Server、不需要 USB 数据线常连。

同时保留**从 Windows 远程调试**的能力（见下文「远程调试」）。

---

## 1. 它是怎么工作的

原方案依赖 Appium 在电脑上驱动手机：

```
[电脑] Python + Appium Server  ──adb──>  [手机] 大麦 App
```

本方案把驱动层搬进手机内部，使用安卓自带的**无障碍服务（AccessibilityService）**：

```
[手机] 大麦抢票助手 App
         └─ AccessibilityService  读屏（节点树）+ 手势（点击/滚动）
              └─ 直接操控「大麦 App」
```

代码对应关系（`damai_appium/runner.py` → `android/app/java/.../TicketRunner.java`）：

| Python（Appium） | 安卓（本地无障碍） |
| --- | --- |
| `webdriver.Remote(endpoint, caps)` | `NodeFinder(accessibilityService)` |
| `WebDriverWait(...).until(presence_of_element_located)` | `NodeFinder.waitForAny(...)` |
| `driver.find_elements(By.ID, ...)` | `NodeFinder.findElements(Selector.id(...))` |
| `mobile: clickGesture {x,y,duration}` | `NodeFinder.clickAt(x, y, duration)` |
| `mobile: scrollGesture` | `NodeFinder.scrollDown(rect, percent)` |
| `RunnerPhase` / `FailureReason` / `LogLevel` | 同名常量类（保持一致） |

流程步骤与 Python 侧一一对应：选城市 → 点购买/预约 → 选票价 → 选数量 → 确认购买 → 选观演人 → 提交订单。

---

## 2. 目录结构

```
android/
├─ app/
│  ├─ AndroidManifest.xml              # 应用清单（含无障碍服务声明）
│  ├─ res/                             # 资源（字符串/主题/无障碍配置）
│  └─ java/com/damai/assistant/
│     ├─ MainActivity.java             # 手机端界面（配置/启停/日志）
│     ├─ DamaiAutomationService.java   # 无障碍服务（自动化引擎入口）
│     ├─ RemoteBridge.java             # 远程调试桥（127.0.0.1:8710）
│     ├─ RunController.java            # 运行控制与状态中心（含重试）
│     ├─ TicketRunner.java             # 抢票流程（对应 Python runner.py）
│     ├─ NodeFinder.java               # 节点查询 + 手势引擎
│     ├─ NodeDumper.java               # 页面层级导出（供远程调试）
│     ├─ Config.java                   # 配置模型（对应 AppTicketConfig）
│     ├─ LogEntry / LogLevel           # 日志
│     └─ Phase / FailureReason         # 阶段与失败原因
├─ build.ps1                           # 离线命令行构建脚本
├─ install.ps1                         # 构建/安装/转发/体检一键脚本
├─ mockapp/                            # 大麦 App 测试替身（复刻 view-id 与页面流转）
├─ debug.keystore                      # 自动生成的调试签名（首次构建产生）
└─ dist/                               # 构建产物（apk）
```

Windows 侧调试与测试工具：

```
tools/damai_remote.py       # 远程调试客户端（状态/配置/启停/日志/dump）
tools/e2e_android_test.py   # 端到端验收测试（模拟器替身，35 项）
tools/adb_drive.py          # 基于 adb 注入的真机驱动（选择器/流程验证）
tools/gesture_probe.py      # 手势注入能力诊断（判定被拦截的原因）
```

---

## 3. 构建（离线，无需 Gradle / 无需联网）

只依赖已安装的 **Android SDK**（`build-tools` + `platforms`）与 **JDK**：

```
aapt2 compile/link → javac → d8 → 打包 → zipalign → apksigner
```

```powershell
cd android
pwsh -File .\build.ps1
```

脚本会自动定位工具（优先 `JAVA_HOME`、Android Studio 自带 `jbr`、`ANDROID_HOME`），产物为：

```
android/dist/damai-assistant-debug.apk
```

可用参数：

| 参数 | 说明 |
| --- | --- |
| `-Clean` | 清理 `android/build` 后重新构建 |
| `-OutDir <路径>` | 自定义输出目录 |

> 为什么不用 Gradle：本机/目标环境常处于离线状态，Gradle 需要联网拉取 Android Gradle Plugin。此脚本仅用 SDK 自带工具即可完成构建，因此更可靠。
> 若要用 Android Studio 打开，需要能访问 Maven 仓库。

---

## 4. 安装与首次配置

```powershell
# 1) 连接手机（开启 USB 调试）
adb devices            # 状态应为 device

# 2) 安装
adb install -r android/dist/damai-assistant-debug.apk
```

然后在手机上：

1. 打开「大麦抢票助手」 App；
2. 点击 **开启无障碍权限** → 在系统列表中找到「大麦抢票助手」并启用；
3. 回到 App，状态显示 **已开启** 即代表自动化引擎就绪；
4. 填写关键词 / 城市 / 票价索引 / 观演人，点击 **开始抢票**。

> 无障碍服务是安卓系统的标准能力，用于辅助操作；本应用只在你点击「开始抢票」后执行动作。

---

## 5. 远程调试（Windows 侧）

手机端 App 在开启无障碍后会同时启动一个调试桥，**只监听 `127.0.0.1:8710`**（回环地址，局域网内其它设备无法访问）。Windows 侧通过 adb 端口转发接进来：

```
[Windows] tools/damai_remote.py  ──>  adb forward  ──>  [手机] 127.0.0.1:8710
```

### 5.1 一键体检

```powershell
adb forward tcp:8710 tcp:8710
python tools/damai_remote.py doctor
```

`doctor` 会依次检查：adb、设备状态、应用是否安装、端口转发、bridge 连通性、无障碍服务是否开启。

### 5.2 常用命令

```powershell
# 查看运行状态（阶段/尝试次数/失败原因）
python tools/damai_remote.py status

# 读取手机上的当前配置
python tools/damai_remote.py get-config

# 下发配置
python tools/damai_remote.py set --city 郑州 --price-index 3 --users 张三,李四

# 启动（可同时下发配置）
python tools/damai_remote.py start --city 郑州 --keyword 张靓颖

# 实时跟踪日志（流程结束后自动退出）
python tools/damai_remote.py logs --follow

# 导出当前页面层级 XML（等价原 scripts/dump_current_page.py）
python tools/damai_remote.py dump -o page_dump_android.xml

# 导出运行报告 JSON
python tools/damai_remote.py report -o run-report-android.json

# 停止
python tools/damai_remote.py stop
```

多设备时用 `--device <序列号>` 指定；端口可用 `--port` 自定义。

### 5.3 协议

一行一个 JSON 请求 / 回应，便于脚本化与二次开发：

```jsonc
// 请求
{"cmd": "start", "config": {"city": "郑州", "users": ["张三"], "if_commit_order": false}}

// 响应
{"ok": true, "state": "running"}
```

支持命令：`ping`、`status`、`getConfig`、`setConfig`、`start`、`stop`、`logs`、`dump`。

### 5.4 其它调试手段（无需本 App 配合）

```powershell
# 实时看系统日志
adb logcat -s DamaiA11yService DamaiRemoteBridge DamaiRunController

# 直接拉取运行报告文件
adb shell run-as com.damai.assistant cat files/../files/damai_run_report.json
adb pull /sdcard/Android/data/com.damai.assistant/files/damai_run_report.json

# 无线调试（手机与电脑同一 Wi-Fi，无需数据线）
adb tcpip 5555
adb connect <手机IP>:5555
```

---

## 6. 与 Python / GUI 版本的关系

| 版本 | 运行位置 | 驱动方式 | 适用场景 |
| --- | --- | --- | --- |
| `damai_gui.py` / `damai_app_v2.py` | 电脑 | Appium + adb | 已有电脑环境、需要可视化面板 |
| **本安卓版** | 手机 | 无障碍服务 | 只想在手机上跑、无需电脑常连 |

两套实现共用同一套流程语义（阶段、失败原因、日志格式），因此日志与报告可以互相参照。

---

## 7. 常见问题

**Q：App 显示「无障碍服务未开启」？**
到「设置 → 无障碍 → 已安装的服务」中启用「大麦抢票助手」。部分机型还需要在「设置 → 应用 → 大麦抢票助手 → 电池」中允许后台活动。

**Q：`doctor` 报 bridge 连不上？**
1. 确认手机端 App 已打开且无障碍已启用（bridge 随服务启动）；
2. 重新执行 `adb forward tcp:8710 tcp:8710`；
3. 确认没有其它程序占用 8710。

**Q：找不到票价 / 观演人？**
大麦 App 会随版本调整控件 id。可先用 `python tools/damai_remote.py dump -o p.xml` 导出页面层级，对照 `TicketRunner.java` 中的选择器更新。

**Q：担心自动提交订单？**
默认关闭（`if_commit_order = false`），流程会在进入确认页后停下，由你手动支付。

**Q：真机上点「立即购票」没反应？**
这是**已确认的应用侧防护**：大麦会过滤来自无障碍服务（`dispatchGesture`）的注入手势。
请先运行 `python tools/gesture_probe.py --selftest` 确认结论，再用
`python tools/adb_drive.py`（adb 注入）完成真机验证。详见第 9.3 / 9.4 节。

**Q：`adb install` 报 `INSTALL_FAILED_USER_RESTRICTED`？**
部分国产 ROM 会拦截 adb 安装。改用：
```powershell
adb push android\dist\damai-assistant-debug.apk /data/local/tmp/da.apk
adb shell pm install -r -t /data/local/tmp/da.apk
```

**Q：`uiautomator dump` 报 `could not get idle state`？**
部分真机（含本机 MEIZU 21 Pro）uiautomator 不稳定。
本项目的 `damai_remote.py dump` 走 App 内桥接，稳定可用；`adb_drive.py` 也已默认优先用它。

---

## 8. 验收测试

### 8.1 为什么需要「大麦替身」

真实大麦 App 需从应用商店下载（无法离线获取）。`android/mockapp/` 是一个**测试替身**：
它以 `package="cn.damai"` 构建，并复刻真实大麦的 **view-id 与页面流转**
（详情页 → 票价页 → 确认页 → 订单页 → 提交完成），
因此 `TicketRunner.java` 中现成的选择器、坐标点击与观演人勾选逻辑都能被真实执行到。

### 8.2 运行验收

```powershell
# 构建两个 APK
pwsh -File android\build.ps1
pwsh -File android\build.ps1 -AppDirName mockapp -ApkName damai-mock

# 安装
adb install -r android\dist\damai-assistant-debug.apk
adb install -r android\dist\damai-mock.apk

# 开启无障碍（重装后需重新开启）
adb shell settings put secure enabled_accessibility_services com.damai.assistant/com.damai.assistant.DamaiAutomationService
adb shell settings put secure accessibility_enabled 1

# 一键验收
python tools\e2e_android_test.py --report e2e.txt --screenshots .\shots
```

### 8.3 覆盖范围（35 项，已在本机模拟器全部通过）

| 分组 | 覆盖内容 |
| --- | --- |
| A 远程通道 | `doctor` 全绿、`status` 可用、无障碍已连接 |
| B 完整流程 | 购买入口点击、**票价索引命中**、确认购买、进入订单页、未开启自动提交时不提交、观演人精确勾选 |
| C 自动提交 | 走到「立即提交」完成 |
| D 多观演人 | 2 人组合（3 组）与 3 人全选，全部精确勾选 |
| E 幂等性 | 已勾选观演人**不重复点击、不误取消** |
| F 停止信号 | `stop` 生效、阶段为 `stopped`/`user_stop` |
| G 异常路径 | 无可购入口时**快速失败且不卡死** |
| H 页面 dump | 合法 XML、层级可解析、含 `cn.damai:id/*`、uiautomator 风格属性 |

### 8.4 测试中发现并修复的缺陷

1. **`resources.arsc` 必须不压缩存储**
   targetSdk ≥ 30 时，若把 arsc 一起压缩，安装会失败：
   `requires the resources.arsc of installed APKs to be stored uncompressed`。
   已在 `build.ps1` 中改为逐条复制并保留 arsc 的存储方式。

2. **连续手势会被前一次取消（影响多观演人勾选）**
   `dispatchGesture` 会取消尚未完成的上一个手势。原先观演人之间仅间隔 20ms，
   而单次点击手势持续 50ms，导致**只有最后一个观演人被勾选**。
   已改为**同步等待手势完成**（回调投递到独立 `HandlerThread`，避免与工作线程互等死锁）。

3. **管道输出编码错误（影响脚本调用）**
   `damai_remote.py` 的输出被重定向到管道时，Python 使用系统 locale 编码（简体中文 Windows 为 GBK），
   中文变乱码、emoji 直接抛 `UnicodeEncodeError`。
   已改为：非 TTY 时强制 UTF-8 输出；TTY 下保留控制台编码并容错。

4. **`NodeDumper` 丢失层级**
   原先所有节点自闭合，父子关系丢失，无法用于结构分析。
   已改为真实嵌套 XML，格式与 `uiautomator dump` 对齐，项目原有的 dump 分析脚本可直接复用。

---

## 9. 真机全流程（详情页 → 提交订单，含刷新）

> 端到端驱动：`tools/real_device_dryrun.py`（功能完整）
> 极速驱动：`tools/fast_run.py`（低延迟优化版，见 9.6 耗时分析）
> 逐阶段计时：`tools/time_stages.py`

### 9.1 流程与刷新点

```
演出详情页
  ├─（购买入口缺失时）点「努力刷新」捡漏 → 重试购买入口   ← 刷新点 1
  └─ 点购买入口 → 过弹窗（票务须知 / 实名制观演）
       └─ 票档页 → 按 price_index 选票档 → 点「确定」
            └─（出现「努力刷新」时）刷新并重新确认        ← 刷新点 2
                 └─ 确认订单页（DmOrderActivity）
                      ├─ 勾选观演人（已勾选则跳过，不误取消）
                      └─ 点「立即提交」
                           └─（出现「继续尝试」时）关闭并重新提交  ← 刷新点 3
```

三个刷新点与 `damai_appium/runner.py` 的 Python 实现一一对应，
在 Java（`TicketRunner`）与 adb 驱动（`adb_drive.py`）两侧都已实现。

### 9.2 用法

```powershell
# 默认：跑到确认订单页并勾选观演人，不提交
python tools\real_device_dryrun.py --serial <设备> --price-index 3 --users 姚瑜

# 极速版（低延迟，用于抢票）
python tools\fast_run.py --serial <设备> --price-index 3 --users 姚瑜

# 逐阶段耗时
python tools\time_stages.py --serial <设备> --price-index 3

# 关闭刷新重试 / 真正提交
python tools\real_device_dryrun.py --serial <设备> --no-refresh
python tools\real_device_dryrun.py --serial <设备> --submit
```

### 9.3 真机实测结果

```
详情页: ...ProjectDetailActivity
票档页: ...NcovSkuActivity   票档共 9 个 → 选 index=3
确认订单页: ...DmOrderActivity
观演人状态: [x] 姚瑜
结果: 已到达确认订单页并完成勾选 OK
```

| 环节 | 结果 |
| --- | --- |
| 详情页 → 购买入口 | ✓ 自定义绘制按钮，按 bounds 点击 |
| 弹窗处理 | ✓ 票务须知 / 实名制观演自动关闭 |
| 票档页 + price_index | ✓ index=3 → 看台500元，页面价格同步为 ¥500 |
| 确定 → 确认订单页 | ✓ `DmOrderActivity` |
| 观演人勾选 | ✓ `[ ]` → `[x]`，重复勾选幂等（不误取消） |
| 刷新按钮探测 | ✓ 无该按钮时快速返回、不误点 |

### 9.4 刷新「快速失败」的原因

「努力刷新」「继续尝试」只在**售罄 / 未开售 / 库存不足**时出现。
本次场次有票，因此这两个按钮不会出现——探针正确返回「未出现」，不误点其它元素。
分支逻辑已按真机出现的条件实现，真正抢票（无票）时会自动生效。

### 9.5 踩坑记录（均为真机实测发现）

1. **票档页进入瞬间 bounds 会漂移**
   实测：刚进入票档页时，票档项 bounds 可能是 `x=1442`（**屏幕外**，横向滚动中间态），
   约 0.8s 后才稳定到 `x=74`。此时点击必然落空（表现为「停在票档页、价格仍为 0」）。
   → 修复：**等「票档项落在屏幕内 且 连续稳定」**再点击（`wait_price_ready`）。

2. **`每次 spawn adb` 的进程开销巨大**
   实测 `adb shell input tap` 每次约 **85–135ms**，其中绝大部分是 adb 进程启动。
   → 修复：复用常驻 `adb shell` 的 stdin，客户端开销降到 **<1ms**（只有设备端 `input` 自身耗时）。

3. **观演人在 dump 中嵌套两层 `layout_main`**，按姓名去重后才不重复。

### 9.6 预选机制实测（能否进一步压缩）

大麦提供「抢票攻略」预选入口（详情页「设置本次抢票信息，抢票快人一步！」）。

**实测事实：**

| 项 | 实测结果 |
| --- | --- |
| 预选页内容 | **只有 Step 1「预选本次实名观演人」**，没有票档预选项 |
| 预选观演人是否生效 | **生效** —— 确认订单页观演人状态实测为 `[('姚瑜', True)]`，已自动勾选 |
| 票档是否会被记忆 | **不会** —— 选过 index=3 后返回详情页再进入，`tv_price` 仍为 0 |
| 票档是否自动选中 | **不会** —— 不选票档直接点「确定」会停在票档页，进不了订单页 |

**因此的实际优化：**

| 步骤 | 必要性 | 耗时 | 说明 |
| --- | --- | --- | --- |
| 点击购买入口 | 必须 | 31–524 ms | — |
| 等票档页就绪 | 必须 | 426–531 ms | 不可压缩（App + 网络） |
| 等票档屏内稳定 | 必须 | 500–1150 ms | 不可压缩（大麦横向滚动动画） |
| 选票档 | 必须 | 1–2 ms | 已优化 |
| 票档生效（价格重绘） | 必须 | 135–307 ms | 不可压缩（App 重绘） |
| 点确定 | 必须 | 105–128 ms | 已优化 |
| 等确认订单页 | 必须 | 465–711 ms | 不可压缩（App + 网络） |
| ~~选观演人~~ | **可跳过** | **0 ms** | ★ 预选已生效，无需点击 |

> 结论：**预选让「选观演人」这一步变成 0 点击**，但该步骤本来只占约 100–150 ms，
> 因此总收益有限。**票档必须主动选择，无法跳过**。

`tools/preset_run.py` 即按此实现：默认跳过观演人点击（只读状态确证），
可用 `--verify-users` 改为校验/补齐，`--skip-price` 用于测试票档是否被自动选中。

### 9.7 耗时分析与 0.5s 可行性结论

**优化历程：**

| 版本 | 详情页 → 可提交订单 |
| --- | --- |
| 原始（固定 sleep） | 约 33.4 s |
| 严格轮询（`fast_run.py`） | 中位 2.46 s |
| 预选优化（`preset_run.py`） | 中位 2.39 s |
| 极限压缩 | 1.68 – 1.89 s |

**耗时归因（中位约 2.4 s）：**

| 阶段 | 耗时 | 性质 |
| --- | --- | --- |
| 点击购买入口 | 31–524 ms | 可压缩 |
| **等票档页就绪** | 426–531 ms | **不可压缩**（App 页面创建 + 数据渲染，含网络） |
| 等票档屏内稳定 | 500–1150 ms | **不可压缩**（大麦横向滚动动画收敛） |
| 选票档 + 生效 | 136–309 ms | 部分可压缩 |
| 点确定 + **等确认订单页** | 570–839 ms | **不可压缩**（App 页面创建 + 数据渲染，含网络） |
| 读取观演人状态 | 82–103 ms | 可压缩（预选后仅需确认） |

**硬性下限 ≈ 1.4 s**（三段 App 内部页面创建/渲染 + 票档页滚动动画），
再加至少 4 次 `dump` 取坐标（每次 35–75 ms）。

**结论：0.5 s 不可达。** 原因：

1. 三段 App 内部页面创建/渲染 + 票档页滚动动画合计约 1.4 s，
   是**设备端 + 网络**成本，脚本侧无法压缩；
2. 每次读取界面坐标必须 `dump` 整棵节点树，单次 35–75 ms，全流程最少 4 次；
3. `adb` 注入 `tap` 在设备端仍有排队延迟。

**实际可达下限约 1.5 s**（实测最快 1.68 s）。

**若要继续逼近下限，可行方向（均在不牺牲正确性的前提下）：**

- **预热到票档页**：抢票前先停在票档页，跳过「点购买入口 + 等票档页就绪」约 0.5–1.0 s；
  抢票瞬间只需「选票档 → 确定 → 提交」，约 **0.9–1.1 s**。
- **减少 dump 次数**：目前约 4 次取坐标，可由 60 ms/次进一步合并到 2 次。
- **改用 Shizuku 在设备内注入**：省掉 adb 通道往返（当前已用常驻 shell，客户端开销 <1 ms，
  这部分已基本无优化空间）。

**⚠️ 硬性边界**：0.5 s 需要连「票档页 → 订单页」两次 App 内部页面跳转都完成，
而每次跳转实测 400–700 ms，**物理上不可能压缩到 0.5 s**。

### 9.8 工具一览

| 工具 | 说明 |
| --- | --- |
| `tools/real_device_dryrun.py` | 全流程：详情页 → 提交订单；含 `--users` / `--submit` / `--no-refresh` |
| `tools/fast_run.py` | 极速版：常驻 adb shell + 严格轮询 + 屏幕感知稳定等待 |
| `tools/preset_run.py` | 预选优化版：跳过已预选的观演人；`--skip-price` 测试票档自动选中 |
| `tools/time_stages.py` | 逐阶段耗时测量，用于定位瓶颈 |
| `tools/adb_drive.py` | 底层驱动：`refresh` / `continue-try` / `viewers` / `select-viewers` / `submit` |
| `tools/gesture_probe.py` | 手势注入能力诊断（判定被拦截的原因） |

---

## 10. 真机环境与限制（MEIZU 21 Pro / Android 16 / 大麦 9.0.28）

在真机上用今天可抢的场次做了实际预演（**合肥·2026张韶涵玩家巡回演唱会-合肥站**，
票价 ¥399–1580，9 个票档），不使用模拟器替身。

### 10.1 已逐项验证通过

| 项目 | 结果 |
| --- | --- |
| 安装（国产 ROM） | `adb install` 被 `INSTALL_FAILED_USER_RESTRICTED` 拦截；**`pm install -r -t` 可成功** |
| 无障碍服务 | 正常绑定，`capabilities=33`（含 `CAN_PERFORM_GESTURES`=32） |
| 远程调试通道 | `doctor` 全绿；`status` / `dump` / `logs` 正常 |
| 页面层级读取 | 正确读到真实 `cn.damai:id/*`（`uiautomator dump` 在这台机器上不可用，会报 `could not get idle state`，改用 App 内桥接 dump） |
| **购买入口选择器** | `trade_project_detail_purchase_status_bar_container_fl` **命中** |
| **票档容器选择器** | `project_detail_perform_price_flowlayout` **命中** |
| **确认按钮选择器** | `btn_buy_view` **命中** |
| **观演人选择器** | `recycler_main` / `layout_main` / `text_name` / `checkbox` **全部命中**，结构与代码预期一致 |
| **票价索引映射** | index=3 → 选中的是「看台500元」，页面价格同步变为 **¥500**，与截图逐档一致 |
| **观演人勾选** | 用真机页面点击后 `checked` 由 `false` → `true`，并可再次点回 `false` |
| 完整链路 | 详情页 →（弹窗）→ 票档页 → 选档 →「确定」→ **确认订单页 `DmOrderActivity`**，显示「¥500.00 票档 ×1张」+ 观演人 + 「立即提交」 |

> 预演在「确认订单页」停止，**未提交任何真实订单**。

### 10.2 真实页面结构与代码预期的差异（已据此改造）

1. **购买/确认按钮是自定义绘制**
   `trade_project_detail_purchase_status_bar_container_fl` 与 `btn_buy_view` 都是
   `clickable=false` 且**无文本**，不能靠 `clickable` 或文本定位，必须按其 `bounds` 中点坐标点击。

2. **链路中存在阻断式弹窗**
   点击「立即购票」后会依次弹出：
   - 「票务须知」→ `cn.damai:id/damai_theme_dialog_confirm_btn`（确认并知悉）
   - 「实名制观演」→ 同 id（预选实名观演人）/ `damai_theme_dialog_cancel_btn`（知道了）

   已新增 `dismissBlockingDialogs()`，并在流程各关键步骤前后统一清理。

3. **票档文本在无障碍树中为空**
   实测确认价格文本（如「看台399元」）**不出现在节点树**里，只能靠 `price_index` 索引选择
   —— 与第 7 节「已知问题」一致，属大麦自身实现。

4. **观演人 checkbox 是切换语义**
   真机验证：对已勾选的 checkbox 再点一次会**取消勾选**。
   因此 `_select_users` 中「先判断 `checked`，已勾选则跳过」的保护是**必需**的，不能省。

### 10.3 关键限制：大麦会过滤无障碍注入手势 ⚠️

这是本次真机实测的**决定性结论**。用 `tools/gesture_probe.py` 得到的判据：

```
[A] 无障碍手势能力: capabilities=33 canPerformGestures=True
[B] 自检：在本应用界面上点击「开启无障碍权限」
    点击前前台: com.damai.assistant/.MainActivity
    点击 (684,951) duration=50ms -> outcome=0 (完成，手势已送达)
    点击后前台: com.android.settings/...FlymeAccessibilitySettingsActivity
    => 本应用点击有效：手势注入链路正常
    => 结论 C：目标 App 内点击无效，是该 App 过滤了注入手势（应用侧防护）
```

三重交叉验证：

| 验证 | 结果 |
| --- | --- |
| `dispatchGesture` 回调 | `onCompleted`（outcome=0），手势**确实送达** |
| 同一坐标用 `adb shell input tap` | 大麦**正常响应**（能选票价、能进确认页） |
| 同一手势在我们自己的 App / 系统设置上 | **正常响应**（能跳转无障碍设置页） |

因此：
- 无障碍服务能力、坐标、选择器、流程编排**都没有问题**；
- **大麦 App 在应用内部过滤了来自无障碍服务的注入手势**；
- `adb input tap` 走的是系统输入通道、注入源不同，所以有效。

### 10.4 因此的可行路径

| 方案 | 说明 | 真机结论 |
| --- | --- | --- |
| 无障碍 + `dispatchGesture`（当前默认实现） | 在大麦上被过滤 | ✗ 被防护拦截 |
| **`adb shell input tap`（外部注入）** | 实测可完整走通全流程 | ✓ 可行，但需电脑常连 |
| App 内 root 执行 `input` | 需 root | △ 需 root |
| **接入 Shizuku，以 ADB 权限在设备内注入** | 无需 root、无需常连电脑，注入源等同 adb | ✓ 推荐下一步 |

> 结论：**纯无障碍手势方案在大麦上不可行**。
> 节点读取、选择器、流程编排、弹窗处理、日志与远程调试这些部分**全部已验证可用并可复用**；
> 需要替换的只是「执行点击」这一步的注入通道（见 `NodeFinder.Injector` 抽象）。

### 10.5 新增的排障工具

| 工具 | 用途 |
| --- | --- |
| `tools/gesture_probe.py` | 判定手势为何无效：`--selftest` 给出 A/B/C 结论 |
| `tools/adb_drive.py` | 基于 adb 注入的底层驱动：`status` / `verify` / `dialog` / `prices` / `tap --id|--text` |
| `tools/real_device_dryrun.py` | **真机全流程预演**：首页 → 详情页 → 票档 → 确认订单页，**在确认页停止、不提交订单** |

真机预演示例（本次实测即用它跑通）：

```powershell
python tools\real_device_dryrun.py --serial <设备序列号> --keyword 张韶涵 --price-index 3
```

输出示例：

```
起始前台: cn.damai/.homepage.MainActivity
已点击演出卡片 (768,1612)
详情页: cn.damai/.trade.newtradeorder.ui.projectdetail.ui.activity.ProjectDetailActivity
已点击购买入口
票档页: cn.damai/.commonbusiness.seatbiz.sku.qilin.ui.NcovSkuActivity
票档共 9 个
已选 index=3 center=(533,1795)
已点击「确定」
当前前台: cn.damai/.ultron.view.activity.DmOrderActivity
结果: 已到达确认订单页 OK
```

---

## 11. 免责声明

同项目根目录 `README.md`：仅供学习与技术研究使用，请遵守大麦网服务条款，勿用于恶意刷票。
