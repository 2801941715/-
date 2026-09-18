#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""真机全流程（adb 注入）：演出详情页 → 提交订单。

覆盖完整链路，并保留售罄/未开售时的「刷新」捡漏能力：

    详情页 → 点购买入口 →（弹窗）→ 票档页 → 选票档 → 确定
          → 确认订单页 → 勾选观演人 → 立即提交

刷新（默认保留，可用 --no-refresh 关闭）：
  - 购买入口缺失时：先点「努力刷新」捡漏，再重试购买入口
  - 确认购买后：若出现「努力刷新」，循环刷新并重新确认
  - 提交订单后：若出现「继续尝试」，循环关闭并重新提交

为什么用 adb 注入：实测大麦会过滤无障碍注入手势（见 tools/gesture_probe.py），
而 `adb shell input tap` 走系统输入通道、可正常驱动大麦。

安全默认：**不自动提交订单**。要真正提交需显式加 --submit。
不加 --submit 时流程停在确认订单页（观演人已勾选，可人工核对后提交）。

用法：
    # 演练到确认订单页（默认，不提交）
    python tools/real_device_dryrun.py --serial <设备> --price-index 3

    # 演练并提交订单（谨慎）
    python tools/real_device_dryrun.py --serial <设备> --price-index 3 --submit
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import xml.etree.ElementTree as ET
from typing import List, Optional, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import adb_drive as ad  # noqa: E402

DUMP = os.path.join(ROOT, "android", "dist", "_dryrun.xml")

# 复用驱动中的 Activity 常量，避免两处定义漂移
DETAIL_ACTIVITY = ad.DETAIL_ACTIVITY
SKU_ACTIVITY = ad.SKU_ACTIVITY
ORDER_ACTIVITY = ad.ORDER_ACTIVITY


