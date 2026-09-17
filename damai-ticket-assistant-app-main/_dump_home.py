# -*- coding: utf-8 -*-
"""临时脚本：dump 大麦 App 当前页面结构（用于导航到详情页）"""
import re
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
}

driver = webdriver.Remote(
    command_executor="http://127.0.0.1:4723",
    options=UiAutomator2Options().load_capabilities(CAPS),
)
try:
    src = driver.page_source
    print("PAGE_SOURCE_LEN:", len(src))
    texts = re.findall(r'text="([^"]+)"', src)
    descs = re.findall(r'content-desc="([^"]+)"', src)
    rids = re.findall(r'resource-id="([^"]+)"', src)
    print("--- texts ---")
    for t in dict.fromkeys(texts):
        print(repr(t))
    print("--- descs ---")
    for d in dict.fromkeys(descs):
        print(repr(d))
    print("--- rids (unique) ---")
    for r in dict.fromkeys(rids):
        print(r)
finally:
    driver.quit()
