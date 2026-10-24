# Phase 2.2 Execution Plan

本文件基于当前仓库状态制定 Phase 2.2 执行计划。它只安排已冻结路线下的并行任务，不重新选择模型、接口或评价口径。

## 1. Current Status

- **当前 Git commit：** `682f3ac feat: freeze monthly forecast evaluation protocol and pipeline`
- **当前 branch：** `A-new1`
- **当前阶段：** Phase 2.2：问题2全年 U-A 调度集成
- **工作区状态：** 当前存在前一轮项目同步产生的未提交文档修改；本文件为本次新增计划文档，未修改代码、数据或结果。

### 已完成里程碑

- U-A 问题1确定性 LP、统一物理内核、SOC和成本模块完成。
- C 侧 S1 独立验收 PASS。
- P-A/P-B/P-C 预测长表生成，因果检查通过。
- Monthly Train-Freeze-Test Protocol、`freeze_id` 和 `split_manifest.json` 已实现。
- 2025-11 至 2025-12 `final_test` 已隔离。
- C 侧 Monthly Freeze 独立验收 PASS。
- 预测接口方案B冻结：A读取 `results/c_forecasts/` 通用长表。

### 当前风险

- 问题2全年 U-A 尚未实现，当前没有正式调度结果。
- `src/c_scenarios.py` 仍引用已删除的 `EVAL_START`，并使用旧 P-B 配置名；旧场景库仍含 rolling split 来源。
- U-B 场景权重、alpha、A-max融合实现、U-C参数和U-BC参数仍为 Pending。

## 2. ABC并行任务总览

| Task ID | 负责人 | 任务名称 | 目标 | 依赖 | 是否可并行 | 输出 |
| ------- | --- | ---- | -- | -- | ----- | -- |
| A1 | A | 预测接口接入 | 读取并筛选 P-A/P-B/P-C 冻结长表 | 已有 `results/c_forecasts/` 与 TEAM_INTERFACE | 可立即开始 | 输入适配代码、接口测试 |
| A2 | A | 问题2全年 U-A | 扩展日期循环、跨日 SOC 和节点结算 | A1接口确认 | A1完成后；与B1/B2并行 | `results/c_q2/` 调度、SOC、成本、runtime |
| A3 | A | 正式评价窗口 | 只评价 `monthly_test`、`final_test` | A2输出 | 依赖A2 | 窗口清单、评价汇总 |
| B1 | B | 场景接口迁移 | 清理 `EVAL_START`、旧 rolling split 和旧配置名 | 当前代码与旧场景结果 | 可立即开始 | 新场景入口、接口变更记录 |
| B2 | B | U-B残差场景库 | 仅用 `monthly_test` 残差构造候选场景 | B1、预测长表 | 与A1/A2并行 | 场景库、manifest、来源审计 |
| B3 | B | A-max接口准备 | 暴露7天、30天、A-max历史输入，不搜索权重 | 现有历史数据和冻结规则 | 可与A1/B1并行 | 特征接口说明、配置模板 |
| C1 | C | Q2 U-A验收框架 | 预先定义时间、SOC、能量、成本和runtime检查 | U-A规格和接口 | 可立即开始 | `docs/Q2_UA_VALIDATION_CHECKLIST.md` |
| C2 | C | 场景验收 | 检查残差来源、字段完整和最终测试隔离 | B2输出 | 等待B2 | 场景验收报告 |
| C3 | C | 文档同步 | 同步事实状态和交付记录 | 各任务交付信息 | 可立即开始 | 状态文档更新 |

状态说明：A1、B1、B3、C1、C3可立即开始；A2需A1接口确认；A3需A2结果；C2需B2输出。当前没有新增路线决策要求。

## 3. 队员A任务

### A1 数据接口接入

**负责人：** A  
**输入：** `results/c_forecasts/p_a_predictions.csv.gz`、`p_b_predictions.csv.gz`、`p_c_predictions.csv.gz`，标准实际数据。  
**任务：**

- 读取 `results/c_forecasts/`；
- 支持 P-A/P-B/P-C；
- 使用 `model_id + config_id + target + freeze_id` 筛选；
- 使用 `date + slot` 连接；
- 正式评价筛选 `split_role in {monthly_test, final_test}`。

**禁止：** 修改预测字段、自行重采样、修改B接口或读取训练期预测结果。  
**输出：** 输入适配代码、接口测试和字段检查日志。  
**完成标准：** 三类预测均能按冻结字段读取，连接键无重复或缺失，未来 `actual_value`/`residual` 未进入执行策略。

### A2 全年调度模型扩展

**负责人：** A  
**输入：** A1适配输入、U-A物理内核、标准实际数据。  
**任务：** 从问题1单日模型扩展日期循环、跨日SOC连续传递、全年运行和月度冻结预测调用。  
**输出：** `results/c_q2/` 下调度CSV、SOC轨迹、成本结果和runtime日志。  
**完成标准：** SOC不断裂；能量平衡通过；成本可人工复核；同一命令重复运行结果一致。

### A3 问题2评价窗口处理

**负责人：** A  
**输入：** A2调度结果、`split_manifest.json`。  
**任务：** 明确记录运行日期、正式评价日期和初始化日期；正式评价只汇总 `monthly_test` 与 `final_test`。  
**输出：** 窗口清单、评价汇总和过滤日志。  
**完成标准：** 训练阶段不进入正式预测评价，最终测试期不参与调参。若实现中出现冻结字段或日期定义冲突，停止并报告 `DECISION REQUIRED`。

