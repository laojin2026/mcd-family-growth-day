#!/usr/bin/env python3
"""
一键发布到 GitHub（麦麦成长日 · 参赛用）
=====================================

用 GitHub REST API 完成：创建公开仓库 → 上传全部文件 → 设为公开。
零第三方依赖，仅用 Python 标准库。

用法：
    export GITHUB_TOKEN="你的Personal Access Token"
    python scripts/publish_github.py --repo mcd-family-growth-day

需要 Token 权限：
    - repo scope（创建仓库 + 推送内容）
    Token 获取地址：https://github.com/settings/tokens/new
    勾选 "public_repo" 即可（勾 repo 也行）

退出码：0 成功 / 1 参数或环境缺失 / 2 GitHub API 错误
"""

import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request

API = "https://api.github.com"
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 需要上传的文件（相对仓库根），全部使用 POSIX 路径分隔符
FILES = [
    ".gitignore",
    "README.md",
    "RESULTS.md",
    "CONTEST_DECLARATION.md",
    "MCP_INTEGRATION.md",
    "mcp-config.example.json",
    "workbuddy.md",
    "SKILL.md",
    "LICENSE",
    "scripts/mcd.py",
    "scripts/publish_github.py",
    "references/nutrition-planner.md",
    "references/nutrition-snapshot.json",
    "references/talk-scripts.md",
    "references/growth-log-format.md",
    "references/official-family-activities.md",
]

COMMIT_MSG = "feat: 麦麦成长日 - 亲子点单与沟通助手"


def get_token():
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        print("错误：未设置 GITHUB_TOKEN 环境变量。", file=sys.stderr)
        print("请先执行： export GITHUB_TOKEN=\"你的Token\"", file=sys.stderr)
        sys.exit(1)
    return token


def api(method, path, token, payload=None):
    url = path if path.startswith("http") else API + path
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": "Bearer " + token,
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
            "User-Agent": "mcd-family-growth-day-publisher",
        },
    )
    try:
        resp = urllib.request.urlopen(req, timeout=45)
        body = resp.read().decode("utf-8", "replace")
        return json.loads(body) if body.strip() else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        try:
            msg = json.loads(detail).get("message", detail)
        except Exception:
            msg = detail
        raise RuntimeError("GitHub API %s %s -> HTTP %s: %s" % (method, path, exc.code, msg))
    except urllib.error.URLError as exc:
        raise RuntimeError("网络错误：%s" % exc)


def get_login(token):
    return api("GET", "/user", token)["login"]


def repo_exists(token, owner, name):
    try:
        api("GET", "/repos/%s/%s" % (owner, name), token)
        return True
    except RuntimeError:
        return False


def create_repo(token, name):
    return api(
        "POST",
        "/user/repos",
        token,
        {
            "name": name,
            "description": "麦麦成长日 · 亲子点单与沟通助手 —— 基于麦当劳 MCP 的 Skill。把一顿麦当劳变成一次有营养依据、有沟通脚本、有成长记号的家庭互动。",
            "public": True,
            "auto_init": False,
            "has_issues": True,
            "has_wiki": False,
        },
    )


def file_to_tree_entry(rel_path):
    abs_path = os.path.join(REPO_ROOT, rel_path.replace("/", os.sep))
    with open(abs_path, "rb") as fh:
        content = fh.read()
    b64 = base64.b64encode(content).decode()
    mode = "100755" if rel_path.endswith(".py") else "100644"
    return {
        "path": rel_path,
        "mode": mode,
        "type": "blob",
        "content": b64,
    }


def push_tree(token, owner, name, branch, message):
    """用 Git Trees API 一次性提交全部文件（比逐个 PUT 快且可靠）"""
    entries = [file_to_tree_entry(p) for p in FILES]
    print("  准备上传 %d 个文件..." % len(entries))
    tree = api(
        "POST",
        "/repos/%s/%s/git/trees" % (owner, name),
        token,
        {"base_tree": None, "tree": entries},
    )
    commit = api(
        "POST",
        "/repos/%s/%s/git/commits" % (owner, name),
        token,
        {
            "message": message,
            "tree": tree["sha"],
            "parents": [],
        },
    )
    ref = api(
        "POST",
        "/repos/%s/%s/git/refs" % (owner, name),
        token,
        {"ref": "refs/heads/" + branch, "sha": commit["sha"]},
    )
    return commit["sha"], ref["ref"]


def main():
    repo_name = "mcd-family-growth-day"
    args = sys.argv[1:]
    if "--repo" in args:
        idx = args.index("--repo")
        if idx + 1 < len(args):
            repo_name = args[idx + 1]

    token = get_token()
    login = get_login(token)
    print("GitHub 账号：%s" % login)

    owner = login
    if repo_exists(token, owner, repo_name):
        print("仓库已存在：%s/%s（将直接推送文件）" % (owner, repo_name))
    else:
        print("创建公开仓库 %s/%s ..." % (owner, repo_name))
        create_repo(token, repo_name)
        time.sleep(2)

    sha, ref = push_tree(token, owner, repo_name, "main", COMMIT_MSG)
    print("  提交成功：%s" % sha[:8])

    url = "https://github.com/%s/%s" % (owner, repo_name)
    print()
    print("=" * 56)
    print("完成！仓库地址：")
    print("  " + url)
    print("=" * 56)
    print()
    print("接下来：")
    print("1. 打开上面的地址，确认文件都在、仓库是 Public")
    print("2. 到官方仓库提交报名 Issue：")
    print("   https://github.com/M-China/mcd-developer-innovation-challenge/issues")
    print()
    print("   Issue 标题（标题与正文之间不要有换行）：")
    print("   麦麦成长日 - 亲子点单与沟通助手")
    print()
    print("   Issue 正文（各字段之间不要有换行）：")
    print("   【参赛申请】")
    print("   项目名称：麦麦成长日 · 亲子点单与沟通助手")
    print("   项目地址：" + url)
    print("   项目简介：基于麦当劳MCP官方营养与菜单数据，为带孩子吃麦当劳的家庭一键配出能量蛋白质均衡的套餐，"
          "并生成亲子沟通四步法饭桌话术与成长记号，把一次随手点单变成一次高质量亲子互动。")


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as exc:
        print("失败：%s" % exc, file=sys.stderr)
        sys.exit(2)
