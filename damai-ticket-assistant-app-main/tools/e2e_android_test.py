#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""大麦抢票助手（安卓版）端到端验收测试。

在已连接的 Android 设备/模拟器上自动完成一套验收：安装确认、远程调试通道、
完整抢票流程、多观演人选择、幂等性、停止信号、异常路径与页面 dump 格式。

测试需要一个「大麦替身」App（android/mockapp），它复刻了真实大麦 App 的
view-id 与页面流转，用于在无法安装真实大麦 App 的环境下验证选择器与流程。

用法：
    # 1. 构建并安装两个 APK
    pwsh -File android/build.ps1
    pwsh -File android/build.ps1 -AppDirName mockapp -ApkName damai-mock
    adb install -r android/dist/damai-assistant-debug.apk
    adb install -r android/dist/damai-mock.apk

    # 2. 开启无障碍（首次或重装后）
    adb shell settings put secure enabled_accessibility_services \
        com.damai.assistant/com.damai.assistant.DamaiAutomationService
    adb shell settings put secure accessibility_enabled 1

    # 3. 运行验收
    python tools/e2e_android_test.py
    python tools/e2e_android_test.py --report out.txt   # 保存报告

退出码：0 = 全部通过；1 = 有失败用例。
"""

from __future__ import annotations

import argparse
import io
import json
import os
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(HERE)
REMOTE = os.path.join(HERE, "damai_remote.py")

ASSISTANT_PKG = "com.damai.assistant"
MOCK_PKG = "cn.damai"
MOCK_ACTIVITY = "cn.damai/.MainActivity"
DUMP_FILE = os.path.join(PROJECT_ROOT, "android", "dist", "_e2e_dump.xml")

# 终态阶段（用于判断流程是否结束）
TERMINAL_PHASES = ("completed", "failed", "stopped")


class Harness:
    def __init__(self, serial: str, timeout: float) -> None:
        self.serial = serial
        self.timeout = timeout
        self.results: List[Tuple[str, bool]] = []

    # ---------------- 基础命令 ----------------
    def adb(self, *args: str) -> str:
        proc = subprocess.run(
            [self._adb_path(), "-s", self.serial, *args],
            capture_output=True, encoding="utf-8", errors="replace",
        )
        return proc.stdout or ""

    @staticmethod
    def _adb_path() -> str:
        from shutil import which
        found = which("adb")
        if found:
            return found
        for env in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
            root = os.environ.get(env)
            if root:
                cand = os.path.join(root, "platform-tools", "adb.exe")
                if os.path.exists(cand):
                    return cand
        cand = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Android", "Sdk",
                            "platform-tools", "adb.exe")
        if os.path.exists(cand):
            return cand
        raise SystemExit("未找到 adb")

    def remote(self, *args: str) -> str:
        proc = subprocess.run(
            [sys.executable, REMOTE, "--device", self.serial, *args],
            capture_output=True, encoding="utf-8", errors="replace",
        )
        return proc.stdout or ""

    def remote_json(self, *args: str) -> Dict[str, Any]:
        text = self.remote(*args)
        start = text.find("{")
        while start != -1:
            try:
                return json.loads(text[start:])
            except Exception:
                start = text.find("{", start + 1)
        return {}

    # ---------------- 断言 ----------------
    def check(self, name: str, ok: bool, detail: str = "") -> None:
        self.results.append((name, ok))
        line = f"{'PASS' if ok else 'FAIL'}  {name}"
        if detail and not ok:
            line += f"   [{detail}]"
        print(line)
        self._log(line)

    _log_stream: Optional[io.TextIOWrapper] = None

    def _log(self, line: str) -> None:
        if Harness._log_stream is not None:
            Harness._log_stream.write(line + "\n")

    def section(self, title: str) -> None:
        print("\n" + "=" * 62)
        print(title)
        print("=" * 62)
        self._log("\n" + "=" * 62)
        self._log(title)
        self._log("=" * 62)

    # ---------------- 场景辅助 ----------------
    def reset_mock(self, city: str = "郑州") -> None:
        self.adb("shell", "am", "force-stop", MOCK_PKG)
        self.adb("shell", "am", "start", "-n", MOCK_ACTIVITY, "--es", "city", city)
        time.sleep(2.2)
        self.adb("logcat", "-c")

    def wait_done(self) -> Dict[str, Any]:
        deadline = time.time() + self.timeout
        status: Dict[str, Any] = {}
        while time.time() < deadline:
            status = self.remote_json("status")
            if status.get("running") is False and status.get("phase") in TERMINAL_PHASES:
                return status
            time.sleep(0.4)
        return status

    def start_and_wait(self) -> Dict[str, Any]:
        self.remote("start")
        return self.wait_done()

    def viewers(self) -> Dict[str, bool]:
        root = ET.parse(DUMP_FILE).getroot()
        out: Dict[str, bool] = {}
        for row in root.iter("android.widget.LinearLayout"):
            if row.get("resource-id") != "cn.damai:id/layout_main":
                continue
            name = checked = None
            for ch in row.iter():
                if ch.get("resource-id") == "cn.damai:id/text_name":
                    name = ch.get("text")
                if ch.get("resource-id") == "cn.damai:id/checkbox":
                    checked = (ch.get("checked") == "true")
            if name is not None:
                out[name] = bool(checked)
        return out

    def mock_log(self) -> str:
        return self.adb("logcat", "-d", "-s", "DamaiMock")

    def mock_stages(self) -> str:
        return " | ".join(
            l.split("DamaiMock:")[-1].strip()
            for l in self.mock_log().splitlines() if "DamaiMock:" in l
        )

    def screenshot(self, path: str) -> None:
        self.adb("shell", "screencap", "-p", "/sdcard/_e2e.png")
        subprocess.run([self._adb_path(), "-s", self.serial, "pull", "/sdcard/_e2e.png", path],
                       capture_output=True)


def run_suite(h: Harness, screenshot_dir: Optional[str]) -> int:
    # ---------------- A. 远程调试通道 ----------------
    h.section("A. 远程调试通道")
    doctor = h.remote("doctor")
    h.check("doctor 全部 OK", "[FAIL]" not in doctor, doctor[-200:])
    st = h.remote_json("status")
    h.check("status 可用", st.get("ok") is True)
    h.check("无障碍服务已连接", st.get("service_connected") is True)

    # ---------------- B. 完整流程 ----------------
    h.section("B. 完整流程（票价索引 3，单观演人）")
    h.reset_mock()
    h.remote("set", "--city", "郑州", "--price-index", "3", "--users", "张三",
             "--no-commit-order", "--max-retries", "1")
    st = h.start_and_wait()
    h.check("流程 completed", st.get("phase") == "completed",
            f"phase={st.get('phase')} reason={st.get('failure_reason')}")
    h.check("无失败码", st.get("failure_code") is None, str(st.get("failure_code")))
    stages = h.mock_stages()
    h.check("点击购买入口生效", "stage -> price" in stages, stages)
    h.check("票价索引 3 命中 VIP票388元", "price selected index=3" in stages, stages)
    h.check("确认购买生效", "stage -> confirm" in stages, stages)
    h.check("进入订单页", "stage -> order" in stages, stages)
    h.check("未开启自动提交时不提交", "stage -> done" not in stages, stages)
    h.remote("dump", "-o", DUMP_FILE)
    v = h.viewers()
    h.check("观演人列表可见", len(v) == 3, str(v))
    h.check("仅目标观演人被勾选",
            v.get("张三") is True and v.get("李四") is False and v.get("王五") is False, str(v))

    # ---------------- C. 自动提交 ----------------
    h.section("C. 自动提交订单")
    h.reset_mock()
    h.remote("set", "--city", "郑州", "--price-index", "0", "--users", "张三",
             "--commit-order", "--max-retries", "1")
    st = h.start_and_wait()
    stages = h.mock_stages()
    h.check("开启后走到提交完成", ("stage -> done" in stages) or ("order submitted" in stages), stages)
    h.check("流程 completed", st.get("phase") == "completed", str(st.get("phase")))

    # ---------------- D. 多观演人 ----------------
    h.section("D. 多观演人选择")
    cases = [
        ("张三, 李四", {"张三": True, "李四": True, "王五": False}),
        ("张三, 王五", {"张三": True, "李四": False, "王五": True}),
        ("李四, 王五", {"张三": False, "李四": True, "王五": True}),
        ("张三, 李四, 王五", {"张三": True, "李四": True, "王五": True}),
    ]
    for users, expect in cases:
        h.reset_mock()
        h.remote("set", "--city", "郑州", "--price-index", "0", "--users", users,
                 "--no-commit-order", "--max-retries", "1")
        st = h.start_and_wait()
        h.remote("dump", "-o", DUMP_FILE)
        got = h.viewers()
        h.check(f"多选 {users} 全部正确勾选", got == expect, f"got={got} expect={expect}")
        h.check(f"多选 {users} 流程完成", st.get("phase") == "completed", str(st.get("phase")))

    # ---------------- E. 幂等 ----------------
    h.section("E. 已勾选幂等（不误取消）")
    h.reset_mock()
    h.remote("set", "--city", "郑州", "--price-index", "0", "--users", "张三",
             "--no-commit-order", "--max-retries", "1")
    h.start_and_wait()
    h.remote("dump", "-o", DUMP_FILE)
    v1 = h.viewers()
    h.check("首次运行勾选张三", v1.get("张三") is True, str(v1))

    h.adb("logcat", "-c")
    h.start_and_wait()
    h.remote("dump", "-o", DUMP_FILE)
    v2 = h.viewers()
    clicks = h.mock_log().count("CB-click") + h.mock_log().count("ROW-click")
    h.check("二次运行未重复点击（幂等）", clicks == 0, f"clicks={clicks}")
    h.check("二次运行张三仍勾选", v2.get("张三") is True, str(v2))
    logs2 = h.remote("logs")
    h.check("二次运行记录跳过日志", "已勾选" in logs2 or "无需操作" in logs2, "no skip log")

    # ---------------- F. 停止 ----------------
    h.section("F. 停止信号")
    h.reset_mock()
    h.remote("set", "--city", "郑州", "--price-index", "3", "--users", "张三",
             "--no-commit-order", "--max-retries", "3")
    h.remote("start")
    time.sleep(0.25)
    sr = h.remote_json("stop")
    h.check("stop 被接受", sr.get("ok") is True, str(sr))
    st = h.wait_done()
    h.check("停止后不再运行", st.get("running") is False, str(st))
    h.check("阶段为 stopped / user_stop",
            st.get("phase") == "stopped" or st.get("failure_code") == "user_stop",
            f"phase={st.get('phase')} code={st.get('failure_code')}")

    # ---------------- G. 异常路径 ----------------
    h.section("G. 异常路径（无可购入口）")
    h.reset_mock()
    h.remote("set", "--city", "郑州", "--price-index", "0", "--users", "张三",
             "--commit-order", "--max-retries", "1")
    h.start_and_wait()      # 走到 done
    st = h.start_and_wait() # 在 done 页重跑
    h.check("未卡死（已结束）", st.get("running") is False, str(st))
    h.check("给出失败或完成状态",
            st.get("failure_code") is not None or st.get("phase") == "completed", str(st))

    # ---------------- H. dump 格式 ----------------
    h.section("H. 页面层级 dump")
    h.reset_mock()
    h.remote("dump", "-o", DUMP_FILE)
    txt = io.open(DUMP_FILE, encoding="utf-8").read()
    h.check("含 hierarchy 根节点", txt.startswith("<?xml") and "<hierarchy" in txt)
    try:
        ET.parse(DUMP_FILE)
        h.check("是合法 XML（层级可解析）", True)
    except Exception as exc:
        h.check("是合法 XML（层级可解析）", False, str(exc))
    h.check("包含大麦资源 id", "cn.damai:id/" in txt)
    h.check("包含 uiautomator 风格属性",
            'resource-id="' in txt and "bounds=" in txt and "clickable=" in txt)

    # ---------------- 存档 ----------------
    if screenshot_dir:
        os.makedirs(screenshot_dir, exist_ok=True)
        h.reset_mock()
        h.remote("set", "--city", "郑州", "--price-index", "3", "--users", "张三, 李四",
                 "--no-commit-order", "--max-retries", "1")
        h.start_and_wait()
        h.screenshot(os.path.join(screenshot_dir, "android_order_page.png"))

    failures = [n for n, ok in h.results if not ok]
    h.section("结果")
    print(f"总计 {len(h.results)} 项，失败 {len(failures)} 项")
    h._log(f"总计 {len(h.results)} 项，失败 {len(failures)} 项")
    for n in failures:
        print("  FAIL:", n)
        h._log("  FAIL: " + n)
    return 1 if failures else 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="大麦抢票助手（安卓版）端到端验收测试")
    parser.add_argument("--serial", help="设备序列号（多设备时指定）")
    parser.add_argument("--timeout", type=float, default=30.0, help="单个流程等待秒数")
    parser.add_argument("--report", help="把报告写入文件")
    parser.add_argument("--screenshots", help="把关键界面截图保存到该目录")
    args = parser.parse_args(argv)

    serial = args.serial
    if not serial:
        proc = subprocess.run([Harness._adb_path(), "devices"], capture_output=True,
                              encoding="utf-8", errors="replace")
        for line in (proc.stdout or "").splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 2 and parts[1] == "device":
                serial = parts[0]
                break
    if not serial:
        raise SystemExit("未检测到可用设备（adb devices 应为 device 状态）")

    h = Harness(serial, args.timeout)
    if args.report:
        Harness._log_stream = io.open(args.report, "w", encoding="utf-8")
    print(f"设备: {serial}")
    h._log(f"设备: {serial}")
    try:
        return run_suite(h, args.screenshots)
    finally:
        if Harness._log_stream is not None:
            Harness._log_stream.close()


if __name__ == "__main__":
    sys.exit(main())
