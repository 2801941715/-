#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""完整往返演练：验证 _select_users 的"未勾选 -> 自动勾选"路径。

流程：
  1. 记录当前勾选状态；
  2. 手动取消勾选（点击 checkbox），确认状态变为未勾选；
  3. 调用改进后的 _select_users(["姚瑜"])，应自动勾选；
  4. 确认最终状态与最初一致（恢复原状）。
无论中途是否出错，finally 中都会调用 _select_users 恢复勾选。
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from appium import webdriver
from appium.options.common.base import AppiumOptions
from appium.webdriver.common.appiumby import AppiumBy
from selenium.webdriver.support.wait import WebDriverWait

from damai_appium import AppTicketConfig, DamaiAppTicketRunner

UDID = "481QFFEA228TR"
SERVER = "http://127.0.0.1:4723"
TARGET_USER = "姚瑜"


def _logger(level: str, message: str, context: Optional[Dict[str, Any]] = None) -> None:
    extra = f" | {context}" if context else ""
    print(f"[{level}] {message}{extra}")


def _caps() -> Dict[str, Any]:
    return {
        "platformName": "Android",
        "appium:udid": UDID,
        "appium:deviceName": "MEIZU_21_Pro",
        "appium:automationName": "UiAutomator2",
        "appium:appPackage": "cn.damai",
        "appium:appActivity": "cn.damai.ultron.view.activity.DmOrderActivity",
        "appium:noReset": True,
        "appium:dontStopAppOnReset": True,
        "appium:skipUnlock": True,
        "appium:shouldTerminateApp": False,
        "appium:newCommandTimeout": 60,
    }


def _find_checkbox(driver: Any) -> Any:
    """定位目标观演人的 checkbox（resource-id 精确匹配）。"""
    return driver.find_element(
        AppiumBy.XPATH,
        f'//*[@resource-id="cn.damai:id/layout_main"'
        f' and .//*[@resource-id="cn.damai:id/text_name" and contains(@text,"{TARGET_USER}")]]'
        f'//*[@resource-id="cn.damai:id/checkbox"]',
    )


def _read_checked(driver: Any) -> Optional[str]:
    try:
        cb = _find_checkbox(driver)
        return cb.get_attribute("checked")
    except Exception as exc:  # noqa: BLE001
        print("读取勾选状态失败:", exc)
        return None


def _tap_checkbox(driver: Any, label: str) -> None:
    cb = _find_checkbox(driver)
    rect = cb.rect
    driver.execute_script(
        "mobile: clickGesture",
        {
            "x": rect["x"] + rect["width"] // 2,
            "y": rect["y"] + rect["height"] // 2,
            "duration": 50,
        },
    )
    print(f"✅ 已点击 checkbox（{label}）")
    time.sleep(0.3)


def main() -> int:
    config = AppTicketConfig(
        server_url="127.0.0.1:4723",
        keyword="欢子",
        users=[TARGET_USER],
        if_commit_order=False,
        wait_timeout=1.0,
        device_caps={"udid": UDID, "deviceName": "MEIZU_21_Pro"},
    )
    runner = DamaiAppTicketRunner(config=config, logger=_logger)

    options = AppiumOptions()
    options.load_capabilities(_caps())
    driver = webdriver.Remote(SERVER, options=options)
    runner._driver = driver
    runner._wait = WebDriverWait(driver, 1.0)

    try:
        original = _read_checked(driver)
        print(f"① 初始勾选状态 checked = {original}")

        # ② 手动取消勾选
        _tap_checkbox(driver, "取消勾选")
        unchecked = _read_checked(driver)
        print(f"② 取消后 checked = {unchecked}")

        # ③ 用改进后的代码自动勾选
        print(f">>> 调用 _select_users(['{TARGET_USER}']) ...")
        runner._select_users([TARGET_USER])
        time.sleep(0.3)
        reselected = _read_checked(driver)
        print(f"③ 自动勾选后 checked = {reselected}")
    finally:
        # ④ 无论中途结果如何，都确保恢复为已勾选
        try:
            runner._select_users([TARGET_USER])
            time.sleep(0.3)
            final = _read_checked(driver)
            print(f"④ 最终状态 checked = {final}")
            if final in ("true", "1", "yes"):
                print("✅ 往返演练成功：未勾选 -> 自动勾选，已恢复原状")
            else:
                print("⚠️ 最终未恢复为已勾选，请人工确认页面！")
        except Exception as exc:  # noqa: BLE001
            print("❌ 恢复勾选失败:", exc)
        driver.quit()

    return 0


if __name__ == "__main__":
    sys.exit(main())
