#!/usr/bin/env python3
"""
麦麦成长日 · MCP 客户端 CLI
============================

零第三方依赖，仅用 Python 标准库通过 Streamable HTTP 直连麦当劳 MCP Server。

用途：
  1. 校验 Token 与连通性（check）
  2. 列出全部可用工具（tools）
  3. 查看某个工具的入参 Schema（schema）
  4. 调用只读工具（call）
  5. 本地营养配比计算（plan）—— 不联网，基于 nutrition-snapshot.json

用法：
  export MCD_MCP_TOKEN="你的Token"
  python scripts/mcd.py check
  python scripts/mcd.py tools
  python scripts/mcd.py schema list-nutrition-foods
  python scripts/mcd.py call now-time-info
  python scripts/mcd.py call list-nutrition-foods
  python scripts/mcd.py plan --age 8 --adults 1 --kids 1 --max-sodium 800

退出码：0 成功 / 1 工具错误 / 2 鉴权失败 / 3 限流 / 4 网络错误
"""

import json
import os
import sys
import urllib.error
import urllib.request

MCP_URL = "https://mcp.mcd.cn"
PROTOCOL_VERSION = "2024-11-05"
SNAPSHOT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "references",
    "nutrition-snapshot.json",
)


# --------------------------------------------------------------------------
# MCP 传输层
# --------------------------------------------------------------------------

def get_token():
    token = os.environ.get("MCD_MCP_TOKEN", "").strip()
    if not token:
        cfg = os.path.join(
            os.path.expanduser("~"), ".workbuddy", "mcp.json"
        )
        if os.path.exists(cfg):
            try:
                with open(cfg, encoding="utf-8") as fh:
                    raw = fh.read()
                start = raw.find("Bearer ")
                if start >= 0:
                    token = raw[start + 7:].split('"')[0].strip()
            except OSError:
                pass
    if not token:
        print(
            "未找到 Token。请设置环境变量 MCD_MCP_TOKEN，"
            "或保证 ~/.workbuddy/mcp.json 中已配置。",
            file=sys.stderr,
        )
        sys.exit(2)
    return token


class McpClient:
    def __init__(self):
        self.url = MCP_URL
        self.headers = {
            "Authorization": "Bearer " + get_token(),
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        self.session_id = None
        self._id = 0

    def _next_id(self):
        self._id += 1
        return self._id

    def rpc(self, method, params=None, notify=False):
        body = {"jsonrpc": "2.0", "method": method}
        if not notify:
            body["id"] = self._next_id()
        if params is not None:
            body["params"] = params
        headers = dict(self.headers)
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        req = urllib.request.Request(
            self.url, data=json.dumps(body).encode(), headers=headers, method="POST"
        )
        try:
            resp = urllib.request.urlopen(req, timeout=45)
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8", "replace")
            except Exception:
                pass
            if exc.code == 401:
                print("鉴权失败（401）：Token 无效或已过期。", file=sys.stderr)
                sys.exit(2)
            if exc.code == 429:
                print("触发限流（429）：超过 600 次/分钟，请稍候。", file=sys.stderr)
                sys.exit(3)
            print("HTTP %s: %s" % (exc.code, detail[:300]), file=sys.stderr)
            sys.exit(4)
        except Exception as exc:
            print("网络错误：%s" % exc, file=sys.stderr)
            sys.exit(4)

        sid = resp.headers.get("Mcp-Session-Id")
        if sid:
            self.session_id = sid
        raw = resp.read().decode("utf-8", "replace")
        if notify:
            return None
        payload = raw
        if raw.startswith("event:") or raw.startswith("data:"):
            for line in raw.splitlines():
                if line.startswith("data:"):
                    payload = line[5:].strip()
                    break
        return json.loads(payload)

    def connect(self):
        self.rpc(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "mcd-family-growth-day", "version": "1.0"},
            },
        )
        self.rpc("notifications/initialized", {}, notify=True)

    def call(self, name, args=None):
        result = self.rpc("tools/call", {"name": name, "arguments": args or {}})
        if result.get("error"):
            print("工具错误：%s" % json.dumps(result["error"], ensure_ascii=False),
                  file=sys.stderr)
            sys.exit(1)
        blocks = result.get("result", {}).get("content", [])
        return "\n".join(b.get("text", "") for b in blocks if b.get("type") == "text")


# --------------------------------------------------------------------------
# 本地营养配比
# --------------------------------------------------------------------------

AGE_BANDS = [
    (3, 6, 250, 350),
    (7, 9, 350, 450),
    (10, 12, 450, 550),
    (13, 99, 550, 650),
]


