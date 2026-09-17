#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""只读验证：确认观演人选择器的 XPath 在真实页面上能命中（不做任何点击）。"""

from __future__ import annotations

import sys
from typing import Any, Dict

from appium import webdriver
from appium.options.common.base import AppiumOptions
from appium.webdriver.common.appiumby import AppiumBy

UDID = "481QFFEA228TR"
SERVER = "http://127.0.0.1:4723"


def build_caps() -> Dict[str, Any]:
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


def main() -> int:
    options = AppiumOptions()
    options.load_capabilities(build_caps())
    driver = webdriver.Remote(SERVER, options=options)
    try:
        # 1) 观演人列表容器
        try:
            c = driver.find_element(AppiumBy.ID, "recycler_main")
            print("✅ 容器 recycler_main rect=", c.rect, "clickable=", c.get_attribute("clickable"))
        except Exception as exc:  # noqa: BLE001
            print("❌ 容器 recycler_main:", exc)

        # 2) 观演人条目（按姓名 resource-id 精确匹配）与内部 CheckBox 状态
        for name in ["姚瑜"]:
            # 2a) 可点击的内层条目（优先点击目标）
            try:
                clickable_item = driver.find_element(
                    AppiumBy.XPATH,
                    f'//*[@resource-id="cn.damai:id/layout_main" and @clickable="true"'
                    f' and .//*[@resource-id="cn.damai:id/text_name" and contains(@text,"{name}")]]',
                )
                print(f"✅ 可点击条目({name}) rect=", clickable_item.rect)
            except Exception as exc:  # noqa: BLE001
                print(f"❌ 可点击条目({name}):", exc)

            # 2b) 任意包含姓名的条目（兜底），读取内部 CheckBox 状态
            try:
                item = driver.find_element(
                    AppiumBy.XPATH,
                    f'//*[@resource-id="cn.damai:id/layout_main"'
                    f' and .//*[@resource-id="cn.damai:id/text_name" and contains(@text,"{name}")]]',
                )
                try:
                    cb = item.find_element(AppiumBy.ID, "checkbox")
                    cx = cb.rect["x"] + cb.rect["width"] // 2
                    cy = cb.rect["y"] + cb.rect["height"] // 2
                    print(f"✅ CheckBox rect={cb.rect} checked={cb.get_attribute('checked')} "
                          f"clickable={cb.get_attribute('clickable')} 点击中心=({cx},{cy})")
                except Exception as exc:  # noqa: BLE001
                    print("   ❌ 条目内 checkbox:", exc)
            except Exception as exc:  # noqa: BLE001
                print(f"❌ 观演人条目({name}):", exc)

        # 3) 页面上所有观演人条目数量（确认是否多观演人）
        try:
            items = driver.find_elements(
                AppiumBy.XPATH, '//*[@resource-id="cn.damai:id/layout_main"]'
            )
            print(f"✅ 页面上观演人条目数量: {len(items)}")
            for it in items[:5]:
                try:
                    nm = it.find_element(AppiumBy.ID, "text_name").get_attribute("text")
                    cb = it.find_element(AppiumBy.ID, "checkbox")
                    print(f"   - {nm}  checked={cb.get_attribute('checked')}")
                except Exception:  # noqa: BLE001
                    pass
        except Exception as exc:  # noqa: BLE001
            print("❌ 条目数量查询:", exc)
    finally:
        driver.quit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
