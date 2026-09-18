#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""预选优化版：详情页 -> 可提交订单（利用大麦的实名观演人预选）。

前提（真实抢票场景）：
  - 观演人已在「抢票攻略」中预选 → 确认订单页会自动勾选，**无需再点**
  - 票档按 price_index 自动选中（可用 --skip-price 完全跳过选档）

相比 fast_run.py 的差异：
  1. 跳过观演人勾选（预选已生效）
  2. 可选 --skip-price：票档页直接点「确定」（票档由 App 默认选中）
  3. 严格轮询、常驻 adb shell、屏幕感知稳定等待全部保留

用法：
    python tools/preset_run.py --serial <设备>                       # 全自动（跳过观演人）
    python tools/preset_run.py --serial <设备> --skip-price          # 连票价也不选
    python tools/preset_run.py --serial <设备> --repeat 5
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import statistics
import subprocess
import sys
import time
from typing import List, Optional, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import fast_run as fr  # noqa: E402

ADB = fr.ADB


class PresetRunner(fr.FastRunner):
    """在 FastRunner 基础上，支持跳过「已预选」的步骤。"""

    def run(self, price_index: int, users: List[str], keyword: str = "张韶涵",
            skip_price: bool = False, verify_users: bool = False) -> bool:
        self.start()

        # --- 0) 确保在详情页 ---
        xml = self.b.dump()
        if self.find(xml, fr.T_PURCHASE) is None:
            if not self._enter_detail_page(xml, keyword):
                print("  未能进入演出详情页")
                return False
            self.lap("从首页进入演出详情页")
        self.detail_ready = time.perf_counter()

        # --- 1) 点购买入口 ---
        xml = self.b.dump()
        bar = self.find(xml, fr.T_PURCHASE)
        x, y = self._center(bar)
        self.tap(x, y)
        self.lap("点击购买入口")

        # --- 2) 等票档页就绪 ---
        ok, n = self.wait_token(fr.T_PRICE, timeout=12.0)
        if not ok:
            print("  票档页未就绪")
            return False
        self.lap(f"票档页就绪(轮询{n}次)")

        # --- 3) 弹窗（有则清，一次判定） ---
        self.clear_dialogs()
        self.lap("清理弹窗")

        # --- 4) 票档 ---
        if skip_price:
            self.lap("跳过选票档（由 App 默认选中）")
        else:
            xml = self.wait_price_ready(timeout=3.0, samples=1)
            self.lap("等票档屏内可用")
            container = self.find(xml, fr.T_PRICE)
            items = [c for c in container if c.get("clickable") == "true"]
            if not (0 <= price_index < len(items)):
                print(f"  price_index 越界")
                return False
            x, y = self._center(items[price_index])
            self.tap(x, y)
            self.lap(f"选票档 index={price_index}")
            if not self._price_applied(timeout=1.2):
                return False
            self.lap("票档生效")

        # --- 5) 点确定 ---
        xml = self.b.dump()
        btn = self.find(xml, fr.T_CONFIRM)
        if btn is None:
            ok, n = self.wait_token(fr.T_CONFIRM, timeout=3.0)
            if not ok:
                return False
            btn = self.find(self.b.dump(), fr.T_CONFIRM)
        x, y = self._center(btn)
        self.tap(x, y)
        self.lap("点击确定")

        # --- 6) 等确认订单页 ---
        ok, n = self.wait_token(fr.T_ORDER, timeout=12.0)
        if not ok:
            print("  确认订单页未就绪")
            return False
        self.lap(f"确认订单页就绪(轮询{n}次)")
        self.clear_dialogs()
        self.lap("清理弹窗")

        # --- 7) 观演人：预选场景下跳过校验，只读状态 ---
        if verify_users and users:
            missing = self.select_viewers_fast(users)
            self.lap(f"校验观演人 {users} (missing={missing})")
        else:
            # 仅一次 dump 读取勾选状态，用于日志确证（不做点击）
            xml = self.b.dump()
            rows = self._viewer_rows(xml)
            self.lap(f"读取观演人状态 {[r[0] for r in rows if r[1]] or rows}")
        return True

    # ---- 轻量观演人操作 ----
    def _viewer_rows(self, xml: str):
        from xml.etree import ElementTree as ET
        root = ET.fromstring(xml)
        out, seen = [], set()
        for row in root.iter():
            if row.get("resource-id") != "cn.damai:id/layout_main":
                continue
            name = cb = None
            checked = False
            for ch in row.iter():
                rid = ch.get("resource-id")
                if rid == "cn.damai:id/text_name":
                    name = (ch.get("text") or "").strip()
                elif rid == "cn.damai:id/checkbox":
                    cb = ch
                    checked = (ch.get("checked") == "true")
            if name and name not in seen:
                seen.add(name)
                out.append((name, checked, cb))
        return out

    def select_viewers_fast(self, users: List[str]) -> List[str]:
        xml = self.b.dump()
        rows = self._viewer_rows(xml)
        missing = []
        for want in users:
            hit = next((r for r in rows if r[0] == want), None)
            if hit is None:
                missing.append(want)
                continue
            if hit[1]:
                continue          # 已勾选（预选生效），不重复点
            if hit[2] is None:
                missing.append(want)
                continue
            x, y = self._center(hit[2])
            self.tap(x, y)
            time.sleep(0.15)
        return missing


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="预选优化版：详情页 → 可提交订单")
    ap.add_argument("--serial", required=True)
    ap.add_argument("--keyword", default="张韶涵")
    ap.add_argument("--price-index", type=int, default=3)
    ap.add_argument("--users", default="姚瑜")
    ap.add_argument("--skip-price", action="store_true", help="跳过选票档（票档由 App 默认选中）")
    ap.add_argument("--verify-users", action="store_true", help="校验/补齐观演人（默认跳过，信赖预选）")
    ap.add_argument("--repeat", type=int, default=1)
    args = ap.parse_args(argv)

    users = [u.strip() for u in args.users.split(",") if u.strip()]
    totals: List[float] = []
    for i in range(args.repeat):
        print("=" * 56)
        print(f"第 {i+1}/{args.repeat} 次（预选优化版）"
              f"{'  跳过选票档' if args.skip_price else ''}"
              f"{'  校验观演人' if args.verify_users else '  跳过观演人(信赖预选)'}")
        print("=" * 56)
        r = PresetRunner(args.serial)
        try:
            if not r.run(args.price_index, users, args.keyword,
                         skip_price=args.skip_price, verify_users=args.verify_users):
                print("  流程未完成")
                return 1
            totals.append(r.report())
        finally:
            r.close()
        if i < args.repeat - 1:
            resetter = fr.FastRunner(args.serial, verbose=False)
            try:
                for _ in range(2):
                    resetter.sh("input keyevent KEYCODE_BACK")
                    time.sleep(0.7)
                resetter.wait_token(fr.T_PURCHASE, timeout=8.0)
                time.sleep(0.3)
            finally:
                resetter.close()

    print()
    print(f"结果: {[f'{t/1000:.2f}s' for t in totals]}")
    if len(totals) > 1:
        print(f"中位: {statistics.median(totals)/1000:.2f}s   最快: {min(totals)/1000:.2f}s")
    print("\n注意: 未提交订单。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