def kid_band(age):
    for lo, hi, kmin, kmax in AGE_BANDS:
        if lo <= age <= hi:
            return lo, hi, kmin, kmax
    return 13, 99, 550, 650


def cmd_plan(args):
    with open(SNAPSHOT, encoding="utf-8") as fh:
        foods = json.load(fh)

    adults = int(args.get("adults", 1))
    kids = int(args.get("kids", 1))
    age = int(args.get("age", 8))
    max_sodium = float(args.get("max_sodium", 800))
    _, _, kmin, kmax = kid_band(age)

    kid_items = [
        f for f in foods
        if f["protein"] >= 10 and kmin <= f["kcal"] <= kmax and f["sodium"] <= max_sodium
    ]
    kid_items.sort(key=lambda f: (-f["protein"], f["sodium"]))

    adult_items = [
        f for f in foods
        if f["protein"] >= 15 and 400 <= f["kcal"] <= 800 and f["sodium"] <= 1000
    ]
    adult_items.sort(key=lambda f: (-f["protein"], f["sodium"]))

    print("儿童段（%d岁）目标能量 %d-%d kcal，钠上限 %.0f mg" % (age, kmin, kmax, max_sodium))
    print("候选儿童餐品 %d 项，前 5：" % len(kid_items))
    for f in kid_items[:5]:
        print("  - %-22s kcal=%4d 蛋白=%4.0f 脂=%4.0f 碳=%4.0f 钠=%5.0f"
              % (f["name"][:22], f["kcal"], f["protein"], f["fat"], f["carb"], f["sodium"]))
    print()
    print("候选成人餐品 %d 项，前 5：" % len(adult_items))
    for f in adult_items[:5]:
        print("  - %-22s kcal=%4d 蛋白=%4.0f 脂=%4.0f 碳=%4.0f 钠=%5.0f"
              % (f["name"][:22], f["kcal"], f["protein"], f["fat"], f["carb"], f["sodium"]))
    print()
    if kid_items and adult_items:
        k, a = kid_items[0], adult_items[0]
        total_kcal = k["kcal"] * kids + a["kcal"] * adults
        kid_share = k["kcal"] * kids / total_kcal * 100
        print("推荐组合示例：成人 %s + 儿童 %s" % (a["name"], k["name"]))
        print("  全餐能量 %d kcal，蛋白质 %.0f g，钠 %.0f mg"
              % (total_kcal,
                 k["protein"] * kids + a["protein"] * adults,
                 k["sodium"] * kids + a["sodium"] * adults))
        print("  儿童能量占比 %.0f%%（目标 30-40%%）" % kid_share)
        print("  营养数据来自麦当劳官方餐品营养信息，仅供参考，不构成专业营养建议。")


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return

    cmd = sys.argv[1]
    client = McpClient()

    if cmd == "plan":
        args = {"adults": 1, "kids": 1, "age": 8, "max_sodium": 800}
        for i, item in enumerate(sys.argv[2:]):
            if item.startswith("--"):
                key = item[2:]
                val = sys.argv[3 + i] if 3 + i < len(sys.argv) else ""
                args[key] = val
        return cmd_plan(args)

    client.connect()

    if cmd == "check":
        print("连接成功，服务端：%s" % MCP_URL)
        return
    if cmd == "tools":
        tools = client.rpc("tools/list").get("result", {}).get("tools", [])
        print("共 %d 个工具：" % len(tools))
        for t in tools:
            print("  - %-26s %s" % (t["name"], (t.get("description") or "").split("\n")[0][:60]))
        return
    if cmd == "schema":
        if len(sys.argv) < 3:
            print("用法：python scripts/mcd.py schema <tool_name>")
            return
        target = sys.argv[2]
        tools = client.rpc("tools/list").get("result", {}).get("tools", [])
        for t in tools:
            if t["name"] == target:
                print(json.dumps(t.get("inputSchema", {}), ensure_ascii=False, indent=2))
                return
        print("未找到工具：%s" % target, file=sys.stderr)
        sys.exit(1)
    if cmd == "call":
        if len(sys.argv) < 3:
            print("用法：python scripts/mcd.py call <tool_name> [json_args]")
            return
        name = sys.argv[2]
        args = json.loads(sys.argv[3]) if len(sys.argv) > 3 else {}
        print(client.call(name, args))
        return

    print("未知命令：%s" % cmd, file=sys.stderr)
    print(__doc__)
    sys.exit(1)


if __name__ == "__main__":
    main()
