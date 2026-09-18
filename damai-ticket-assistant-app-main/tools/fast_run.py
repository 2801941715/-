#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""极速路径：演出详情页 -> 可提交订单（严格轮询，无固定 sleep）。

与 real_device_dryrun.py 等价，但做了如下提速：
  1. 持久化 bridge 连接（省去每次 7-28ms 建连）
  2. 彻底移除固定 sleep，改为「轮询 token 出现/就绪」立即推进
  3. 最小化 dump 次数（每个决策点只 dump 一次，结果就地复用）
  4. 用单次 dump 同时判定进度，避免重复取树

用法：
    python tools/fast_run.py --serial <设备> --price-index 3 --users 姚瑜
    python tools/fast_run.py --serial <设备> --repeat 3
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import statistics
import sys
import time
import xml.etree.ElementTree as ET
from typing import List, Optional, Tuple

ADB = os.path.join(os.environ.get("ANDROID_HOME", ""), "platform-tools", "adb.exe")
DUMP_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "android", "dist")

# 关键 token（出现在 dump 中即表示到达该状态）
T_PURCHASE = "trade_project_detail_purchase_status_bar_container_fl"
T_PRICE = "project_detail_perform_price_flowlayout"
T_CONFIRM = "btn_buy_view"
T_ORDER = "recycler_main"
T_DIALOG = "damai_theme_dialog_title"
T_DIALOG_CONFIRM = "damai_theme_dialog_confirm_btn"

POLL = 0.0   # 轮询间隔（0 = 尽可能快）


class Bridge:
    """持久连接的 bridge 客户端。"""

    def __init__(self, timeout: float = 30.0) -> None:
        self.sock = socket.create_connection(("127.0.0.1", 8710), timeout=timeout)
        self.rw = self.sock.makefile("rw", encoding="utf-8", newline="\n")

    def req(self, payload: dict) -> dict:
        self.rw.write(json.dumps(payload) + "\n")
        self.rw.flush()
        line = self.rw.readline()
        return json.loads(line) if line else {}

    def dump(self) -> str:
        xml = self.req({"cmd": "dump"}).get("xml", "")
        # 刷新屏幕尺寸（用于判断坐标是否越界）
        i = xml.find("<hierarchy")
        if i >= 0:
            head = xml[i:i + 200]
            import re
            mw = re.search(r'width="(\d+)"', head)
            mh = re.search(r'height="(\d+)"', head)
            if mw and mh:
                self.screen = (int(mw.group(1)), int(mh.group(1)))
        return xml

    def close(self) -> None:
        try:
            self.rw.close()
            self.sock.close()
        except Exception:
            pass


