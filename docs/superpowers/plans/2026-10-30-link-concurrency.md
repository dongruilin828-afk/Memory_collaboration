# 对话链接并发上限调整 Implementation Plan

> **For agentic workers:** 本次由当前 agent 直接执行，用户已确认设为 10；不创建分支、不执行 commit。

**Goal:** 对话链接支持 1～10 并发，默认仍为 3。

**Architecture:** 在现有抓取模块分别定义默认并发和最大并发，供批次校验及两个界面入口复用。保留当前抓取与总结分开调度、取消、排序和登录协调逻辑。

**Tech Stack:** Python、Tkinter、asyncio、unittest、Playwright。

**Spec:** 本聊天已确认的方案：上限 10，默认 3，保留用户现有改动。

## Global Constraints

- 不创建分支，不提交或推送，不批量删除，不覆盖以前的测试结果。
- 保留已有登录视口相关修改，不修改各平台解析器、媒体读取器或总结规则。
- 文件模式仍保持自动及 1～10 并发。
- 最终证据统一保存到 tests/test_results 下带递增序号的中文新目录，包含抓取及三种总结产物；受控网页和模拟网关如实标注。

## Review Focus

- 默认调用仍为 3，不能因最大值改为 10 而打开 10 页。
- 1、4、10 均可用；0、11、布尔值和非整数仍拒绝。
- 两个界面入口均能选择并传入 10；手输越界值被拒绝，运行时禁用编辑。
- 10 个并发任务保留消息与文件归属，不超过所选数量，不受后续批次叠加影响。
- 文件模式、登录协调、取消和恢复继续通过已有回归。

## Task 1: 扩大链接并发范围并验证

**Files:** gui/batch_capture.py、gui/batch_processing.py、gui/batch_processing_dialog.py、gui/batch_capture_dialog.py、scripts/batch_capture.py、README.md，以及对应 tests/test_batch*.py。

**Interfaces:** 保留 capture_links、BatchPlan 和 GUI 提交回调签名；新默认/上限常量由 gui.batch_capture 提供。

- [x] 调整校验、调度及两个入口；旧抓取入口复用现有原生 Spinbox 交互。
- [x] 更新已有边界、默认值、真实并发和 GUI 回归，补足 10 并发验证。
- [x] 运行受影响的离线及受控浏览器测试，统一保存最终证据：98 项通过，0 失败、0 错误、0 跳过。
- [x] 核对 diff、已有改动及结果完整性；证据位于 tests/test_results/03_链接十并发上限验证_20261030。