## 4. 队员B任务

### B1 场景接口迁移

**负责人：** B  
**输入：** `src/c_scenarios.py`、旧场景结果、Monthly Freeze manifest。  
**任务：** 删除旧 `EVAL_START` 依赖，移除旧 rolling split 正式输入逻辑，对齐 `monthly_test`/`final_test` 角色和新冻结字段。  
**输出：** 新场景生成脚本、接口说明和新 manifest。  
**完成标准：** 不再把 `rolling_oos_pool_pending_final_split` 当正式输入；代码导入和接口检查通过。

### B2 新残差场景库

**负责人：** B  
**输入：** P-A/P-B/P-C预测长表。  
**任务：** 只使用 `monthly_test` 残差，禁止使用 `final_test`；每条场景记录 `scenario_id`、残差字段、`source_period`、`weight_id`。  
**输出：** 场景库、manifest和来源审计。  
**完成标准：** 字段完整、来源可追溯、无最终测试泄漏。权重不在本任务中确定，保持 Pending。

### B3 A-max多尺度预测准备

**负责人：** B  
**输入：** 可见历史数据和冻结评价规则。  
**任务：** 只建立7天、30天和 `A_max = min(可用历史长度, 90天)` 的接口与配置占位。  
**输出：** 特征接口说明、配置模板和可审计输入结构。  
**完成标准：** 不补造未来数据，不搜索或冻结 alpha 权重；alpha及搜索方法保持 Pending。

## 5. 队员C任务

### C1 问题2 U-A验收框架

**负责人：** C  
**输入：** U-A模型规格、TEAM_INTERFACE和A输出契约。  
**任务：** 预先定义 `date + slot` 完整性、SOC连续、能量平衡、成本复核和runtime检查。  
**输出：** `docs/Q2_UA_VALIDATION_CHECKLIST.md`。  
**完成标准：** A交付后可直接执行，且区分正式评价窗口和初始化日期。

### C2 B场景验收

**负责人：** C  
**输入：** B2场景库、manifest和预测长表。  
**任务：** 检查 residual 来源、最终测试隔离和场景字段完整性。  
**输出：** 场景验收报告。  
**完成标准：** 明确 PASS/NEED REVIEW，不修改B代码或场景数据。

### C3 文档同步

**负责人：** C  
**输入：** 各成员交付记录。  
**任务：** 检查并同步 PROJECT_STATUS、TEAM_PROGRESS、NEXT_PHASE_PLAN、TEAM_INTERFACE 的事实状态。  
**输出：** 文档变更记录。  
**完成标准：** 只同步事实，不修改数学路线和冻结决策。

## 6. 任务依赖关系图

```text
A1 预测接口接入 ───────┐
                       ├─> A2 问题2全年U-A ──> A3 正式评价窗口 ──> C1/C验收
B1 场景接口迁移 ─> B2 场景库 ────────────────> C2 场景验收 ──> U-B准备
B3 A-max接口准备 ───────────────────────────────┘

A2 + B2 + C1/C2/C3
          ↓
     U-B正式实验（后续阶段）
```

B1、B3、C1、C3无需等待A完成；A2和C2分别依赖接口/场景交付。

## 7. 当前 Decision Required

当前冻结范围内没有需要重新选择的方案。以下是后续仍未冻结的参数，不能在本阶段擅自决定：

### Decision 1：U-B场景权重

**问题：** 选择何种场景权重。  
**当前状态：** Pending。  
**选项：** 等权、经验频率、时间衰减或其他经验证方案。  
**影响：** U-B期望成本、风险表现和运行时间。  
**推荐等待阶段：** B2场景库完成并经过验证期实验后。

### Decision 2：alpha与权重搜索

**问题：** 多尺度融合的具体 alpha 和搜索方法。  
**当前状态：** Pending。  
**选项：** 待验证实验确定，当前只保留接口。  
**影响：** P-A/P-B/P-C预测值和后续调度输入。  
**推荐等待阶段：** B3接口完成、评价实验设计完成后。

### Decision 3：U-C与U-BC参数

**问题：** Gamma、lambda等风险参数。  
**当前状态：** Pending。  
**选项：** 待U-B/U-C独立验证后比较。  
**影响：** 鲁棒程度、成本和模型排序。  
**推荐等待阶段：** U-B和U-C独立实验完成后。

## 8. Commit前检查清单

- [ ] 是否修改冻结接口？若是，必须先记录接口变更并同步团队。
- [ ] 是否产生新的数据或结果文件？必须记录来源、命令和版本。
- [ ] 是否需要C侧独立验收？所有A调度和B场景正式结果都需要。
- [ ] 是否需要更新 `DECISION_LOG.md`？只有冻结决策或接口变化时更新。
- [ ] 是否确认正式评价只包含 `monthly_test` 和 `final_test`？
- [ ] 是否确认U-B残差未使用 `final_test`？
- [ ] 是否确认未生成 `monthly_train` 预测结果？
- [ ] 是否通过 `git diff --check`、接口检查和相应验证？
- [ ] 是否可以commit？只有上述检查完成且C验收通过后才可以。

本计划本身不代表任务已完成，也不代表可以跳过A/B/C交付和C侧验收。
