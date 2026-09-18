#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Windows 侧远程调试客户端（App 模式 / 手机内运行版）。

通过 adb 端口转发连接手机内「大麦抢票助手」暴露的调试端口，
在电脑上即可查看状态、下发配置、启停流程、读取日志与页面层级。

设计要点：
  - 仅使用 Python 标准库（与项目「最小依赖」风格一致）；
  - 自动执行 `adb forward tcp:8710 tcp:8710`，无需手工准备；
  - 手机端 bridge 只监听 127.0.0.1，必须经 adb 通道访问。

典型用法：
    # 1. 连接设备并安装
    adb install -r android/dist/damai-assistant-debug.apk

    # 2. 在前台 App 中开启无障碍权限（或直接调用 accessibility 设置页）

    # 3. 电脑侧远程调试
    python tools/damai_remote.py doctor
    python tools/damai_remote.py status
    python tools/damai_remote.py set --city 郑州 --price-index 3 --users 张三,李四
    python tools/damai_remote.py start
    python tools/damai_remote.py logs --follow
    python tools/damai_remote.py dump -o page_dump_remote.xml
    python tools/damai_remote.py stop
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional

DEFAULT_PORT = 8710
DEFAULT_APK = os.path.join("android", "dist", "damai-assistant-debug.apk")
PACKAGE = "com.damai.assistant"
SERVICE_COMPONENT = f"{PACKAGE}/{PACKAGE}.DamaiAutomationService"


# ---------------------------------------------------------------------------
# adb 工具
# ---------------------------------------------------------------------------
def adb_path() -> str:
    """定位 adb：优先 PATH，其次常见的 Android SDK 安装位置。"""
    found = shutil.which("adb")
    if found:
        return found

    candidates = []
    for env in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        root = os.environ.get(env)
        if root:
            candidates.append(os.path.join(root, "platform-tools", "adb.exe"))
            candidates.append(os.path.join(root, "platform-tools", "adb"))
    local = os.environ.get("LOCALAPPDATA")
    if local:
        candidates.append(os.path.join(local, "Android", "Sdk", "platform-tools", "adb.exe"))
    candidates.append(r"C:\Android\platform-tools\adb.exe")

    for path in candidates:
        if path and os.path.exists(path):
            return path
    raise SystemExit(
        "未找到 adb。请安装 Android Platform Tools 并加入 PATH，"
        "或设置环境变量 ANDROID_HOME。"
    )


def adb(*args: str, timeout: int = 30) -> subprocess.CompletedProcess:
    cmd = [adb_path(), *args]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def list_devices() -> List[Dict[str, str]]:
    proc = adb("devices", "-l")
    devices: List[Dict[str, str]] = []
    for line in (proc.stdout or "").splitlines()[1:]:
        line = line.strip()
        if not line or "\t" not in line and " " not in line:
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        entry = {"serial": parts[0], "state": parts[1]}
        for token in parts[2:]:
            if ":" in token:
                key, value = token.split(":", 1)
                entry[key] = value
        devices.append(entry)
    return devices


def require_device(explicit: Optional[str]) -> str:
    devices = list_devices()
    if not devices:
        raise SystemExit("未检测到设备。请连接手机并开启 USB 调试（adb devices 应为 device 状态）。")
    if explicit:
        for d in devices:
            if d["serial"] == explicit:
                return explicit
        raise SystemExit(f"未找到指定设备: {explicit}")
    ready = [d for d in devices if d["state"] == "device"]
    if not ready:
        raise SystemExit(
            "设备已连接但未授权（状态非 device）。请在手机上确认 USB 调试授权。"
        )
    return ready[0]["serial"]


def setup_forward(serial: str, port: int) -> None:
    adb("-s", serial, "forward", f"tcp:{port}", f"tcp:{port}")


def remove_forward(serial: str, port: int) -> None:
    adb("-s", serial, "forward", "--remove", f"tcp:{port}")


