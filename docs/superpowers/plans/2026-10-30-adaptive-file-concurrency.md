# 已有文件自动并发 Implementation Plan

> **For agentic workers:** 用户已批准第一版，由当前 agent 直接执行；不创建分支、不提交。

**Goal:** 自动模式按 API 实际负载分配文件，逐步扩容、遇错降速，统一约束回退及重试，总上限 10。

**Architecture:** 增加仅使用标准库的批次内请求调度器；按接口和凭据在内存合并容量，文件级分配统计与请求级许可分开。网关可选注入调度器，每次真实请求单独取得/释放许可；未注入时维持现有行为。容量从 1 开始，稳定成功后加 1，429 降半并冷却、增加请求间隔，连续传输故障降速，永久错误停用相应账号或模型。

**Tech Stack:** Python threading.Condition、contextmanager、unittest、Tkinter、现有 API 网关。

**Spec:** 本聊天已确认的第一版建议；工作量仅作轻量估计，保留总结内容、文件编号、用户选定接口与调用顺序。

## Global Constraints

- 仅已有文件自动模式启用；手动并发、链接模式及其他 AI 的默认行为不变。
- 不增加测速或探活请求，不落盘凭据或其指纹，不批量删除文件。
- 等待主题选择不占 API 许可；取消能打断容量/冷却等待；降低容量不中断已有请求。
- 本批学习只在内存中生效，不推断不同 Key 的账号或项目关系，不写死厂商限额。
- 最终证据目录为 tests/test_results/05_文件自动并发最终验证_20261030，集中保留抓取与三种总结及必要证据；04 为补强前阶段记录。

## Review Focus

- 一个 API 自动容量可超过 1，总任务及请求数均不超过 10。
- 同接口同凭据重复配置共用容量；冷却、禁用接口不被新文件集中选择。
- 每次重试和回退均经过许可；HTTP 状态和 Retry-After 通过结构数据传递。
- JSON/内容问题不降低容量；401/402 停用账号，403/404 停用对应模型；连续 5xx/超时才降低容量。
- 取消不泄漏许可，不在锁中执行 UI 回调；手动模式不注入新调度器。

## Task 1: 调度器与 API 入口

**Files:** scripts/adaptive_concurrency.py、scripts/gemini_summarizer.py、gui/service.py、tests/test_adaptive_concurrency.py。

- [x] 实现容量、负载预留、请求许可、冷却、反馈及安全快照。
- [x] 网关每次真实请求接入可选调度器，保留默认路径，验证取消、错误、重试和回退。

## Task 2: 自动批次与验证

**Files:** gui/batch_processing.py、gui/batch_queue_panel.py、gui/batch_processing_dialog.py、README.md、对应测试。

- [x] 自动批次动态计算任务上限、按负载预留首选 API，并释放文件预留。
- [x] 显示实际运行数、动态上限和调整原因，更新说明。
- [x] 最终405项通过，0失败、0错误、0跳过；完整文件批次以一个本地HTTP接口处理四个文件，实际请求峰值2，生成三种总结共12份；指纹一致。
