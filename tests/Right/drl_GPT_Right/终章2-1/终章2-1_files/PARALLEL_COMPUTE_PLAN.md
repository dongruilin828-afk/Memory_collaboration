# 三机并行计算与结果交接方案

更新时间：2026-09-12

本文件是三台计算机执行题目 C 四问实验时的统一说明。三台电脑均从同一份项目目录复制启动，因此代码、文档、输入数据和已有历史结果在启动时保持一致。三台电脑不共享运行时内存、checkpoint 或临时文件；只通过有线传输交换已完成的实验汇总。

## 1. 当前冻结共识

- 问题1至问题4均以题面附件为边界组织实验。
- U-A、U-B、U-C 已有可运行模型和验收基础。
- U-C alpha 搜索结果作为当前正式候选，但仍需通过题目对应实验验证其效果。
- 问题4保留 U-A、U-B、U-C 对照，并允许在组合方式冻结后加入 U-BC。
- U-BC 的定义、融合位置和参数范围属于本阶段待完成实验，不得在没有实验记录的情况下写成已确定结论。
- 充放电效率按充电和放电两个过程各 90% 执行，统一使用现有物理内核。

## 2. 复制基线和启动检查

三台电脑从同一目录复制：

```text
D:\zcy\two\math\github\Mathematical-Modelling-main\Mathematical-Modelling-main
```

复制必须在主目录停止所有运行任务后完成。每台电脑启动前检查：

1. 输入附件存在且未被修改；
2. `src/`、`scripts/`、`docs/` 和 `configs/` 已完整复制；
3. 复制版本中不包含正在写入的 checkpoint 或临时 shard；
4. 本机只写自己的 `results/parallel/computer_N/`；
5. 每个实验均有唯一 `experiment_id`；
6. 运行前保存本机基线清单 `baseline_manifest.json`，记录复制时间和关键输入文件哈希。

三台电脑可以拥有相同 Git 分支状态，也可以不再依赖 Git 版本号；有线交接以基线清单和实验 manifest 为准。

## 3. 题目级输入权限

优化决策输入和实际回放输入必须分开。预测或优化函数不得接收未来实际值、残差或最终测试结果。

| 任务 | 允许读取 | 禁止作为决策输入 |
|---|---|---|
| 问题1 | `附件1.xlsx`、附录1 | 附件2、附件3、附件4、全年数据 |
| 问题2 | `附件1.xlsx`、`附件2.xlsx`、附录1 | 附件3未来预报、附件4波动电价 |
| 问题3 | `附件1.xlsx`、`附件2.xlsx`、`附件3.xlsx`、附录1 | 附件4波动电价、发布时刻之后的信息 |
| 问题4-2 | `附件2.xlsx`、`附件4.xlsx`、附录1 | 附件3、问题3未来结果 |
| 问题4-3 | `附件2.xlsx`、`附件3.xlsx`、`附件4.xlsx`、附录1 | 未授权的未来数据和测试结果 |

实际值只能在日前决策完成后的顺序回放阶段读取。问题1不添加虚构日期；其他问题保留题面日期和 `slot`。

## 4. 三台电脑固定任务

### Computer 1：问题1和问题2

任务：

- 问题1 U-A 单日结果；
- 问题2 U-A 全年日前计划和实际回放；
- 问题2 U-B 对照；
- 问题2的预测模型和必要变量消融。

输出根目录：

```text
results/parallel/computer_1/
```

推荐实验编号：

```text
Q1_UA_ATTACHMENT1
Q2_UA_<model>_<config>
Q2_UB_<model>_<config>_<weight>
Q2_ABLATION_<description>
```

完成标准：能量平衡、SOC范围、成本复核、输入权限和运行时间检查全部通过。

### Computer 2：问题3动态预测更新

任务：

- 00:00预测的基准策略；
- 00:00+06:00更新；
- 00:00+06:00+12:00更新；
- 00:00+06:00+12:00+18:00更新；
- 根据计算资源选择最多八组更新时间消融，不要求八组全部全量运行；
- 记录调整购电、违约费用、超额调整费用、紧急购电和 SOC。