# ---------------------------------------------------------------------------
# bridge 协议（一行一个 JSON）
# ---------------------------------------------------------------------------
class BridgeClient:
    def __init__(self, host: str = "127.0.0.1", port: int = DEFAULT_PORT, timeout: float = 120.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.sock: Optional[socket.socket] = None
        self.reader = None
        self.writer = None

    def connect(self) -> None:
        self.sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        self.sock.settimeout(self.timeout)
        self.reader = self.sock.makefile("r", encoding="utf-8", newline="\n")
        self.writer = self.sock.makefile("w", encoding="utf-8", newline="\n")

    def close(self) -> None:
        for stream in (self.reader, self.writer):
            try:
                if stream:
                    stream.close()
            except Exception:
                pass
        try:
            if self.sock:
                self.sock.close()
        except Exception:
            pass
        self.sock = None

    def request(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        if self.writer is None or self.reader is None:
            raise RuntimeError("尚未连接，请先调用 connect()")
        self.writer.write(json.dumps(payload, ensure_ascii=False) + "\n")
        self.writer.flush()
        line = self.reader.readline()
        if not line:
            raise ConnectionError("与手机端 bridge 的连接已断开")
        return json.loads(line)

    def __enter__(self) -> "BridgeClient":
        self.connect()
        return self

    def __exit__(self, *_exc) -> None:
        self.close()


def connect_bridge(args: argparse.Namespace) -> BridgeClient:
    """建立 adb 转发并连接 bridge。"""
    serial = require_device(args.device)
    setup_forward(serial, args.port)
    client = BridgeClient(port=args.port, timeout=args.timeout)
    client.connect()
    return client


# ---------------------------------------------------------------------------
# 命令实现
# ---------------------------------------------------------------------------
def cmd_devices(args: argparse.Namespace) -> int:
    devices = list_devices()
    if not devices:
        print("未检测到设备。")
        return 1
    print(f"{'serial':<22}{'state':<12}model")
    for d in devices:
        print(f"{d['serial']:<22}{d['state']:<12}{d.get('model', '')}")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    """一键体检：adb / 设备 / 端口转发 / bridge / 无障碍服务。"""
    ok = True
    print("== 远程调试体检 ==")

    try:
        path = adb_path()
        print(f"[OK]   adb: {path}")
    except SystemExit as exc:
        print(f"[FAIL] adb: {exc}")
        return 1

    devices = list_devices()
    ready = [d for d in devices if d["state"] == "device"]
    if ready:
        print(f"[OK]   设备: {', '.join(d['serial'] for d in ready)}")
    else:
        print("[FAIL] 设备: 无可用设备（需 adb devices 显示 device）")
        ok = False

    installed = adb("shell", "pm", "list", "packages", PACKAGE).stdout or ""
    if PACKAGE in installed:
        print(f"[OK]   应用已安装: {PACKAGE}")
    else:
        print(f"[WARN] 应用未安装: {PACKAGE}（adb install -r {DEFAULT_APK}）")
        ok = False

    if not ok:
        return 1

    serial = ready[0]["serial"]
    setup_forward(serial, args.port)
    print(f"[OK]   端口转发: tcp:{args.port} -> tcp:{args.port}")

    try:
        with BridgeClient(port=args.port, timeout=10.0) as client:
            pong = client.request({"cmd": "ping"})
            print(f"[OK]   bridge: {pong}")
            status = client.request({"cmd": "status"})
            if status.get("service_connected"):
                print("[OK]   无障碍服务: 已开启")
            else:
                print("[WARN] 无障碍服务: 未开启 —— 请在手机上开启本应用的无障碍权限")
    except Exception as exc:
        print(f"[FAIL] bridge: {exc}")
        print("       请确认手机端 App 已开启无障碍服务（bridge 随服务启动）。")
        return 1
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    client = connect_bridge(args)
    try:
        status = client.request({"cmd": "status"})
        print(json.dumps(status, ensure_ascii=False, indent=2))
    finally:
        client.close()
    return 0


def cmd_get_config(args: argparse.Namespace) -> int:
    client = connect_bridge(args)
    try:
        result = client.request({"cmd": "getConfig"})
        print(json.dumps(result.get("config", result), ensure_ascii=False, indent=2))
    finally:
        client.close()
    return 0


def build_config_payload(args: argparse.Namespace) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if args.config:
        with open(args.config, "r", encoding="utf-8") as fp:
            payload.update(json.load(fp))
    if args.keyword is not None:
        payload["keyword"] = args.keyword
    if args.city is not None:
        payload["city"] = args.city
    if args.price is not None:
        payload["price"] = args.price
    if args.price_index is not None:
        payload["price_index"] = args.price_index
    if args.users is not None:
        payload["users"] = [u.strip() for u in args.users.split(",") if u.strip()]
    if args.commit_order is not None:
        payload["if_commit_order"] = bool(args.commit_order)
    if args.max_retries is not None:
        payload["max_retries"] = args.max_retries
    return payload


def cmd_set(args: argparse.Namespace) -> int:
    payload = build_config_payload(args)
    if not payload:
        print("未提供任何配置项，使用 --help 查看可用参数。")
        return 2
    client = connect_bridge(args)
    try:
        result = client.request({"cmd": "setConfig", "config": payload})
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("ok") else 1
    finally:
        client.close()


def cmd_start(args: argparse.Namespace) -> int:
    payload = build_config_payload(args)
    client = connect_bridge(args)
    try:
        request: Dict[str, Any] = {"cmd": "start"}
        if payload:
            request["config"] = payload
        result = client.request(request)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("ok") else 1
    finally:
        client.close()


def cmd_stop(args: argparse.Namespace) -> int:
    client = connect_bridge(args)
    try:
        result = client.request({"cmd": "stop"})
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("ok") else 1
    finally:
        client.close()


def cmd_logs(args: argparse.Namespace) -> int:
    client = connect_bridge(args)
    cursor = 0
    try:
        while True:
            result = client.request({"cmd": "logs", "since": cursor})
            for entry in result.get("logs", []):
                prefix = {
                    "step": "🧭", "info": "ℹ️", "success": "✅",
                    "warning": "⚠️", "error": "❌",
                }.get(entry.get("level", "info"), "•")
                print(f"[{entry.get('time')}] {prefix} {entry.get('message')}")
            cursor = int(result.get("next", cursor))
            if not args.follow:
                break
            if not client.request({"cmd": "status"}).get("running"):
                # 流程结束再取一次剩余日志后退出
                result = client.request({"cmd": "logs", "since": cursor})
                for entry in result.get("logs", []):
                    prefix = {
                        "step": "🧭", "info": "ℹ️", "success": "✅",
                        "warning": "⚠️", "error": "❌",
                    }.get(entry.get("level", "info"), "•")
                    print(f"[{entry.get('time')}] {prefix} {entry.get('message')}")
                break
            time.sleep(1.0)
    except KeyboardInterrupt:
        print("\n已停止跟踪（手机端流程仍在运行）。")
    finally:
        client.close()
    return 0


def cmd_dump(args: argparse.Namespace) -> int:
    client = connect_bridge(args)
    try:
        result = client.request({"cmd": "dump"})
        xml = result.get("xml", "")
        if args.output:
            with open(args.output, "w", encoding="utf-8") as fp:
                fp.write(xml)
            print(f"页面层级已保存: {args.output}")
        else:
            print(xml)
    finally:
        client.close()
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    client = connect_bridge(args)
    try:
        status = client.request({"cmd": "status"})
        logs = client.request({"cmd": "logs", "since": 0})
        report = {
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "device": args.device,
            "status": status,
            "logs": logs.get("logs", []),
        }
        text = json.dumps(report, ensure_ascii=False, indent=2)
        if args.output:
            with open(args.output, "w", encoding="utf-8") as fp:
                fp.write(text)
            print(f"运行报告已导出: {args.output}")
        else:
            print(text)
    finally:
        client.close()
    return 0


def cmd_install(args: argparse.Namespace) -> int:
    apk = args.apk or DEFAULT_APK
    if not os.path.exists(apk):
        raise SystemExit(f"未找到 APK: {apk}（请先运行 android/build.ps1 构建）")
    serial = require_device(args.device)
    proc = adb("-s", serial, "install", "-r", apk, timeout=180)
    print(proc.stdout or "")
    print(proc.stderr or "")
    if proc.returncode != 0:
        return 1
    adb("-s", serial, "shell", "am", "start", "-n", f"{PACKAGE}/.MainActivity")
    print("已安装并启动。请在手机界面中开启无障碍权限。")
    return 0


def cmd_forward(args: argparse.Namespace) -> int:
    serial = require_device(args.device)
    if args.remove:
        remove_forward(serial, args.port)
        print(f"已移除转发 tcp:{args.port}")
    else:
        setup_forward(serial, args.port)
        print(f"已建立转发: tcp:{args.port} -> tcp:{args.port} ({serial})")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="大麦抢票助手（手机内运行版）Windows 远程调试客户端",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--device", help="目标设备序列号（多设备时指定）")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"调试端口（默认 {DEFAULT_PORT}）")
    parser.add_argument("--timeout", type=float, default=120.0, help="socket 超时秒数")

    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("devices", help="列出已连接设备").set_defaults(func=cmd_devices)
    sub.add_parser("doctor", help="一键体检（adb/设备/转发/bridge/无障碍）").set_defaults(func=cmd_doctor)
    sub.add_parser("status", help="查询运行状态").set_defaults(func=cmd_status)
    sub.add_parser("get-config", help="读取当前配置").set_defaults(func=cmd_get_config)

    def add_config_opts(p: argparse.ArgumentParser) -> None:
        p.add_argument("--config", help="JSON 配置文件路径")
        p.add_argument("--keyword", help="演出/歌手关键词")
        p.add_argument("--city", help="城市")
        p.add_argument("--price", help="票价文本")
        p.add_argument("--price-index", type=int, help="票价索引（从 0 开始）")
        p.add_argument("--users", help="观演人，逗号分隔")
        p.add_argument("--max-retries", type=int, help="最大重试次数")
        p.add_argument("--commit-order", dest="commit_order", action="store_true", default=None,
                       help="开启自动提交订单")
        p.add_argument("--no-commit-order", dest="commit_order", action="store_false",
                       help="关闭自动提交订单")

    p_set = sub.add_parser("set", help="下发配置")
    add_config_opts(p_set)
    p_set.set_defaults(func=cmd_set)

    p_start = sub.add_parser("start", help="启动抢票流程（可同时下发配置）")
    add_config_opts(p_start)
    p_start.set_defaults(func=cmd_start)

    sub.add_parser("stop", help="停止抢票流程").set_defaults(func=cmd_stop)

    p_logs = sub.add_parser("logs", help="读取运行日志")
    p_logs.add_argument("--follow", "-f", action="store_true", help="持续跟踪直到流程结束")
    p_logs.set_defaults(func=cmd_logs)

    p_dump = sub.add_parser("dump", help="导出当前页面层级 XML")
    p_dump.add_argument("-o", "--output", help="输出文件路径")
    p_dump.set_defaults(func=cmd_dump)

    p_report = sub.add_parser("report", help="导出运行报告 JSON")
    p_report.add_argument("-o", "--output", help="输出文件路径")
    p_report.set_defaults(func=cmd_report)

    p_install = sub.add_parser("install", help="安装 APK 并启动")
    p_install.add_argument("--apk", help=f"APK 路径（默认 {DEFAULT_APK}）")
    p_install.set_defaults(func=cmd_install)

    p_forward = sub.add_parser("forward", help="手动建立/移除端口转发")
    p_forward.add_argument("--remove", action="store_true", help="移除转发")
    p_forward.set_defaults(func=cmd_forward)

    return parser


def _configure_console() -> None:
    """保证中文/emoji 在 Windows 下都能安全、正确地输出。

    分两种情况处理：

    1. stdout 被重定向到管道/文件（脚本调用场景）
       Python 会使用系统 locale 编码（简体中文 Windows 上是 GBK/936），
       中文尚可勉强编码，但 emoji 会直接抛 UnicodeEncodeError，
       而按 GBK 编码的字节又会被调用方误按 UTF-8 解码成乱码。
       因此这里强制改用 UTF-8，保证脚本拿到的是干净的 UTF-8 文本。

    2. stdout 是真实控制台（交互场景）
       保留控制台原有编码（Windows 终端常为 GBK），
       仅把不可编码字符替换为占位符，
       避免 print 抛异常导致命令失败，同时不破坏原有中文显示。
    """
    for stream in (sys.stdout, sys.stderr):
        if stream is None:
            continue
        try:
            if not stream.isatty():
                stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
            else:
                stream.reconfigure(errors="replace")  # type: ignore[union-attr]
        except Exception:
            pass


def _ensure_utf8_child_env() -> None:
    """让本进程的子进程（adb 等）也以 UTF-8 返回文本。"""
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")


def main(argv: Optional[List[str]] = None) -> int:
    _ensure_utf8_child_env()
    _configure_console()
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except SystemExit:
        raise
    except KeyboardInterrupt:
        print("\n已中断。")
        return 130
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