class FastRunner:
    def __init__(self, serial: str, verbose: bool = True) -> None:
        self.serial = serial
        self.verbose = verbose
        self.b = Bridge()
        self.stats: List[Tuple[str, float]] = []
        self._t = 0.0
        self.screen = (1080, 2400)   # 由 dump 的 hierarchy 节点刷新

    # ---------- 基础 ----------
    def _shell(self):
        """常驻 adb shell。

        关键提速点：每次执行 `adb shell input tap` 都要新起一个 adb 进程，
        实测约 85-135ms；改为复用同一个 shell 的 stdin 后，
        客户端开销降到 <1ms（只有设备端 `input` 自身的耗时）。
        """
        if getattr(self, "_shell_proc", None) is None:
            import subprocess
            self._shell_proc = subprocess.Popen(
                [ADB, "-s", self.serial, "shell"],
                stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, text=True,
            )
            time.sleep(0.3)   # 等 shell 就绪
        return self._shell_proc

    def sh(self, command: str) -> None:
        p = self._shell()
        p.stdin.write(command + "\n")
        p.stdin.flush()

    def adb(self, *args: str) -> None:
        import subprocess
        subprocess.run([ADB, "-s", self.serial, *args], capture_output=True)

    def tap(self, x: int, y: int) -> None:
        self.sh(f"input tap {int(x)} {int(y)}")

    def lap(self, label: str) -> float:
        now = time.perf_counter()
        dt = (now - self._t) * 1000 if self._t else 0.0
        self._t = now
        self.stats.append((label, dt))
        if self.verbose and dt:
            print(f"  {dt:8.0f} ms  {label}")
        return dt

    def start(self) -> None:
        self._t = time.perf_counter()

    # ---------- 解析 ----------
    @staticmethod
    def _center(node: ET.Element) -> Tuple[int, int]:
        b = node.get("bounds") or ""
        tl, br = b.split("][")
        x1, y1 = (int(v) for v in tl.strip("[").split(","))
        x2, y2 = (int(v) for v in br.strip("]").split(","))
        return (x1 + x2) // 2, (y1 + y2) // 2

    def wait_token(self, token: str, timeout: float = 12.0) -> Tuple[bool, int]:
        """严格轮询直到 dump 中出现 token；返回 (命中, 轮询次数)。"""
        n = 0
        t0 = time.perf_counter()
        while True:
            n += 1
            xml = self.b.dump()
            if token in xml:
                return True, n
            if time.perf_counter() - t0 > timeout:
                return False, n

    def _enter_detail_page(self, xml: str, keyword: str, timeout: float = 15.0) -> bool:
        """从首页点开含 keyword 的演出卡片，并等待详情页就绪。"""
        root = ET.fromstring(xml)
        card = None
        for n in root.iter():
            if n.get("resource-id") != "cn.damai:id/pioneer_homepage_item_container":
                continue
            if any(keyword in (c.get("text") or "") for c in n.iter()):
                card = n
                break
        if card is None:
            for n in root.iter():
                if keyword in (n.get("text") or ""):
                    card = n
                    break
        if card is None:
            return False
        x, y = self._center(card)
        self.tap(x, y)
        ok, _ = self.wait_token(T_PURCHASE, timeout=timeout)
        return ok

    def _price_applied(self, timeout: float = 2.0) -> bool:
        """判断票档是否已选中：底部「确定」旁的价格不再是 0。"""
        t0 = time.perf_counter()
        while time.perf_counter() - t0 < timeout:
            xml = self.b.dump()
            node = self.find(xml, "tv_price")
            if node is not None:
                txt = (node.get("text") or "").strip()
                if txt and txt not in ("0", ""):
                    return True
            if time.perf_counter() - t0 > timeout:
                break
        return False

    def wait_price_ready(self, timeout: float = 3.0, samples: int = 2) -> str:
        """等「票档项位于屏幕内且连续稳定」。

        真机实测（大麦 9.0.28）：进入票档页的瞬间，票档项 bounds 仍在漂移，
        首个采样点可能在屏幕外（如 x=1442 > 屏宽 1368），此时点击必然落空。
        实测约 0.8s 后才稳定。因此必须同时满足：
          1) 票档项的 bounds 落在屏幕内
          2) 连续 samples 次 dump 的 bounds 完全一致
        """
        w, h = self.screen
        last = None
        stable = 0
        t0 = time.perf_counter()
        xml = ""
        while time.perf_counter() - t0 < timeout:
            xml = self.b.dump()
            container = self.find(xml, T_PRICE)
            if container is None:
                stable = 0
                last = None
                continue
            items = [c for c in container if c.get("clickable") == "true"]
            sig = "|".join((c.get("bounds") or "") for c in items)
            on_screen = bool(items) and all(
                self._in_screen(c, w, h) for c in items[:1]
            )
            if on_screen and sig == last:
                stable += 1
                if stable >= samples:
                    return xml
            else:
                stable = 0
                last = sig
        return xml

    @staticmethod
    def _in_screen(node: ET.Element, w: int, h: int) -> bool:
        """判断节点是否完全落在屏幕内（横向滚动中间态会越界）。"""
        b = node.get("bounds") or ""
        if "][" not in b:
            return False
        tl, br = b.split("][")
        try:
            x1, y1 = (int(v) for v in tl.strip("[").split(","))
            x2, y2 = (int(v) for v in br.strip("]").split(","))
        except ValueError:
            return False
        return 0 <= x1 and x2 <= w and 0 <= y1 and y2 <= h

    def find(self, xml: str, rid: str) -> Optional[ET.Element]:
        """按 resource-id 查找；支持短名（不带 cn.damai:id/ 前缀）。"""
        root = ET.fromstring(xml)
        for n in root.iter():
            actual = n.get("resource-id") or ""
            if actual == rid or actual.endswith(":id/" + rid):
                return n
        return None

    def find_text(self, xml: str, text: str) -> Optional[ET.Element]:
        root = ET.fromstring(xml)
        for n in root.iter():
            t = (n.get("text") or "")
            if text in t:
                return n
        return None

    # ---------- 弹窗（就地按 token 判定，不重复 dump） ----------
    def clear_dialogs(self, timeout: float = 3.0) -> int:
        closed = 0
        t0 = time.perf_counter()
        while time.perf_counter() - t0 < timeout:
            xml = self.b.dump()
            if T_DIALOG not in xml and T_DIALOG_CONFIRM not in xml:
                break
            root = ET.fromstring(xml)
            target = None
            for kw in ("知道了", "我知道了", "取消", "确认并知悉", "确定", "同意"):
                for n in root.iter():
                    if kw in (n.get("text") or ""):
                        target = n
                        break
                if target is not None:
                    break
            if target is None:
                break
            x, y = self._center(target)
            self.tap(x, y)
            closed += 1
        return closed

    # ---------- 主流程 ----------
    def run(self, price_index: int, users: List[str], keyword: str = "张韶涵") -> bool:
        self.start()

        # --- 0) 确保位于演出详情页 ---
        # 记录「详情页就绪」时刻，用于单独报告用户关心的区间耗时
        xml = self.b.dump()
        if self.find(xml, T_PURCHASE) is None:
            if not self._enter_detail_page(xml, keyword):
                print("  未能进入演出详情页（缺购买入口）")
                return False
            self.lap("从首页进入演出详情页")
        self.detail_ready = time.perf_counter()

        # --- 1) 详情页：点购买入口 ---
        xml = self.b.dump()
        bar = self.find(xml, T_PURCHASE)
        if bar is None:
            print("  未在详情页（缺少购买入口）")
            return False
        x, y = self._center(bar)
        self.tap(x, y)
        self.lap("详情页: dump + 点击购买入口")

        # --- 2) 等票档页就绪（含弹窗） ---
        ok, n = self.wait_token(T_PRICE, timeout=12.0)
        self.lap(f"等待票档页就绪(轮询{n}次)")
        if not ok:
            return False
        self.clear_dialogs()
        self.lap("清理弹窗")

        # --- 3) 选票档 ---
        # 先等布局稳定：刚进入票档页时 bounds 仍在变化，此时点击会落空
        xml = self.wait_price_ready(timeout=3.0, samples=1)
        self.lap("等待票档就绪(屏内+稳定)")

        # 稳定后重取一次，缩小「读坐标 → 点击」的时间窗
        xml = self.b.dump()
        container = self.find(xml, T_PRICE)
        if container is None:
            return False
        items = [c for c in container if c.get("clickable") == "true"]
        if not (0 <= price_index < len(items)):
            print(f"  price_index={price_index} 越界(0..{len(items)-1})")
            return False
        x, y = self._center(items[price_index])
        self.tap(x, y)
        self.lap(f"选票档 index={price_index}")

        # 确认真实「已选中」：dvp 用 selected 属性判断；票档项本身不一定标 selected，
        # 因此以底部 tv_price 变化为准，并配合多次重试（真机偶发点击不生效）。
        applied = self._price_applied(timeout=1.2)
        if not applied:
            for attempt in range(5):
                # 重新取坐标后再点（页面可能有微滚动）
                xml2 = self.b.dump()
                c2 = self.find(xml2, T_PRICE)
                if c2 is not None:
                    its = [c for c in c2 if c.get("clickable") == "true"]
                    if 0 <= price_index < len(its):
                        x, y = self._center(its[price_index])
                self.tap(x, y)
                applied = self._price_applied(timeout=0.8)
                if applied:
                    self.lap(f"票档生效（重试{attempt+1}次）")
                    break
            if not applied:
                self.lap("票档始终未生效")
                return False
        else:
            self.lap("票档已生效")

        # --- 4) 点确定（票档已选中，按钮必定存在，无需额外等待） ---
        xml = self.b.dump()
        btn = self.find(xml, T_CONFIRM)
        if btn is None:
            ok, n = self.wait_token(T_CONFIRM, timeout=3.0)
            if not ok:
                return False
            btn = self.find(self.b.dump(), T_CONFIRM)
        x, y = self._center(btn)
        self.tap(x, y)
        self.lap("取确定坐标并点击")

        # --- 5) 等确认订单页（含弹窗） ---
        ok, n = self.wait_token(T_ORDER, timeout=12.0)
        self.lap(f"等待确认订单页(轮询{n}次)")
        if not ok:
            return False
        self.clear_dialogs()
        self.lap("清理弹窗")

        # --- 6) 勾选观演人（一次 dump 批量定位） ---
        if users:
            xml = self.b.dump()
            root = ET.fromstring(xml)
            rows = []
            seen = set()
            for row in root.iter():
                if row.get("resource-id") != "cn.damai:id/layout_main":
                    continue
                name = checked = cb = None
                for ch in row.iter():
                    rid = ch.get("resource-id")
                    if rid == "cn.damai:id/text_name":
                        name = (ch.get("text") or "").strip()
                    elif rid == "cn.damai:id/checkbox":
                        cb = ch
                        checked = (ch.get("checked") == "true")
                if name and name not in seen:
                    seen.add(name)
                    rows.append((name, checked, cb))
            for want in users:
                for name, checked, cb in rows:
                    if name == want and not checked and cb is not None:
                        x, y = self._center(cb)
                        self.tap(x, y)
                        break
            self.lap(f"勾选观演人 {users}")

        return True

    def close(self) -> None:
        p = getattr(self, "_shell_proc", None)
        if p is not None:
            try:
                p.stdin.write("exit\n")
                p.stdin.flush()
                p.wait(timeout=3)
            except Exception:
                try:
                    p.kill()
                except Exception:
                    pass
            self._shell_proc = None
        self.b.close()

    def report(self) -> float:
        total = sum(d for _, d in self.stats)
        end = time.perf_counter()
        print()
        print("=" * 56)
        for label, d in self.stats:
            if d:
                print(f"{label:<38}{d:8.0f}ms")
        print("-" * 56)
        print(f"{'全程（含进入详情页）':<38}{total:8.0f}ms  ({total/1000:.2f}s)")
        if getattr(self, "detail_ready", None):
            seg = (end - self.detail_ready) * 1000
            print(f"{'详情页 → 可提交订单':<38}{seg:8.0f}ms  ({seg/1000:.2f}s)")
            return seg
        return total


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="极速路径：详情页 -> 可提交订单（无固定 sleep）")
    ap.add_argument("--serial", required=True)
    ap.add_argument("--price-index", type=int, default=3)
    ap.add_argument("--users", default="姚瑜")
    ap.add_argument("--keyword", default="张韶涵", help="首页定位演出卡片的关键词")
    ap.add_argument("--repeat", type=int, default=1)
    args = ap.parse_args(argv)

    users = [u.strip() for u in args.users.split(",") if u.strip()]
    totals: List[float] = []
    for i in range(args.repeat):
        print("=" * 52)
        print(f"第 {i+1}/{args.repeat} 次（极速模式）")
        print("=" * 52)
        r = FastRunner(args.serial)
        try:
            if not r.run(args.price_index, users, args.keyword):
                print("  流程未完成")
                return 1
            totals.append(r.report())
        finally:
            r.close()
        if i < args.repeat - 1:
            # 复位到详情页：从确认订单页退两层（订单页 -> 票档页 -> 详情页）
            resetter = FastRunner(args.serial, verbose=False)
            try:
                for _ in range(2):
                    resetter.sh("input keyevent KEYCODE_BACK")
                    time.sleep(0.8)
                resetter.wait_token("trade_project_detail_purchase_status_bar_container_fl", timeout=8.0)
                time.sleep(0.3)
            finally:
                resetter.close()

    print()
    print(f"多次结果: {[f'{t/1000:.2f}s' for t in totals]}")
    if len(totals) > 1:
        print(f"中位数: {statistics.median(totals)/1000:.2f}s   最快: {min(totals)/1000:.2f}s")
    print("\n注意: 未提交订单。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
