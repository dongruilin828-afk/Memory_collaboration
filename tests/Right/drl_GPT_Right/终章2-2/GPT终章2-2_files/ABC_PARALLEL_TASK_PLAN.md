# ABC Parallel Task Plan

更新时间：2026-09-11  
适用阶段：Phase 2.2 收口后、U-B/U-C/U-BC 扩展实验准备阶段

## 1. 当前共同基线

### 已完成

- 新版 rolling/final 预测输入已通过 C 侧门禁；
- B2 残差场景库已通过 C2 独立验收；
- A 已完成334天 U-A 调度；
- C1（U-A）和 C2（场景库）均为 `PASS`；
- `evaluate_cost()` 和 U-A `cost_summary.csv` 已生成；
- U-A、U-B、U-C、U-BC 统一以实际 `total_cost` 作为最终比较指标。

### 当前尚未完成

- U-B 正式调度入口；
- U-C 正式鲁棒调度入口；
- U-BC 组合调度入口；
- 统一多场景实验运行器；
- 扩展模型独立验收报告。

### 当前实验参数状态

以下是第一轮实验预设，允许后续进行对照调整，不等同于最终模型选择：

- U-B：B0～B4风险分级及三组等级权重；
- U-C：90%/95%/99%残差边界，独立 `Gamma_load`、`Gamma_pv`，第一轮取相同值；
- U-BC：`lambda ∈ {0, 0.25, 0.5, 0.75, 1}`；
- 2月1日冷启动：只使用 U-A；
- alpha及多尺度融合：仍为 Pending。

## 2. 三人并行总览

| 阶段 | A：优化与求解 | B：数据与场景 | C：验证与文档 | 共享接口 |
|---|---|---|---|---|
| S0 参数落地 | 编写 U-B/U-C 模型规格和配置读取接口，不求解 | 生成 B0-B4 风险等级、等级内场景映射、U-C正负残差边界表 | 将参数定义、边界规则和状态写入验证清单 | `scenario_id`、`risk_level`、`weight_id`、边界字段 |
| S1 单模型冒烟 | 实现 U-B、U-C 最小可运行入口，保留 U-A基线 | 校验场景可用时间、风险分级和边界统计 | 建立 U-B/U-C 独立验收脚本 | 预测→场景/集合→调度→`evaluate_cost()` |
| S2 U-B/U-C核验 | 运行小规模或单配置实验并记录 runtime | 提供来源审计、配置 manifest和参数网格 | 独立复核物理、成本、因果和参数追溯 | 结果长表、成本摘要、验证 JSON |
| S3 U-BC准备 | 在 U-B/U-C分别通过后实现组合入口 | 提供场景与鲁棒集合连接信息 | 建立组合模型验收清单 | `ExpectedCost`、`RobustCost`、`lambda` |
| S4 扩展实验 | 按实验矩阵运行并输出结果 | 维护输入版本、哈希和实验配置 | 汇总成本排名、消融和论文表格 | `experiment_id`、`cost_summary.csv` |

## 3. 队员A任务

### A0：接口和模型规格

负责人：A  
输入：`docs/SCENARIO_INTERFACE.md`、`results/c_scenarios/`、当前 U-A物理内核  
输出：`docs/U_B_MODEL_SPEC.md`、`docs/U_C_MODEL_SPEC.md`、扩展配置字段说明  
完成标准：明确变量、目标、约束、场景非预见性、Gamma预算和输出字段；不写入未决定参数。  
依赖：B0风险字段和 U-C边界字段的接口名称确认。

### A1：U-B场景优化入口

建议文件：

```text
src/optimization/scenario_interface.py
src/optimization/ub_model.py
scripts/c_run_ub.py
```

任务：

- 读取 B0～B4场景及等级权重；
- 应用 `available_from <= decision_time`；
- 保持日前计划与场景运行的非预见性；
- 复用 `physics.py`；
- 输出场景级调度和成本；
- 所有结果调用 `evaluate_cost()`。

依赖：B完成风险分级和权重配置文件；权重方案只能读取配置，不能写死在模型中。  
暂不做：final_test残差、旧monthly_test残差、U-C约束、U-BC组合。

### A2：U-C鲁棒入口

建议文件：

```text
src/optimization/robust_model.py
scripts/c_run_uc.py
```

任务：

- 读取按 `target × slot` 的正负残差分位边界；
- 只对负荷和光伏施加不确定性；
- 价格保持确定性预测；
- 负荷和光伏使用独立预算；
- 计算压力情形实际运行成本最大值作为 `RobustCost`；
- 所有结果调用 `evaluate_cost()`。

依赖：B提供边界表；Gamma网格配置。  
停止条件：边界缺失方向未按 Frozen规则记录，或鲁棒对应形式仍有多种解释时停止并报告。

### A3：U-BC组合入口

建议文件：

```text
src/optimization/ubc_model.py
scripts/c_run_ubc.py
```

任务：

- 读取 U-B 的期望成本；
- 读取 U-C 的 RobustCost；
- 使用相同价格、物理约束和成本函数；
- 仅通过 lambda控制目标权衡；
- 输出期望成本、鲁棒成本、组合目标和实际总成本。

