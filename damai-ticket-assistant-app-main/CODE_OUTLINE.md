# 大麦抢票助手（damai-ticket-assistant-app-main）程序代码大纲

> 基于 [WECENG/ticket-purchase](https://github.com/WECENG/ticket-purchase) 二次开发。
> 已**剔除网页模式（Web / Selenium）**，仅保留「App 模式（Appium / 安卓大麦 App）」抢票能力，外加图形界面、安装器与测试套件。

---

## 0. 项目概览

- **技术栈**
  - 语言：Python（pyproject 声明 `^3.8`；安装器与文档按 3.9~3.13 验证）
  - 包管理：Poetry（`pyproject.toml` / `poetry.lock`），另附 `requirements.txt`
  - 依赖：`pydantic ^2.6`、`Appium-Python-Client ^3.1`、`selenium`（Appium 运行器的传递依赖）
  - GUI：Tkinter / ttk（标准库）
  - 质量工具：pytest + pytest-cov、ruff、mypy
- **单一主线：App 模式**
  - `damai_appium/`（Appium 驱动 `cn.damai` 安卓 App）
  - `damai_gui.py`（Tkinter 图形界面，仅 App 模式）
  - `damai/authz.py`（授权校验，与模式无关）
- **目录速览**

```
.
├─ start_gui.pyw            # GUI 启动入口（带运行时补丁）
├─ damai_gui.py             # 主 GUI（App 模式）
├─ damai/                   # 授权校验（authz）
├─ damai_appium/            # App 模式核心（配置 / 运行器 / CLI）
├─ damai_installer/         # Windows 一键安装器（Tkinter + PyInstaller）
├─ tests/                   # pytest 单元/集成测试
├─ scripts/                 # 辅助脚本（页面 dump、观演人选择验证等）
├─ examples/                # 运行器演示
├─ docs/                    # 上手指南、流程图、截图
├─ vendor/                  # 上游原始仓库快照（参考用）
├─ _bench_session.py / _dump_home.py   # 临时调试脚本
└─ page_dump*.xml / *.png   # 调试产物（UI 层级 / 截图）
```

---

## 1. 入口层

### 1.1 `start_gui.pyw` — GUI 启动器
- 职责：把项目根目录加入 `sys.path`，创建 `damai_gui.DamaiGUI()` 实例并启动主循环。
- **运行时补丁（Monkey Patch，不改动 `damai_gui.py`）**
  - `_patched_start_appium_server()`：启动成功后按钮文案切为「停止 Appium」
  - `_patched_stop_appium_server()` / `_patched_reset_appium_state()`：复位为「启动 Appium」
  - `_appium_watchdog()`：每 1s 轮询 `appium_process.poll()`，外部控制台被关闭时自动复位状态
  - `_on_close()`：退出前若 Appium 仍在运行则自动 `_stop_appium_server()`
- 异常兜底：`ImportError` → 「依赖缺失」对话框；其他异常 → 「启动失败」对话框
- 注意：授权校验 `block_if_unauthorized_with_ui()` 调用目前被**注释掉**

### 1.2 `damai_gui.py` — 主 GUI（`class DamaiGUI`）
按功能分组的方法：

| 分组 | 方法 |
| --- | --- |
| 初始化/主循环 | `__init__`、`run`、`create_interface` |
| 步骤面板 | `create_steps_frame`、`refresh_steps`、`update_step`、`mark_step` |
| 面板构建 | `create_main_functions`、`_build_app_panel`、`_create_app_form_fields`、`_create_app_advanced_fields`、`_create_collapsible_section`、`create_control_buttons` |
| App 表单 | `_init_app_form_vars`、`_populate_app_form`、`_build_app_config_payload`、`_collect_app_config_from_form`、`_validate_app_form`、`_update_app_summary_from_form`、`_refresh_app_start_button`、`_get_users_from_widget`、`_on_app_users_modified` |
| App 配置加载 | `_get_default_app_config_path`、`select_app_config`、`load_app_config`、`open_app_docs`、`_set_app_summary_text` |
| 配置校验报错 | `_format_config_errors`、`_show_config_validation_error` |
| 日志系统 | `log`、`clear_logs`、`_infer_log_level`、`_log_passes_filter`、`_append_log_entry`、`_refresh_log_view`、`_on_log_filter_changed`、`export_logs` |
| 运行统计展示 | `_update_app_metrics_display`、`_format_failure_for_display` |
| 环境检测 | `check_environment`、`_check_app_environment`、`_resolve_cli_command`、`_check_cli_dependency`、`_check_node_cli`、`_check_appium_cli`、`_check_adb_cli` |
| Appium 服务管理 | `_toggle_appium_server`、`_start_appium_server`、`_stop_appium_server`、`_reset_appium_state`、`_validate_app_server` |
| 设备管理 | `_refresh_devices_clicked`、`_perform_device_refresh`、`_update_device_status_from_result`、`_detect_connected_devices`、`_set_device_status`、`_set_device_detail`、`_reset_device_status_ui`、`_format_detected_device_list`、`_find_device_record_by_label`、`_apply_device_record_to_form`、`_build_device_detail_message`、`_on_device_selection_changed` |
| 抢票执行 | `start_grabbing`、`_start_app_grabbing`、`_run_app_runner`、`_handle_app_run_result`、`_handle_app_run_exception`、`_app_runner_logger`、`_reset_buttons`、`stop_grabbing` |
| 定时开抢 | `_schedule_start_clicked`、`_parse_start_time_to_epoch`、`_resolve_selected_start_epoch`、`_generate_time_option_labels`、`_refresh_schedule_options`、`_schedule_tick`、`_preheat_checks`、`_schedule_cancel` |
| 帮助/授权 | `show_help`、`_start_authz_watchdog`（当前被注释，不启动） |
| 模块入口 | `main()` |

- 关键状态：`is_grabbing`、`app_env_ready` / `app_config_ready`、`app_should_stop`、`appium_running` / `appium_pid` / `appium_process`、日志过滤器、定时任务句柄
- 可选导入：`APPIUM_AVAILABLE`（缺依赖时降级为提示而非崩溃）

---

## 2. 授权校验 `damai/`

> 网页模式核心（`concert.py` / `config.py` / `damai.py` / `requirements.txt`）已随网页模式一并删除。

### 2.1 `damai/authz.py` — 授权校验（轻量混淆）
- `AuthorizationError(Exception)`
- `_unfuse(parts)`：字符串分片拼接（混淆 OWNER/REPO 常量）
- 常量：`OWNER="10000ge10000"`、`REPO="damai-ticket-assistant"`、`REPO_ID_LOCK=1059334334`
- `@dataclass AuthzPayload(exp, repo_id, nonce)`
- 网络：`_http_get(url, timeout=5)`（标准库 urllib）、`_fetch_repo_id`、`_fetch_latest_release_body`
- 解析：`_extract_authz_token(body)`（从 Release body 找 `AUTHZ:<BASE64>` → JSON）、`_check_exp`
- 对外：`ensure_authorized()`、`block_if_unauthorized_with_ui()`（Tk 弹窗 + `os._exit(1)`）
- 说明：该模块与抢票模式无关，GUI 中的调用目前均被注释，暂未启用

### 2.2 `damai/__init__.py`
- 空包标记（保留原上游注释）

---

## 3. App 模式核心 `damai_appium/`

### 3.1 `damai_appium/config.py` — 配置模型与校验
- 工具函数
  - `_strip_jsonc(content)`：剥离 `//` 与 `/* */` 注释
  - `_normalise_server_url(url)`：补全 `http://`
  - `_clean_users(users)`：清理空白/None 观演人
  - `_format_validation_errors(exc)`：pydantic 错误格式化
  - `_resolve_config_path(path)`：优先 `config.jsonc`，其次 `config.json`
- 异常
  - `ConfigValidationError(errors, message="配置校验失败")`
- Pydantic 模型
  - `DeviceOverrideModel`：单设备覆写（`server_url`、`keyword`、`users`、`city`、`date`、`price`、`price_index`、`if_commit_order`、`device_caps`、`wait_timeout`、`retry_delay`），支持 camelCase 别名
  - `AppTicketConfigModel`：主配置模型（含 `devices: List[DeviceOverrideModel]`）
- 设备解析
  - `@dataclass AdbDeviceInfo`（`is_ready`、`describe`）
  - `parse_adb_devices(raw_output)`：解析 `adb devices -l` 输出
- `@dataclass AppTicketConfig`
  - 字段：`server_url`、`keyword`、`users`、`city`、`date`、`price`、`price_index`、`if_commit_order`、`device_caps`、`wait_timeout`、`retry_delay`
  - 属性：`endpoint`、`desired_capabilities`（Android/UiAutomator2 默认 caps + 用户覆盖）
  - 构造：`from_mapping`、`from_mapping_multi`（展开 `devices` 覆写）、`load`、`load_all`

### 3.2 `damai_appium/runner.py` — 抢票运行器（核心）
- 类型别名：`Logger`、`StopSignal`、`DriverFactory`
- 枚举与异常
  - `LogLevel`：step / info / success / warning / error
  - `RunnerPhase`：init → connecting → applying_settings → selecting_city → tapping_purchase → selecting_price → selecting_quantity → confirming_purchase → selecting_users → submitting_order → completed / stopped / failed
  - `FailureReason`：user_stop / appium_connection_failed / flow_failure / unexpected_error / max_retries_reached
  - `TicketRunnerError(RuntimeError)`、`TicketRunnerStopped(TicketRunnerError)`
- 数据结构
  - `TicketRunLogEntry`（`to_dict`）
  - `TicketRunMetrics`（`to_dict`）
  - `TicketRunReport`（`to_dict`、`dump_json`）
  - `_default_logger`
- `@dataclass DamaiAppTicketRunner(config, logger, stop_signal, driver_factory)`
  - 公共 API：`run(max_retries)`、`get_last_report()`、`export_last_report(path)`
  - 生命周期：`_execute_once`、`_create_driver`、`_apply_driver_settings`、`_cleanup_driver`
  - 流程：`_perform_ticket_flow` 及各步骤
    - `_select_city`、`_tap_purchase_button`、`_select_price`、`_select_quantity`、`_confirm_purchase`、`_select_users`、`_submit_order`
    - 加速工具：`_smart_wait_and_click`、`_ultra_fast_click`、`_ultra_batch_click`、`_tap_effort_refresh`、`_tap_continue_try`
  - 状态与诊断：`_transition_to`、`_mark_failure`、`_mark_stopped`、`_ensure_not_stopped`、`_should_stop`、`_diagnose_failure`、`_ensure_driver`
  - 日志：`_log`
- 设计要点
  - `WebDriverWait(poll_frequency=0.05)` 替代 `implicitly_wait`
  - 大量使用 `mobile: clickGesture` 坐标点击提升速度
  - 观演人多选：收集坐标批量点击

### 3.3 `damai_appium/damai_app_v2.py` — CLI 入口
- `_console_logger` / `_make_session_logger(session_label)`
- `_derive_session_label(config, index)`：生成 `device-<i>:<deviceName/udid>`
- `_parse_args()`：
  - `--config`、`--retries`(默认 3)、`--export-report`、`--start-at`、`--warmup-sec`
- 定时：`_parse_start_at_text`、`_wait_until_utc(target_utc, warmup_sec, server_url)`
- 预热自检：`_check_appium_status(server_url)`（`/status`）、`_adb_ready()`
- 报告：`_print_summary(result, report, session_label)`、`_export_reports(target, runs)`
- `main()`：加载多设备配置 → （可选）定时等待 → 逐会话执行 runner → 汇总 / 导出 → 退出码（0 全成功 / 1 有失败 / 2 配置错误）

### 3.4 `damai_appium/damai_app.py`
- 兼容包装：`from damai_appium.damai_app_v2 import main`，`__main__` 时执行

### 3.5 `damai_appium/__init__.py`
- 统一导出 `AppTicketConfig`、`ConfigValidationError`、`DamaiAppTicketRunner`、`FailureReason`、`LogLevel`、`RunnerPhase`、`TicketRunLogEntry`、`TicketRunMetrics`、`TicketRunReport`、`TicketRunnerError`、`TicketRunnerStopped`

### 3.6 配置样例与说明
- `config.jsonc`：实际配置（server_url / keyword / users / city / date / price / price_index / if_commit_order / device_caps）
- `config.example.json`：带注释的示例模板
- `config-bak.jsonc`：备份样例
- `app.md`：App 模式说明（Appium 启动参数、`--relaxed-security` 与 `mobile: clickGesture`、性能优化记录、模块化接口示例）

---

## 4. 安装器 `damai_installer/`

- `src/installer.py` — `class DamaiInstaller(tk.Tk)`：图形化一键安装
  - 配置与 UI：`load_components_config`、`create_ui`、`log`、`update_component_status`
  - 环境：`check_environment`、`startup_check_components`、`refresh_env_variables`、`find_program`、`run_command`
  - 安装：`install_all`、`_install_all_thread`、`install_component`、`_install_appium_with_fallback`（在线失败回退离线）
  - Android 环境变量：`_setup_android_env_variables`、`_manual_setup_android_env`、`_show_manual_install_dialog`
  - PATH/NPM：`add_to_user_path`、`_get_npm_global_bin_candidates`、`_ensure_npm_bin_in_process_path`、`_ensure_npm_bin_in_user_path`
  - 卸载与授权：`uninstall_all`、`_uninstall_all_thread`、`uninstall_component`、`install_pyarmor_runtime`
  - 启动主程序：`start_gui`
- `src/pyarmor_method.py` — PyArmor 代码保护（可选）
- `resources/components.json` — 组件清单（Python 3.11.6 / Node 18.18.2 / Platform Tools / pip 离线 wheels / Appium 2.5.0 + uiautomator2 2.45.1），含安装与检测命令
- `resources/requirements.txt`、`resources/pyarmor_runtime/`
- `scripts/`：`install_appium_offline.cmd`、`install_appium_online.cmd`、`setup_android_env.cmd`、`download_installers.py`
- `installer_files/`：离线安装包（python 安装器、npm 包）
- `build_installer.bat`、`installer.spec`（PyInstaller）、`verify_fixes.py`、`verify_offline_packages.bat`
- 文档：`README.md`、`COMPILE.md`、`CHANGELOG.md`（2.1.0 / 2.0.0 版本记录）、`UPDATE_REPORT.md`

---

## 5. 测试 `tests/`

- `conftest.py`：`temp_dir`、`mock_appium_driver`、`mock_time`、`mock_file_operations`、`gui_instance`、`gui_appium_ready`、`gui_appium_missing`、`sample_config(s)` 等 fixture
- `unit/test_app_config.py`：URL 规范化、JSONC 注释剥离、users 清洗、配置校验、caps 合并、类型转换、配置加载、`parse_adb_devices`
- `unit/test_app_ticket_config_validation.py`：字段规范化、非法入参用例化、别名与默认值、多设备覆写、`desired_capabilities` 覆盖、`endpoint`、路径解析
- `unit/test_cli_config_validation.py`：CLI 校验失败 / 文件缺失 / 多设备执行
- `unit/test_cli_start_at.py`：`--start-at` 定时等待调用（含过去时间立即执行）
- `unit/test_gui_dependencies.py`：`_check_cli_dependency` 成功/缺失/异常
- `unit/test_gui_device_refresh.py`：设备状态刷新分支
- `unit/test_runner_logic.py`：停止信号、`_ensure_not_stopped`、日志回退与容错、成功后停止、阶段追踪、失败阶段、`run report` 指标与失败原因、报告导出
- `integration/`：目前为空占位

---

## 6. 脚本与示例

### 6.1 `scripts/`
- `dump_current_page.py`：连接设备 dump 前台页面 UI 层级
- `verify_viewer_selector.py`：只读验证观演人选择器 XPath
- `dryrun_select_users.py`：端到端演练 `_select_users`（不提交订单）
- `roundtrip_select_users.py`：验证「未勾选 → 自动勾选」往返路径
- `app_mode_quickstart.ps1`：App 模式快速启动（ConfigPath / Retries / StartAt / WarmupSec）
- `windows/start_gui.bat`、`windows/debug_gui.bat`：Windows 启动与调试脚本

### 6.2 `examples/`
- `app_runner_demo.py`：用桩函数模拟 `DamaiAppTicketRunner` 全流程，演示 `RunnerPhase` 轨迹与运行统计

### 6.3 根目录临时脚本
- `_bench_session.py`：测量 Appium session 创建 / `update_settings` 耗时
- `_dump_home.py`：dump 大麦 App 首页结构
- `test_appium.py`：`ResolveCliCommandTests`（CLI 命令解析）
- 调试产物：`page_dump*.xml`、`_*.png`、`current_page.png`、`run-report.json`

---

## 7. 文档与上游资源

- `README.md`：项目总览、免责声明、核心功能、使用流程、扩展路线、致谢
- `docs/guides/APP_MODE_README.md`：App 模式零基础上手指南（环境、Appium、常见问题）
- `docs/setup/windows_installation.md`：Windows 安装说明
- `vendor/upstream_ticket_purchase/`：上游原始仓库快照（`damai/`、`damai_appium/`、`tests/`、README、CLAUDE.md）

---

## 8. 关键流程对照

### 8.1 App 模式执行链
```
start_gui.pyw
  └─ damai_gui.DamaiGUI
       ├─ _check_app_environment()        # 自检 node/appium/adb
       ├─ _start_appium_server()          # 启动 Appium
       ├─ _detect_connected_devices()     # adb 设备检测
       ├─ load_app_config() / 表单收集     # AppTicketConfig
       └─ _start_app_grabbing()
            └─ _run_app_runner(config, max_retries)
                 ─ DamaiAppTicketRunner.run()
                      └─ _execute_once() → _perform_ticket_flow()
                           └─ 选城市/购买/票价/数量/确认/观演人/提交
                 └─ 生成 TicketRunReport → _update_app_metrics_display / export_logs
```

### 8.2 CLI 执行链
```
python -m damai_appium.damai_app_v2 --config ... --retries N --export-report out.json [--start-at ...]
  └─ AppTicketConfig.load_all()  → 多设备会话
       └─ 每个会话：DamaiAppTicketRunner.run() → _print_summary()
            └─ _export_reports() → JSON 报告
```

---

## 9. 配置速查

- **App 模式**：`config.jsonc`（或 `.json`）
  - `server_url`（默认 `127.0.0.1:4723`）
  - `keyword`（演出/歌手关键字）
  - `users[]`（观演人姓名）
  - `city` / `date` / `price` / `price_index`（`price_index` 从 0 起，按票价升序）
  - `if_commit_order`（是否自动提交订单，建议 false）
  - `device_caps`（覆盖 Appium capabilities）
  - `devices[]`（可选，多设备覆写）
  - `wait_timeout` / `retry_delay`（可选）

---

## 10. 风险与待办（源码中显式标注）

- `damai/authz.py`：需把 `OWNER` / `REPO_ID_LOCK` 更新为真实仓库值（源码中的 `TODO`）
- `damai_appium/app.md`：票价 Text 为空串问题需靠预置 `price_index` 规避；**预约功能尚未实现**
- `README.md` 扩展路线：多设备并行、定时任务 / 自动守候、监控上报仍在规划中
- 合规提示：项目声明仅供学习研究，需遵守大麦网服务条款
