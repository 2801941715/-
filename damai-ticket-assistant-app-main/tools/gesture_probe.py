#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""手势注入能力诊断（真机排障用）。

背景：部分国产 ROM / 目标 App（含大麦）会对「无障碍手势注入」做限制。
本工具用受控实验区分三种可能：

  A. 无障碍服务缺少手势能力        -> caps 探针会返回 canPerformGestures=false
  B. 设备/系统层面拦截手势注入      -> 在「本应用/系统设置」上点击也无效
  C. 目标 App 过滤注入手势          -> 其它 App 有效，但目标 App 无效

用法：
    python tools/gesture_probe.py --serial <设备> --x 533 --y 1795
    python tools/gesture_probe.py --serial <设备> --selftest
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
from typing import Any, Dict, Optional

PORT = 8710
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def adb_path() -> str:
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
    p = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Android", "Sdk", "platform-tools", "adb.exe")
    return p


def adb(serial: str, *args: str) -> str:
    r = subprocess.run([adb_path(), "-s", serial, *args], capture_output=True,
                       encoding="utf-8", errors="replace")
    return r.stdout or ""


def bridge(payload: Dict[str, Any], timeout: float = 20.0) -> Dict[str, Any]:
    s = socket.create_connection(("127.0.0.1", PORT), timeout=timeout)
    f = s.makefile("rw", encoding="utf-8", newline="\n")
    try:
        f.write(json.dumps(payload) + "\n")
        f.flush()
        line = f.readline().strip()
        return json.loads(line) if line else {}
    finally:
        f.close()
        s.close()


def foreground(serial: str) -> str:
    out = adb(serial, "shell", "dumpsys", "activity", "activities")
    for line in out.splitlines():
        if "topResumedActivity" in line:
            return line.strip()
    return "(unknown)"


OUTCOME = {0: "完成(手势已送达)", 1: "取消(被拦截/被后续手势打断)", 2: "超时", 3: "未派发"}


def probe(serial: str, x: int, y: int, duration: int) -> int:
    r = bridge({"cmd": "tap", "x": x, "y": y, "duration": duration})
    outcome = r.get("outcome")
    print(f"  点击 ({x},{y}) duration={duration}ms -> outcome={outcome} ({OUTCOME.get(outcome, '?')})")
    return int(outcome) if isinstance(outcome, int) else -1


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description="无障碍手势注入能力诊断")
    ap.add_argument("--serial", help="设备序列号")
    ap.add_argument("--x", type=int, help="点击 x")
    ap.add_argument("--y", type=int, help="点击 y")
    ap.add_argument("--duration", type=int, default=50, help="手势时长(ms)")
    ap.add_argument("--selftest", action="store_true",
                    help="执行自检：先在本应用上验证手势是否可用，再给出结论")
    args = ap.parse_args(argv)

    serial = args.serial
    if not serial:
        out = subprocess.run([adb_path(), "devices"], capture_output=True,
                             encoding="utf-8", errors="replace").stdout or ""
        for line in out.splitlines()[1:]:
            p = line.split()
            if len(p) >= 2 and p[1] == "device":
                serial = p[0]
                break
    if not serial:
        raise SystemExit("未检测到设备")

    # 建立端口转发
    adb(serial, "forward", f"tcp:{PORT}", f"tcp:{PORT}")

    print(f"设备: {serial}")
    caps = bridge({"cmd": "caps"})
    print(f"[A] 无障碍手势能力: capabilities={caps.get('capabilities')} "
          f"canPerformGestures={caps.get('canPerformGestures')}")
    if not caps.get("canPerformGestures"):
        print("    => 结论 A：无障碍服务未获得手势能力（检查 accessibility_service_config 的 canPerformGestures）")
        return 2

    if args.selftest:
        pkg = "com.damai.assistant"
        print(f"[B] 自检：在本应用界面 ({pkg}) 上点击「开启无障碍权限」按钮")
        adb(serial, "shell", "am", "start", "-n", f"{pkg}/.MainActivity")
        time.sleep(3)
        before = foreground(serial)
        print(f"    点击前前台: {before}")
        probe(serial, 684, 951, args.duration)
        time.sleep(3)
        after = foreground(serial)
        print(f"    点击后前台: {after}")
        moved = ("settings" in after.lower()) or (after != before)
        if not moved:
            print("    => 结论 B：本应用上点击也无效，问题在设备/系统层面（ROM 手势限制或服务未真正生效）")
            return 3
        print("    => 本应用点击有效：手势注入链路正常（capabilities 与 dispatch 均 OK）")
        print("    => 结论 C：若目标 App 内点击无效，则是该 App 过滤了注入手势（应用侧防护）")
        return 0

    if args.x is None or args.y is None:
        print("请提供 --x/--y，或使用 --selftest")
        return 0

    print(f"[C] 在目标界面点击 ({args.x},{args.y})")
    print(f"    当前前台: {foreground(serial)}")
    probe(serial, args.x, args.y, args.duration)
    return 0


if __name__ == "__main__":
    sys.exit(main())
