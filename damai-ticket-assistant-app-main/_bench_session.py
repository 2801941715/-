# -*- coding: utf-8 -*-
"""临时脚本：测量 Appium session 创建与 update_settings 耗时"""
import time
from appium import webdriver
from appium.options.android import UiAutomator2Options

CAPS = {
    "platformName": "Android",
    "automationName": "UiAutomator2",
    "appPackage": "cn.damai",
    "appActivity": ".launcher.splash.SplashMainActivity",
    "noReset": True,
    "skipUnlock": True,
    "skipDeviceInitialization": True,
    "skipServerInstallation": True,
    "skipLogcatCapture": True,
    "autoLaunch": False,
    "newCommandTimeout": 6000,
    "unicodeKeyboard": True,
    "resetKeyboard": True,
    "ignoreHiddenApiPolicyError": True,
    "disableWindowAnimation": True,
}

t0 = time.time()
driver = webdriver.Remote(
    command_executor="http://127.0.0.1:4723",
    options=UiAutomator2Options().load_capabilities(CAPS),
)
t1 = time.time()
print(f"session 创建耗时: {t1 - t0:.2f}s")

try:
    driver.update_settings(
        {
            "waitForIdleTimeout": 0,
            "actionAcknowledgmentTimeout": 0,
            "keyInjectionDelay": 0,
            "waitForSelectorTimeout": 300,
            "ignoreUnimportantViews": False,
            "allowInvisibleElements": True,
            "enableNotificationListener": False,
        }
    )
    t2 = time.time()
    print(f"update_settings 耗时: {t2 - t1:.2f}s")

    # 测试一次元素查找（详情页的购买/预约按钮区域）
    from appium.webdriver.common.appiumby import AppiumBy
    t3 = time.time()
    els = driver.find_elements(AppiumBy.ID, "cn.damai:id/trade_project_detail_purchase_status_bar_container_fl")
    t4 = time.time()
    print(f"find_elements 耗时: {t4 - t3:.3f}s, 命中 {len(els)} 个")
finally:
    t5 = time.time()
    driver.quit()
    t6 = time.time()
    print(f"driver.quit 耗时: {t6 - t5:.2f}s")
