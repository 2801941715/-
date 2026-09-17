#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
连接已连接的手机，导出当前前台页面 UI 层级（用于分析选择观影人页面结构）。
用法：
    python scripts/dump_current_page.py [输出文件.xml]
默认输出到项目根目录 page_dump.xml
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any, Dict

from appium import webdriver
from appium.options.common.base import AppiumOptions

UDID = "481QFFEA228TR"
SERVER = "http://127.0.0.1:4723"
PKG = "cn.damai"
ACTIVITY = "cn.damai.ultron.view.activity.DmOrderActivity"


def _current_focus() -> str:
    """通过 adb 获取当前前台 window，用于校验连接是否停留在目标页。"""
    try:
        import subprocess
        out = subprocess.run(
            ["adb", "-s", UDID, "shell", "dumpsys window | grep mCurrentFocus"],
            capture_output=True, text=True, timeout=10,
        ).stdout.strip()
        return out
    except Exception:
        return ""


def build_caps() -> Dict[str, Any]:
    return {
        "platformName": "Android",
        "appium:udid": UDID,
        "appium:deviceName": "MEIZU_21_Pro",
        "appium:automationName": "UiAutomator2",
        "appium:appPackage": PKG,
        "appium:appActivity": ACTIVITY,
        "appium:noReset": True,
        "appium:dontStopAppOnReset": True,
        "appium:skipUnlock": True,
        "appium:shouldTerminateApp": False,
        "appium:newCommandTimeout": 120,
    }


def main() -> int:
    out_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("page_dump.xml")

    print("当前前台窗口:", _current_focus())

    options = AppiumOptions()
    options.load_capabilities(build_caps())

    driver = webdriver.Remote(SERVER, options=options)
    try:
        time.sleep(0.5)
        print("当前窗口矩形:", driver.get_window_rect())
        source = driver.page_source
        out_path.write_text(source, encoding="utf-8")
        print(f"✅ 页面 UI 层级已导出: {out_path.resolve()}（{len(source)} 字符）")
        # 统计节点数量，便于确认抓取完整
        print(f"节点数量: {source.count('<node')}")
    finally:
        driver.quit()

    return 0


if __name__ == "__main__":
    sys.exit(main())
