# 🍒 红豆 (Redou)

> **“红豆生南国，春来发几枝。愿君多采撷，此物最相思。”**

[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Status](https://img.shields.io/badge/Status-研发中-orange.svg)]()
[![Language](https://img.shields.io/badge/Language-English-blue.svg)](./README.md)

## 👁️ 项目愿景 (Vision)

**Redou (红豆) 旨在构建一个长程、联想式且具有情感权重的大模型外部记忆引擎。它不仅仅是存储数据，而是让 AI 像人一样，能够从碎片化的信息中“睹物思人”，实现知识的自我生长与深度共情。**

---

## 🛠️ 核心研发方向 (Technical Roadmap)

### A. 联想式记忆索引 (Associative Indexing)
传统的 RAG（检索增强生成）靠向量相似度，而“相思”是跳跃式的。
* **研发点：** 开发一种基于“知识图谱 + 向量”的混合索引。
* **目标：** 当用户提到 A 时，Redou 不仅能检索到 A，还能通过逻辑或情感关联拉取到 B，实现“由物及人”的深度联想。

### B. 记忆的动态遗忘与整合 (Consolidation & Forgetting)
人的记忆会模糊，也会因为重复而深刻。
* **研发点：** 仿生遗忘曲线算法（Ebbinghaus Forgetting Curve）。
* **目标：** 自动清理低频、低价值的噪声信息；将多次出现的碎片信息“固化”为结构化的知识条目。

### C. 情感权重机制 (Emotional Weighting)
“此物最相思”——红豆代表的是有感情的记忆。
* **研发点：** 在存储 Memory 时，额外记录一个 `Emotional_Score`（情感张量）。
* **目标：** 优先提取那些对用户重要、具有情绪波动或关键决策意义的记忆，而非仅仅是最近的对话。

### D. 隐私保护的“私人领地” (TEE & Encryption)
既然是相思之物，必然涉及隐私。
* **研发点：** 基于本地端侧存储或 TEE（可信执行环境）的记忆加密。
* **目标：** 确保用户的“心事”只有 AI 知道，且不可被第三方或开发者窃取。

---

## 🏗️ 模块化设计 (Modular Design)

* **`Redou-Core`**：核心算法（记忆写入、更新、检索）。
* **`Redou-DB`**：适配各种向量数据库（Milvus, Pinecone, DuckDB）的接口。
* **`Redou-Bridge`**：适配主流 LLM 框架（LangChain, LlamaIndex）的插件。

---

## 📅 路线图 (Roadmap)

- [ ] **V0.1**: 核心存储架构设计与基础向量检索实现。
- [ ] **V0.5**: 引入知识图谱关联与情感得分权重。
- [ ] **V1.0**: 完整的遗忘曲线管理与 TEE 隐私保护部署。

---

## 📜 许可协议 (License)

本项目采用 **Apache License 2.0** 协议。

---
[查看英文版 (English Version)](./README.md)
