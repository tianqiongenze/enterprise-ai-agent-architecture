# -*- coding: utf-8 -*-
"""B 端控制台 SPA 资源加载器。

页面：概览 / 租户管理 / 指标注册中心 / 模型路由 / Capability权限矩阵 /
Memory管理 / 审批中心 / 任务中心 / 发布与灰度 / API测试
认证：JWT（登录后 localStorage），401 自动回登录页。设计：深色侧栏+浅色内容+青色主色。

工程纪律（修复记录）：SPA 的 HTML 曾经整块内嵌为本文件的 Python 字符串（333 行），
导致前端改动必须动 Python 源码、且无法被编辑器/工具链识别为 HTML。
现已拆分为真正的静态资源 ``static/console.html``，由本模块以包资源方式加载：
- 源码运行：``Path(__file__).parent / "static"``；
- pip 安装运行：pyproject 的 package-data 已把 ``*.html`` 打进 wheel。
加载失败显式抛错（fail-fast），绝不静默返回空白页。
"""
from __future__ import annotations

from pathlib import Path

_STATIC = Path(__file__).parent / "static" / "console.html"


def load_spa_html() -> str:
    """读取控制台 SPA 的 HTML（UTF-8）。文件缺失属于部署缺陷，直接抛错。"""
    if not _STATIC.exists():
        raise FileNotFoundError(
            f"控制台静态资源缺失: {_STATIC} —— 请确认 static/console.html 随包发布"
        )
    return _STATIC.read_text(encoding="utf-8")


SPA = load_spa_html()
