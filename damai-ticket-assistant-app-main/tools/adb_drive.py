#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""基于 adb 注入的真机预演（不依赖无障碍手势）。

为什么需要它：实测大麦会过滤无障碍注入手势，但 `adb shell input tap` 有效。
本脚本复用与 App 相同的「选择器 + 流程」语义，但点击通过 adb 注入完成，
用于在真机上验证选择器是否命中、流程能否走通。

用法：
    python tools/adb_drive.py --serial <设备> status
    python tools/adb_drive.py --serial <设备> dump -o page.xml
    python tools/adb_drive.py --serial <设备> tap --id cn.damai:id/btn_buy_view
    python tools/adb_drive.py --serial <设备> tap --text "立即购票"
    python tools/adb_drive.py --serial <设备> run-buy --price-index 3
"""

from __future__ import annotations

import argparse
import io
import os
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DUMP_DEFAULT = os.path.join(ROOT, "android", "dist", "_adb_drive.xml")

DIALOG_TITLE = "cn.damai:id/damai_theme_dialog_title"
DIALOG_CONFIRM = "cn.damai:id/damai_theme_dialog_confirm_btn"
DIALOG_CANCEL = "cn.damai:id/damai_theme_dialog_cancel_btn"
PRICE_CONTAINER = "cn.damai:id/project_detail_perform_price_flowlayout"
PURCHASE_BAR = "cn.damai:id/trade_project_detail_purchase_status_bar_container_fl"
CONFIRM_BTN = "cn.damai:id/btn_buy_view"
# 观演人（确认订单页 DmOrderActivity）
VIEWER_CONTAINER = "cn.damai:id/recycler_main"
VIEWER_ROW = "cn.damai:id/layout_main"
VIEWER_NAME = "cn.damai:id/text_name"
VIEWER_CHECKBOX = "cn.damai:id/checkbox"
# 刷新相关按钮文本（真机实测存在）
REFRESH_TEXT = "努力刷新"
CONTINUE_TRY_TEXT = "继续尝试"
SUBMIT_TEXT = "立即提交"
# 关键 Activity（用于判断流程所处阶段）
DETAIL_ACTIVITY = "ProjectDetailActivity"
SKU_ACTIVITY = "NcovSkuActivity"
ORDER_ACTIVITY = "DmOrderActivity"


def _adb_path() -> str:
    from shutil import which
    found = which("adb")
    if found:
        return found
    for env in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        r = os.environ.get(env)
        if r:
            p = os.path.join(r, "platform-tools", "adb.exe")
            if os.path.exists(p):
                return p
    return os.path.join(os.environ.get("LOCALAPPDATA", ""), "Android", "Sdk",
                        "platform-tools", "adb.exe")


class Driver:
    def __init__(self, serial: str) -> None:
        self.serial = serial

    def adb(self, *args: str) -> str:
        r = subprocess.run([_adb_path(), "-s", self.serial, *args],
                           capture_output=True, encoding="utf-8", errors="replace")
        return r.stdout or ""

    # ---------------- 基础动作 ----------------
    def dump(self, out: str = DUMP_DEFAULT) -> str:
        """导出当前页面层级。

        优先复用 App 内的无障碍桥（tools/damai_remote.py dump）：
        实测部分真机的 `uiautomator dump` 会报 "could not get idle state"，
        而桥接 dump 稳定可用，且格式与 uiautomator 对齐。
        """
        os.makedirs(os.path.dirname(out), exist_ok=True)
        remote = os.path.join(ROOT, "tools", "damai_remote.py")
        r = subprocess.run([sys.executable, remote, "--device", self.serial, "dump", "-o", out],
                           capture_output=True, encoding="utf-8", errors="replace")
        if os.path.exists(out) and os.path.getsize(out) > 0:
            return out
        # 兜底：uiautomator
        self.adb("shell", "rm", "-f", "/sdcard/_ad.xml")
        self.adb("shell", "uiautomator", "dump", "/sdcard/_ad.xml")
        self.adb("pull", "/sdcard/_ad.xml", out)
        return out

    def tap(self, x: int, y: int) -> None:
        self.adb("shell", "input", "tap", str(x), str(y))

    def launch_damai(self, wait: float = 8.0) -> str:
        """启动大麦 App 到首页（若已在任何大麦页面则不动）。"""
        fg = self.foreground()
        if "cn.damai" in fg:
            return fg
        self.adb("shell", "am", "start", "-n", "cn.damai/.homepage.MainActivity")
        time.sleep(wait)
        return self.foreground()

    def foreground(self) -> str:
        out = self.adb("shell", "dumpsys", "activity", "activities")
        for line in out.splitlines():
            if "topResumedActivity" in line:
                m = re.search(r"u0 ([^ ]+)", line)
                return m.group(1) if m else line.strip()
        return "(unknown)"

    # ---------------- 节点查询 ----------------
    @classmethod
    def _load(cls, path: str) -> ET.Element:
        root = ET.parse(path).getroot()
        cls._update_screen(root)
        return root

    # 屏幕尺寸（dump 的 hierarchy 节点给出），用于钳制越界坐标
    screen = (1368, 3192)

    @classmethod
    def _center(cls, node: ET.Element) -> Tuple[int, int]:
        b = node.get("bounds") or ""
        tl, br = b.split("][")
        x1, y1 = (int(v) for v in tl.strip("[").split(","))
        x2, y2 = (int(v) for v in br.strip("]").split(","))
        x, y = (x1 + x2) // 2, (y1 + y2) // 2
        # 大麦票档页含横向滚动容器，滚动过程中 dump 可能取到整屏偏移的 bounds，
        # 这类坐标必须钳制到屏幕内，否则点击会落到屏幕外而无效。
        w, h = cls.screen
        x = max(0, min(x, w - 1))
        y = max(0, min(y, h - 1))
        return x, y

    @classmethod
    def _update_screen(cls, root: ET.Element) -> None:
        for n in root.iter():
            if n.tag == "hierarchy":
                try:
                    cls.screen = (int(n.get("width")), int(n.get("height")))
                except Exception:
                    pass
                return

    @staticmethod
    def find_by_id(root: ET.Element, rid: str) -> Optional[ET.Element]:
        for n in root.iter():
            if n.get("resource-id") == rid:
                return n
        return None

    @staticmethod
    def find_by_text(root: ET.Element, text: str, contains: bool = True) -> Optional[ET.Element]:
        for n in root.iter():
            t = (n.get("text") or "").strip()
            d = (n.get("content-desc") or "").strip()
            if not t and not d:
                continue
            if (contains and (text in t or text in d)) or (not contains and text == t):
                return n
        return None

    @staticmethod
    def find_clickable(root: ET.Element, rid: str = "", text: str = "") -> Optional[ET.Element]:
        for n in root.iter():
            if n.get("clickable") != "true":
                continue
            if rid and n.get("resource-id") == rid:
                return n
            if text:
                t = (n.get("text") or "")
                for d in n.iter():
                    if text in (d.get("text") or ""):
                        return n
                if text in t:
                    return n
        return None

    # ---------------- 弹窗 ----------------
    def dismiss_dialogs(self, dump_path: str) -> List[str]:
        closed: List[str] = []
        for _ in range(4):
            self.dump(dump_path)
            root = self._load(dump_path)
            if self.find_by_id(root, DIALOG_TITLE) is None:
                break
            title_node = self.find_by_id(root, DIALOG_TITLE)
            title = (title_node.get("text") or "").strip() if title_node is not None else ""
            # 优先无副作用按钮
            target = None
            for kw in ("知道了", "我知道了", "取消"):
                target = self.find_by_text(root, kw)
                if target is not None:
                    break
            if target is None:
                target = self.find_by_id(root, DIALOG_CONFIRM)
            if target is None:
                for kw in ("确认并知悉", "确定", "同意"):
                    target = self.find_by_text(root, kw)
                    if target is not None:
                        break
            if target is None:
                break
            x, y = self._center(target)
            self.tap(x, y)
            closed.append(title or "(dialog)")
            time.sleep(0.8)
        return closed

    # ---------------- 业务动作 ----------------
    def tap_by_id(self, rid: str, dump_path: str = DUMP_DEFAULT) -> bool:
        self.dump(dump_path)
        root = self._load(dump_path)
        node = self.find_by_id(root, rid)
        if node is None:
            return False
        x, y = self._center(node)
        self.tap(x, y)
        return True

    # ---------------- 刷新与提交 ----------------

    def tap_text(self, text: str, dump_path: str = DUMP_DEFAULT,
                 contains: bool = True) -> Optional[Tuple[int, int]]:
        """按文本找到并点击（优先可点击节点）。返回点击坐标或 None。"""
        self.dump(dump_path)
        root = self._load(dump_path)
        node = self.find_clickable(root, text=text) or self.find_by_text(root, text, contains=contains)
        if node is None:
            return None
        x, y = self._center(node)
        self.tap(x, y)
        return x, y

    def has_text(self, text: str, dump_path: str = DUMP_DEFAULT) -> bool:
        self.dump(dump_path)
        return self.find_by_text(self._load(dump_path), text) is not None

    def tap_effort_refresh(self, max_taps: int = 12, interval: float = 0.6,
                           dump_path: str = DUMP_DEFAULT) -> int:
        """点击「努力刷新」直到按钮消失或达到次数上限。

        售罄/未开售时该按钮会替代购买入口；点击它可刷新页面继续尝试。
        返回实际点击次数（0 表示未出现该按钮）。
        """
        taps = 0
        for _ in range(max_taps):
            hit = self.tap_text(REFRESH_TEXT, dump_path)
            if hit is None:
                break
            taps += 1
            time.sleep(interval)
        return taps

    def tap_continue_try(self, max_taps: int = 5, interval: float = 0.5,
                         dump_path: str = DUMP_DEFAULT) -> int:
        """点击「继续尝试」（提交订单后库存不足时弹出的重试按钮）。"""
        taps = 0
        for _ in range(max_taps):
            hit = self.tap_text(CONTINUE_TRY_TEXT, dump_path)
            if hit is None:
                break
            taps += 1
            time.sleep(interval)
        return taps

    def tap_submit(self, dump_path: str = DUMP_DEFAULT) -> bool:
        """点击「立即提交」（确认订单页）。"""
        return self.tap_text(SUBMIT_TEXT, dump_path) is not None

    # ---------------- 观演人 ----------------

    def viewers(self, dump_path: str = DUMP_DEFAULT) -> List[Tuple[str, bool, int, int]]:
        """返回 [(姓名, 是否已勾选, checkbox_cx, checkbox_cy)]。"""
        self.dump(dump_path)
        root = self._load(dump_path)
        out: List[Tuple[str, bool, int, int]] = []
        seen = set()
        for row in root.iter():
            if row.get("resource-id") != VIEWER_ROW:
                continue
            name = None
            checked = False
            cb = None
            for ch in row.iter():
                rid = ch.get("resource-id")
                if rid == VIEWER_NAME:
                    name = (ch.get("text") or "").strip()
                elif rid == VIEWER_CHECKBOX:
                    cb = ch
                    checked = (ch.get("checked") == "true")
            if name is None:
                continue
            # 真机 dump 中同一观演人会同时出现「外层容器 layout_main」与
            # 「内层可点击行 layout_main」，是嵌套关系，需按姓名去重。
            if name in seen:
                continue
            seen.add(name)
            if cb is not None:
                x, y = self._center(cb)
            else:
                x, y = self._center(row)
            out.append((name, checked, x, y))
        return out

    def select_viewers(self, names: List[str], dump_path: str = DUMP_DEFAULT) -> List[str]:
        """勾选指定观演人（已勾选则跳过，避免取消勾选）。返回未找到的姓名。"""
        missing: List[str] = []
        for name in names:
            done = False
            for _ in range(6):
                items = self.viewers(dump_path)
                for vname, checked, cx, cy in items:
                    if vname != name:
                        continue
                    if checked:
                        done = True          # 已勾选：跳过
                        break
                    self.tap(cx, cy)
                    time.sleep(0.5)
                    done = True
                    break
                if done:
                    break
                # 目标不在可视范围：在列表内滚动后重试
                self.swipe_up(dump_path)
                time.sleep(0.5)
            if not done:
                missing.append(name)
        return missing

    def swipe_up(self, dump_path: str = DUMP_DEFAULT, ratio: float = 0.35) -> None:
        """向上滑动（列表内滚动）。"""
        w, h = self.screen
        x = w // 2
        self.adb("shell", "input", "swipe", str(x), str(int(h * 0.70)),
                 str(x), str(int(h * (0.70 - ratio))))

    def verify_selectors(self, dump_path: str = DUMP_DEFAULT) -> Dict[str, bool]:
        self.dump(dump_path)
        root = self._load(dump_path)
        return {
            "purchase_bar": self.find_by_id(root, PURCHASE_BAR) is not None,
            "price_container": self.find_by_id(root, PRICE_CONTAINER) is not None,
            "confirm_btn": self.find_by_id(root, CONFIRM_BTN) is not None,
            "dialog": self.find_by_id(root, DIALOG_TITLE) is not None,
            "viewer_container": self.find_by_id(root, VIEWER_CONTAINER) is not None,
            "submit": self.find_by_text(root, SUBMIT_TEXT) is not None,
            "refresh": self.find_by_text(root, REFRESH_TEXT) is not None,
            "continue_try": self.find_by_text(root, CONTINUE_TRY_TEXT) is not None,
        }

    def _read_price_items(self, dump_path: str) -> List[Tuple[int, int, str]]:
        root = self._load(dump_path)
        c = self.find_by_id(root, PRICE_CONTAINER)
        out: List[Tuple[int, int, str]] = []
        if c is None:
            return out
        for ch in c:
            if ch.get("clickable") != "true":
                continue
            hints = [d.get("text") for d in ch.iter() if (d.get("text") or "").strip()]
            x, y = self._center(ch)
            out.append((x, y, " / ".join(hints) or "(自定义绘制)"))
        return out

    def price_items(self, dump_path: str = DUMP_DEFAULT, stable: bool = True) -> List[Tuple[int, int, str]]:
        """返回 [(cx, cy, 备注)] —— 顺序即 price_index。

        stable=True 时会连续采样两次，直到坐标一致（避免在页面滚动中间态取到偏移坐标）。
        """
        self.dump(dump_path)
        items = self._read_price_items(dump_path)
        if not stable:
            return items
        for _ in range(4):
            time.sleep(0.6)
            self.dump(dump_path)
            again = self._read_price_items(dump_path)
            if [i[:2] for i in again] == [i[:2] for i in items] and items:
                return again
            items = again
        return items


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="基于 adb 注入的真机预演驱动")
    ap.add_argument("--serial", required=True)
    ap.add_argument("--dump", default=DUMP_DEFAULT)
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status")
    p_dump = sub.add_parser("dump")
    p_dump.add_argument("-o", "--out", default=DUMP_DEFAULT)
    p_vs = sub.add_parser("verify")
    p_vs.add_argument("-o", "--out", default=DUMP_DEFAULT)
    p_tap = sub.add_parser("tap")
    p_tap.add_argument("--id")
    p_tap.add_argument("--text")
    p_dialog = sub.add_parser("dialog")
    p_prices = sub.add_parser("prices")
    p_refresh = sub.add_parser("refresh", help="点击「努力刷新」捡漏")
    p_refresh.add_argument("--taps", type=int, default=12)
    p_refresh.add_argument("--interval", type=float, default=0.6)
    p_ct = sub.add_parser("continue-try", help="点击「继续尝试」重试提交")
    p_ct.add_argument("--taps", type=int, default=5)
    p_viewers = sub.add_parser("viewers", help="列出观演人及其勾选状态")
    p_sel = sub.add_parser("select-viewers", help="按姓名勾选观演人（逗号分隔）")
    p_sel.add_argument("--names", required=True)
    p_submit = sub.add_parser("submit", help="点击「立即提交」")

    args = ap.parse_args(argv)
    d = Driver(args.serial)

    if args.cmd == "status":
        print("前台:", d.foreground())
        return 0
    if args.cmd == "dump":
        print("已导出:", d.dump(args.out))
        return 0
    if args.cmd == "verify":
        res = d.verify_selectors(args.out)
        for k, v in res.items():
            print(f"  {'OK ' if v else 'MISS'} {k}")
        return 0 if all(res.values()) else 1
    if args.cmd == "tap":
        if args.id:
            ok = d.tap_by_id(args.id, args.dump)
            print("按 id 点击:", "成功" if ok else "未找到")
            return 0 if ok else 1
        if args.text:
            d.dump(args.dump)
            root = d._load(args.dump)
            node = d.find_clickable(root, text=args.text) or d.find_by_text(root, args.text)
            if node is None:
                print("未找到文本:", args.text)
                return 1
            x, y = d._center(node)
            d.tap(x, y)
            print("按文本点击:", args.text, (x, y))
            return 0
        print("需要 --id 或 --text")
        return 2
    if args.cmd == "dialog":
        closed = d.dismiss_dialogs(args.dump)
        print("已关闭弹窗:", closed or "(无)")
        return 0
    if args.cmd == "refresh":
        n = d.tap_effort_refresh(args.taps, args.interval, args.dump)
        print(f"点击「努力刷新」{n} 次" if n else "未出现「努力刷新」按钮")
        return 0
    if args.cmd == "continue-try":
        n = d.tap_continue_try(args.taps, 0.5, args.dump)
        print(f"点击「继续尝试」{n} 次" if n else "未出现「继续尝试」按钮")
        return 0
    if args.cmd == "viewers":
        items = d.viewers(args.dump)
        if not items:
            print("未找到观演人列表（是否在确认订单页？）")
            return 1
        for name, checked, x, y in items:
            print(f"  {'[x]' if checked else '[ ]'} {name}  checkbox=({x},{y})")
        return 0
    if args.cmd == "select-viewers":
        names = [n.strip() for n in args.names.split(",") if n.strip()]
        missing = d.select_viewers(names, args.dump)
        for name, checked, x, y in d.viewers(args.dump):
            print(f"  {'[x]' if checked else '[ ]'} {name}")
        if missing:
            print("未找到:", missing)
            return 1
        return 0
    if args.cmd == "submit":
        ok = d.tap_submit(args.dump)
        print("已点击「立即提交」" if ok else "未找到「立即提交」")
        return 0 if ok else 1
    if args.cmd == "prices":
        items = d.price_items(args.dump)
        if not items:
            print("未找到票档容器")
            return 1
        print(f"共 {len(items)} 个票档（顺序即 price_index）：")
        for i, (x, y, hint) in enumerate(items):
            print(f"  index={i}  center=({x},{y})  {hint}")
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
