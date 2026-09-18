#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""逐阶段耗时测量：演出详情页 -> 可提交订单。

用于定位「流程慢在哪」，为提速提供依据（目标：压缩到秒级/亚秒级）。
不改动业务流程，仅在最外层记录每步墙钟时间。

用法：
    python tools/time_stages.py --serial <设备> --price-index 3 --users 姚瑜
    python tools/time_stages.py --serial <设备> --repeat 3
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from typing import List, Optional, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import adb_drive as ad  # noqa: E402

DUMP = os.path.join(ROOT, "android", "dist", "_timing.xml")


class Timer:
    def __init__(self) -> None:
        self.rows: List[Tuple[str, float]] = []
        self.t0 = time.time()
        self._mark = self.t0

    def lap(self, label: str) -> float:
        now = time.time()
        dt = now - self._mark
        self._mark = now
        self.rows.append((label, dt))
        print(f"  {dt*1000:8.0f} ms  {label}")
        return dt

    def total(self) -> float:
        return time.time() - self.t0

    def report(self) -> None:
        print()
        print("=" * 56)
        print(f"{'阶段':<34}{'耗时':>10}{'占比':>10}")
        print("-" * 56)
        tot = sum(d for _, d in self.rows)
        for label, d in self.rows:
            print(f"{label:<34}{d*1000:8.0f}ms{(d/tot*100):9.1f}%")
        print("-" * 56)
        print(f"{'合计':<34}{tot*1000:8.0f}ms")


def run_once(serial: str, price_index: int, users: List[str]) -> Timer:
    d = ad.Driver(serial)
    t = Timer()

    # 确保从桌面/大麦任意页开始
    d.adb("shell", "input", "keyevent", "KEYCODE_HOME")
    time.sleep(1.0)
    d.launch_damai()
    t.lap("启动大麦到首页")

    # 进入详情页
    d.dump(DUMP)
    root = d._load(DUMP)
    card = None
    for n in root.iter():
        if n.get("resource-id") != "cn.damai:id/pioneer_homepage_item_container":
            continue
        if any("张韶涵" in (c.get("text") or "") for c in n.iter()):
            card = n
            break
    if card is None:
        raise SystemExit("未找到目标演出卡片")
    x, y = d._center(card)
    d.tap(x, y)
    time.sleep(7)   # 详情页加载（网络）
    t.lap("首页 → 详情页（含网络加载）")

    # 购买入口
    ok = d.tap_by_id(ad.PURCHASE_BAR, DUMP)
    t.lap("dump + 点击购买入口")
    time.sleep(3)
    t.lap("固定等待页面响应")

    # 弹窗
    closed = d.dismiss_dialogs(DUMP)
    t.lap(f"关闭弹窗({closed or '无'})")
    time.sleep(2)
    t.lap("固定等待")

    # 等票档页
    for _ in range(6):
        if d.verify_selectors(DUMP)["price_container"]:
            break
        d.dismiss_dialogs(DUMP)
        time.sleep(1.5)
    t.lap("等待票档容器出现")

    # 选票档
    items = d.price_items(DUMP, stable=True)
    t.lap(f"取票档坐标(stable, {len(items)}项)")
    x, y, _ = items[price_index]
    d.tap(x, y)
    time.sleep(2)
    t.lap("点击票档 + 固定等待")

    # 确定
    d.tap_by_id(ad.CONFIRM_BTN, DUMP)
    time.sleep(4)
    d.dismiss_dialogs(DUMP)
    time.sleep(2)
    t.lap("点击确定 + 等待确认页")

    # 观演人
    missing = d.select_viewers(users, DUMP)
    t.lap(f"勾选观演人 {users} (missing={missing})")

    # 提交前状态
    fg = d.foreground()
    t.lap(f"读取前台({fg.split('/')[-1]})")
    return t


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="逐阶段耗时测量（详情页 → 可提交订单）")
    ap.add_argument("--serial", required=True)
    ap.add_argument("--price-index", type=int, default=3)
    ap.add_argument("--users", default="姚瑜")
    ap.add_argument("--repeat", type=int, default=1, help="重复次数（取最后一次报告）")
    args = ap.parse_args(argv)

    users = [u.strip() for u in args.users.split(",") if u.strip()]
    last: Optional[Timer] = None
    for i in range(args.repeat):
        print("=" * 56)
        print(f"第 {i+1}/{args.repeat} 次")
        print("=" * 56)
        last = run_once(args.serial, args.price_index, users)
        # 回到桌面便于下次从首页开始
        ad.Driver(args.serial).adb("shell", "input", "keyevent", "KEYCODE_HOME")
        time.sleep(1.0)

    assert last is not None
    last.report()
    print(f"\n端到端总耗时: {last.total()*1000:.0f} ms")
    print("注意: 未提交订单。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
