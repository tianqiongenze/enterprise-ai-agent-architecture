# -*- coding: utf-8 -*-
"""持久化 (第五篇第3课)：内存存储统一端口实现，用于离线运行与测试。

真实企业生产可替换为 Postgres / Redis / S3 / 向量库。此处以内存实现
承载所有 Port（RunStore / MemoryStore 等）以便课程全离线可跑。
"""