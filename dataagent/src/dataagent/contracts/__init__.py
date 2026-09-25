# -*- coding: utf-8 -*-
"""统一契约层 (Contract Layer)。

定义贯穿全系统的领域契约：LogicalCall/Attempt、Run/Step/Event、
ToolSchema 三层契约、ContextProvider、Memory、Action、Eval 等。

设计原则 (SDD/DDD)：
- 领域通用语言 (Ubiquitous Language) 落在此处；
- 所有边界对象只用本包内的纯数据类/协议，不依赖任何基础设施实现；
- 保证 Invariant (不变量) 在契约层即可被静态检查。
"""

from . import model, runtime, tool  # noqa: F401

__all__ = ["model", "runtime", "tool"]