依赖：U-B和U-C分别完成并通过 C 侧验收；不得提前实现最终组合结果。

### A4：统一实验运行器

建议文件：

```text
src/optimization/experiment_runner.py
scripts/run_model_experiment.py
```

统一输入：

```text
model, scenario, weight_id, alpha, gamma_load, gamma_pv, lambda
```

统一输出：

```text
调度结果、成本分项、runtime、experiment_id、验证状态
```

该入口必须调用同一个 `evaluate_cost()`，禁止为 U-B/U-C/U-BC 新建成本公式。

## 4. 队员B任务

### B1：B0-B4风险分级

负责人：B  
输入：`results/c_scenarios/scenario_library.csv.gz`  
输出建议：

```text
results/c_scenarios/scenario_risk_scores.csv
results/c_scenarios/scenario_risk_levels.csv
```

完成标准：

- 每个完整日 scenario 计算三类累计绝对残差；
- 各目标分别按 `x / max(x)` 归一化；
- 使用 `0.4/0.4/0.2` 形成联合风险；
- 按五分位划分 B0～B4；
- 边界归入较低风险等级；
- 记录风险指标、分位点和等级。

风险边界：不得使用 `final_test`，不得混入旧 `monthly_test`。

### B2：场景权重配置

输出建议：

```text
results/c_scenarios/ub_weight_configs.csv
```

配置三组已给定的权重方案，并在等级内部等权分配到具体 scenario。权重必须可替换，不能硬编码在 U-B 求解器中。

### B3：U-C非对称残差边界

输出建议：

```text
results/c_scenarios/uc_residual_bounds.csv
results/c_scenarios/uc_boundary_audit.json
```

完成标准：

- 按 `target × slot` 分开处理正、负残差；
- 保存90%、95%、99%候选边界；
- 缺少正方向时边界为0；
- 缺少负方向时边界为0；
- 记录缺失方向、计数和最终边界；
- 不跨 slot、不使用全局分布补齐。

### B4：输入版本和哈希维护

维护：

- 场景来源文件；
- 预测源文件哈希；
- 风险分级版本；
- U-C边界版本；
- 配置文件和运行命令。

## 5. 队员C任务

### C1：参数与接口验收

输出：

```text
docs/UB_UC_PARAMETER_CHECKLIST.md
```

检查：

- B0～B4定义和分位边界；
- 等级内 scenario 等权；
- 三组 B等级权重；
- Gamma_load/Gamma_pv独立；
- U-C价格保持确定；
- 2月1日只使用 U-A。

### C2：U-B独立验收

建议输出：

```text
results/c_validation/ub_acceptance.json
docs/UB_C_ACCEPTANCE_REPORT.md
```

检查：

- scenario来源和 `available_from`；
- 评分等级和权重映射；
- 非预见性；
- 能量平衡；
- SOC边界和连续性；
- 成本复核；
- `evaluate_cost()`调用和结果可追溯。

### C3：U-C独立验收

建议输出：

```text
results/c_validation/uc_acceptance.json
docs/UC_ACCEPTANCE_REPORT.md
```

检查：

- 正负边界和缺失方向日志；
- 负荷/光伏独立Gamma预算；
- 价格未被加入不确定集合；
- 压力场景实际成本最大值；
- 物理和费用复核。

### C4：结果和文档同步

C维护：

- `results/model_evaluation/cost_summary.csv`；
- 每次实验的配置、命令和版本；
- U-A/U-B/U-C/U-BC对照表；
- 最终排名前的审计材料。

## 6. 依赖与同步节点

```text
B风险分级 + U-C边界
          ↓
      A接口适配
          ↓
   A实现 U-B / U-C
          ↓
       C验收
          ↓
   U-BC组合实现
          ↓
   C验收与扩展实验
```

可以并行：

- B进行风险分级时，A可编写接口和模型规格；
- B生成边界表时，C可编写验收清单；
- A实现 U-B 时，B可维护配置和来源审计；
- A实现 U-C 时，C可准备鲁棒性与成本核验。

必须等待：

- 没有 B 的风险/边界正式文件，A不能运行正式 U-B/U-C；
- 没有 U-B和U-C各自 C 验收，不能实现正式 U-BC 结果比较；
- 没有参数定义，不能进行参数网格实验或最终排名。

## 7. 当前仍需保持 Pending 的内容

- alpha及多尺度预测融合方式；
- B0-B4三组权重方案之外的扩展权重；
- Gamma取值和分位数组合的最终选择；
- lambda最终选择；
- 最终预测模型排名；
- 是否因 LP退化证据补充 MILP。

## 8. 统一停止规则

任一成员遇到以下情况必须停止对应分支并上报：

- 缺少参数或参数含义不明确；
- 需要使用 `final_test` 或未来总览；
- 需要改变冻结数据字段、时间口径或物理约束；
- 成本无法通过 `evaluate_cost()`复核；
- U-B/U-C/U-BC之间出现第二套成本计算；
- 结果缺少输入版本、命令、哈希或验证文件。

在所有扩展实验完成前，不生成 `final_ranking.csv`，不写最终推荐结论。
