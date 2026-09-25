# -*- coding: utf-8 -*-
"""测试根 conftest：把服务层与内核 src 加入导入路径，保证从仓库根运行可收集。"""
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
for p in ("services/src", "dataagent/src"):
    sys.path.insert(0, os.path.join(ROOT, p))