输出根目录：

```text
results/parallel/computer_2/
```

推荐实验编号：

```text
Q3_UPDATE_00
Q3_UPDATE_00_06
Q3_UPDATE_00_06_12
Q3_UPDATE_ALL
Q3_ABLATION_<description>
```

完成标准：每次更新只使用当时可见的预测；已执行时段不被后续预测改写；调整费用和紧急费用可人工复核。

### Computer 3：问题4和鲁棒/融合对照

任务：

- 问题4-2：波动电价下重算问题2；
- 问题4-3：波动电价下重算问题3；
- 保留 U-A、U-B、U-C 对照；
- 在 U-BC 组合定义记录后运行小规模和正式实验；
- 对当前 U-C alpha 候选进行题目对应复验。

输出根目录：

```text
results/parallel/computer_3/
```

推荐实验编号：

```text
Q4_2_UA_<model>
Q4_2_UB_<model>_<weight>
Q4_2_UC_<model>_<gamma>
Q4_3_UA_<model>_<update_policy>
Q4_3_UB_<model>_<update_policy>_<weight>
Q4_3_UC_<model>_<update_policy>_<gamma>
UBC_SMOKE_<definition>
UBC_FULL_<definition>
```

完成标准：问题4-2和问题4-3使用附件4价格；不污染问题2和问题3输入；所有结果通过对应验收后才进入比较表。

## 5. 每个实验必须记录的文件

每个实验目录统一为：

```text
<experiment_id>/
├── manifest.json
├── cost_summary.json
├── validation.json
├── runtime.json
└── run.log
```

逐时 dispatch、日 shard 和 checkpoint 可以留在本机，但不作为跨机迁移的主要文件。manifest 至少记录：

```text
experiment_id
problem_id
model_id
config_id
scenario_id
allowed_inputs
input_hashes
date_start
date_end
producer_machine
status
validation_status
```

统一成本字段：

```text
total_cost
energy_cost
adjustment_cost
emergency_cost
other_cost
```

## 6. 分块运行和有线交接

每台电脑只向自己的交换目录写入：

```text
wired_sync/incoming/computer_1/
wired_sync/incoming/computer_2/
wired_sync/incoming/computer_3/
```

实验完成后执行：

```text
uv run --locked python scripts/summarize_parallel_results.py
```

生成：

```text
results/parallel_summaries/computer_N_summary.csv
results/parallel_summaries/parallel_summary.csv
```

迁移时只复制 manifest、cost_summary、validation、runtime、汇总 CSV，以及失败实验的 run.log。除非需要审计，不迁移逐时 dispatch、daily shard 和 checkpoint。汇总程序不会读取这些大文件。

## 7. 失败和冲突处理

- 单个实验失败只标记 `status=FAILED`，不得伪装为 PASS；
- 失败实验仍需生成 manifest、runtime 和错误摘要；
- 同一 `experiment_id` 不得被第二台电脑覆盖；
- 汇总时发现重复 ID，保留两份来源并标记 `DUPLICATE_ID`，不自动选择；
- 只有 `validation_status=PASS` 的结果才能进入正式排名；
- 不允许用另一台电脑的中间文件补齐缺失结果。

## 8. 统一比较规则

同一问题内按照实际运行 `total_cost` 升序比较。问题1、问题2、问题3、问题4具有不同结算含义，默认分别排名，不直接把不同问题的成本混成一个全局排名。

预测 MAE、RMSE 等仅作辅助解释，不能替代成本排名。

## 9. 开始全量运行前的门禁

三台电脑均完成以下检查后，才可启动长时间任务：

1. 基线清单生成；
2. 输入权限检查通过；
3. 本机独立输出目录可写；
4. 单日或单月冒烟测试通过；
5. 验收脚本通过；
6. 汇总脚本能够从小文件生成总结果；
7. 任务编号不重复；
8. U-C alpha候选和 U-BC 实验的状态在 manifest 中正确标记。

