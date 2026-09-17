#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""端到端演练：在真实设备上安全调用改进后的 _select_users（不提交订单）。

验证目标：
  1. 目标观演人已勾选时，代码正确识别并跳过，不误取消勾选；
  2. 演练前后 checkbox 勾选状态一致。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from appium import webdriver
from appium.options.common.base import AppiumOptions
from appium.webdriver.common.appiumby import AppiumBy
from selenium.webdriver.support.wait import WebDriverWait

from damai_appium import AppTicketConfig, DamaiAppTicketRunner, LogLevel

UDID = "481QFFEA228TR"
SERVER = "http://127.0.0.1:4723"


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


def _read_checked(driver: Any) -> Optional[str]:
    try:
        cb = driver.find_element(AppiumBy.ID, "checkbox")
        return cb.get_attribute("checked")
    except Exception as exc:  # noqa: BLE001
        print("读取勾选状态失败:", exc)
        return None


def main() -> int:
    config = AppTicketConfig(
        server_url="127.0.0.1:4723",
        keyword="欢子",
        users=["姚瑜"],
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
        before = _read_checked(driver)
        print(f"演练前 checkbox checked = {before}")

        print(">>> 调用 _select_users(['姚瑜']) ...")
        runner._select_users(["姚瑜"])

        after = _read_checked(driver)
        print(f"演练后 checkbox checked = {after}")

        if after is not None and before is not None and after == before:
            print("✅ 勾选状态未改变（已勾选 -> 正确跳过，未误取消）")
        else:
            print("⚠️ 勾选状态发生变化，请人工确认页面！")
    finally:
        driver.quit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