class DryRun:
    def __init__(self, serial: str, keyword: str, refresh: bool = True) -> None:
        self.d = ad.Driver(serial)
        self.keyword = keyword
        self.refresh = refresh
        self.fg = ""

    def step(self, msg: str) -> None:
        print("  " + msg)

    # ---------------- 导航 ----------------
    def ensure_detail_page(self) -> bool:
        """若不在详情页，则在首页点开含关键词的演出卡片。"""
        # 确保大麦已启动（桌面/其它应用时先拉起）
        self.fg = self.d.launch_damai()
        if DETAIL_ACTIVITY in self.fg:
            return True
        self.d.dump(DUMP)
        root = self.d._load(DUMP)
        card = None
        for n in root.iter():
            if n.get("resource-id") != "cn.damai:id/pioneer_homepage_item_container":
                continue
            if any(self.keyword in (c.get("text") or "") for c in n.iter()):
                card = n
                break
        if card is None:
            # 兜底：任一含关键词的节点，用其父级区域近似点击
            for n in root.iter():
                if self.keyword in (n.get("text") or ""):
                    card = n
                    break
        if card is None:
            return False
        x, y = self.d._center(card)
        self.d.tap(x, y)
        self.step(f"已点击演出卡片 ({x},{y})")
        time.sleep(7)
        self.fg = self.d.foreground()
        return DETAIL_ACTIVITY in self.fg

    # ---------------- 流程 ----------------
    def to_sku_page(self) -> bool:
        if not self.d.tap_by_id(ad.PURCHASE_BAR, DUMP):
            # 购买入口缺失：可能是售罄/未开售，先点「努力刷新」捡漏
            if self.refresh:
                n = self.d.tap_effort_refresh(12, 0.6, DUMP)
                if n:
                    self.step(f"未找到购买入口，已点「努力刷新」{n} 次")
                    if not self.d.tap_by_id(ad.PURCHASE_BAR, DUMP):
                        return False
                else:
                    self.step("未找到购买入口，且无「努力刷新」按钮")
                    return False
            else:
                return False
        self.step("已点击购买入口")
        time.sleep(3)
        for _ in range(2):
            closed = self.d.dismiss_dialogs(DUMP)
            if closed:
                self.step(f"关闭弹窗: {closed}")
            time.sleep(1.5)
        for _ in range(6):
            if self.d.verify_selectors(DUMP)["price_container"]:
                return True
            self.d.dismiss_dialogs(DUMP)
            time.sleep(1.5)
        return False

    def pick_price(self, index: int) -> Optional[Tuple[int, int, str]]:
        items = self.d.price_items(DUMP)
        self.step(f"票档共 {len(items)} 个")
        if not items:
            return None
        if not (0 <= index < len(items)):
            self.step(f"price_index={index} 越界（0..{len(items)-1}）")
            return None
        x, y, hint = items[index]
        self.d.tap(x, y)
        time.sleep(2)
        return x, y, hint

    def confirm(self) -> bool:
        """票档页点「确定」，并用「努力刷新」兜底重试（售罄/库存不足场景）。"""
        if not self.d.tap_by_id(ad.CONFIRM_BTN, DUMP):
            return False
        self.step("已点击「确定」")
        time.sleep(4)
        self.d.dismiss_dialogs(DUMP)
        time.sleep(2)

        # 售罄/库存不足时可能出现「努力刷新」：循环刷新并重新确认
        if self.refresh:
            for _ in range(8):
                if self.d.tap_effort_refresh(1, 0.6, DUMP) == 0:
                    break
                self.step("出现「努力刷新」，刷新后重新确认")
                time.sleep(0.3)
                self.d.tap_by_id(ad.CONFIRM_BTN, DUMP)
                time.sleep(2)
                self.d.dismiss_dialogs(DUMP)
        return True

    def on_order_page(self) -> bool:
        return ad.ORDER_ACTIVITY in self.d.foreground()

    def select_viewers(self, names) -> bool:
        if not names:
            self.step("未指定观演人，跳过勾选")
            return True
        missing = self.d.select_viewers(names, DUMP)
        got = ", ".join(f"{'[x]' if c else '[ ]'} {n}" for n, c, _, _ in self.d.viewers(DUMP))
        self.step(f"观演人状态: {got}")
        if missing:
            self.step(f"未找到观演人: {missing}")
            return False
        return True

    def submit(self) -> bool:
        """提交订单；若弹出「继续尝试」则循环重试。"""
        if not self.d.tap_submit(DUMP):
            return False
        self.step("已点击「立即提交」")
        time.sleep(4)
        self.d.dismiss_dialogs(DUMP)
        for _ in range(5):
            if self.d.tap_continue_try(1, 0.5, DUMP) == 0:
                break
            self.step("出现「继续尝试」，重新提交")
            time.sleep(0.3)
            self.d.tap_submit(DUMP)
            time.sleep(2)
            self.d.dismiss_dialogs(DUMP)
        return True


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="真机全流程（adb 注入）：演出详情页 → 提交订单",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("--serial", required=True)
    ap.add_argument("--keyword", default="张韶涵", help="首页用于定位演出卡片的关键词")
    ap.add_argument("--price-index", type=int, default=3, help="票价索引（从 0 开始）")
    ap.add_argument("--users", default="", help="观演人姓名，逗号分隔（留空则跳过勾选）")
    ap.add_argument("--submit", action="store_true", help="真正提交订单（默认不提交，停在确认页）")
    ap.add_argument("--no-refresh", dest="refresh", action="store_false", default=True,
                    help="关闭「努力刷新 / 继续尝试」重试（默认开启）")
    args = ap.parse_args(argv)

    r = DryRun(args.serial, args.keyword, refresh=args.refresh)
    users = [u.strip() for u in args.users.split(",") if u.strip()]

    print("=" * 62)
    print(f"真机全流程：关键词={args.keyword!r} price_index={args.price_index}")
    print(f"刷新重试: {'开启' if args.refresh else '关闭'}    提交订单: {'是' if args.submit else '否（停在确认页）'}")
    if users:
        print(f"观演人: {users}")
    print("=" * 62)
    r.step(f"起始前台: {r.d.foreground()}")

    if not r.ensure_detail_page():
        print("\n结果: 未能进入演出详情页 FAIL")
        return 1
    r.step(f"详情页: {r.d.foreground()}")

    # 提前清一次弹窗（票务须知 / 实名制提示）
    closed = r.d.dismiss_dialogs(DUMP)
    if closed:
        r.step(f"关闭弹窗: {closed}")

    if not r.to_sku_page():
        print("\n结果: 未能进入票档页 FAIL")
        return 1
    r.step(f"票档页: {r.d.foreground()}")

    picked = r.pick_price(args.price_index)
    if picked is None:
        print("\n结果: 未能选中票档 FAIL")
        return 1
    r.step(f"已选 index={args.price_index} center=({picked[0]},{picked[1]}) {picked[2]}")

    if not r.confirm():
        print("\n结果: 未能点击确定 FAIL")
        return 1

    if not r.on_order_page():
        fg = r.d.foreground()
        print(f"\n结果: 未到达确认订单页（{fg}）FAIL")
        return 1
    r.step(f"确认订单页: {r.d.foreground()}")

    # 勾选观演人
    if not r.select_viewers(users):
        print("\n结果: 观演人勾选失败 FAIL")
        return 1

    if not args.submit:
        print()
        print("结果: 已到达确认订单页并完成勾选 OK")
        print("注意: 未提交订单（如需提交请加 --submit）。")
        return 0

    # 提交订单
    if not r.submit():
        print("\n结果: 未能提交订单 FAIL")
        return 1
    fg = r.d.foreground()
    r.step(f"提交后前台: {fg}")
    print()
    print("结果: 已提交订单 OK" if ad.ORDER_ACTIVITY not in fg else f"结果: 仍停在订单页（{fg}）FAIL")
    return 0 if ad.ORDER_ACTIVITY not in fg else 1


if __name__ == "__main__":
    sys.exit(main())
