# 🍒 红豆 (Redou)

> **“红豆生南国，春来发几枝。愿君多采撷，此物最相思。”**

[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Status](https://img.shields.io/badge/Status-研发中-orange.svg)]()
[![Language](https://img.shields.io/badge/Language-English-blue.svg)](./README.md)

## 👁️ 项目愿景 (Vision)

**Redou (红豆) 旨在构建一个长程、联想式且具有情感权重的大模型外部记忆引擎。它不仅仅是存储数据，而是让 AI 像人一样，能够从碎片化的信息中“睹物思人”，实现知识的自我生长与深度共情。**

---

## 🛠️ 核心研发方向

### A. 联想式记忆索引 `[相思 / Xiangsi]`
* **研发点**：基于“知识图谱 + 向量”的混合索引。
* **目标**：实现“由物及人”的深度联想，超越简单的相似度匹配。

### B. 记忆的动态遗忘与整合 `[忘川 / Wangchuan]`
* **研发点**：仿生遗忘曲线算法 (Ebbinghaus Forgetting Curve)。
* **目标**：自动清理低价值噪声，将高频碎片固化为结构化条目。

### C. 情感权重机制 `[采撷 / Caidie]`
* **研发点**：存储记忆时记录 `Emotional_Score`（情感张量）。
* **目标**：优先提取对用户重要或具情感波动的记忆。

### D. 安全存储与私领 `[守藏 / Shoucang]`
* **研发点**：TEE (可信执行环境) 与加密存储技术。
* **目标**：确保用户的私密记忆“守而有道，藏而不露”。

### E. 生态适配与联结 `[结缕 / Jielu]`
* **研发点**：统一记忆接口协议与模型桥接。
* **目标**：将红豆丝滑地“联结”至 LangChain、LlamaIndex 等主流框架。

---

## 🚧 当前状态 (Status)

**本项目处于积极研发阶段。**
初始原型设计与算法实验正在进行中。

---

## 📅 路线图 (Roadmap)

- [ ] 记忆重要性建模
- [ ] 联想式检索架构实现
- [ ] 动态遗忘机制开发
- [ ] LLM 推理框架集成

---

## 🏗️ 项目结构 (Structure)

- `redou-core`: 核心算法实现 (`相思`, `忘川`, `采撷`)
- `redou-shoucang`: 安全存储与数据库适配
- `redou-jielu`: 框架适配插件与通讯协议

---

## 📜 许可协议 (License)

Apache License 2.0
