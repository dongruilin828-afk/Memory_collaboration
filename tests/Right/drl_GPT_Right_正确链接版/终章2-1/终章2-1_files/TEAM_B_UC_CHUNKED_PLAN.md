# 队员B：U-C全量分块运行改造方案

更新时间：2026-09-12

## 目标

将当前 U-C 单日冒烟入口改造成可断点、低内存、全年运行的 baseline 入口。

本任务只改运行工程，不改变已经冻结的数学定义。

## 冻结内容（禁止修改）

- U-C 单阶段鲁棒日前优化；
- load/PV 不确定性进入供需平衡；
- 价格保持确定；
- Gamma_load、Gamma_pv 独立；
- 0.95 residual quantile baseline；
- Top-10 压力情形；
- load/PV 压力集合笛卡尔组合；
- StressScenarioMaxCost 定义；
- `evaluate_cost()`；
- 预测文件、场景库、动态边界文件；
- C1/C2/C3 验收器。

## 当前代码与输入

主要代码：

- `scripts/c_run_uc.py`
- `src/optimization/uc_model.py`
- `src/optimization/forecast_interface.py`
- `src/c_dynamic_uncertainty.py`

正式输入：

- `results/c_forecasts/p_a_predictions.csv.gz`
- `results/c_forecasts/p_b_predictions.csv.gz`
- `results/c_forecasts/p_c_predictions.csv.gz`
- `results/c_scenarios/uc_residual_bounds_dynamic.csv.gz`
- `results/c_scenarios/b_dynamic_uncertainty_manifest.json`

当前单日输出：

- `results/c_uc/uc_dispatch.csv.gz`
- `results/c_uc/uc_manifest.json`
- `results/c_uc/uc_runtime.json`

## 必须完成的改造

### B1：全年日期循环

支持 2025-02-01 至 2025-12-31。

规则：

- 2025-02-01：只使用 U-A 冷启动，不调用 U-C 边界；
- 2025-02-02 至 2025-12-31：按日期调用动态 U-C 边界；
- 每个模型配置独立运行；
- 不读取 final_test 残差，边界由动态加载器按决策时刻选择。

建议命令：

```powershell
uv run --locked python scripts/c_run_uc.py `
  --model-id P-A `
  --config-id previous_week `
  --date all `
  --quantile 0.95 `
  --gamma-load 0.5 `
  --gamma-pv 0.5 `
  --resume
```

如果保留当前 `--date` 参数，新增 `--all` 也可以，但必须保持单日冒烟兼容。

### B2：分块写入

禁止将全年所有 dispatch 行保存在一个内存列表中。

推荐目录：

```text
results/c_uc/chunks/
  P-A_previous_week_2025-02-02.csv.gz
  P-A_previous_week_2025-02-03.csv.gz
  ...
```

每个日期完成后：

1. 生成当天所有压力情形的 144 个 slot；
2. 立即写入当天分块；
3. 计算当天各 stress_id 的成本；
4. 更新 checkpoint；
5. 清理当天内存。

最终合并为：

```text
results/c_uc/uc_dispatch.csv.gz
```

合并必须按块顺序进行，不能重新构造全年巨型 DataFrame。

### B3：断点续跑

新增：

```text
results/c_uc/uc_checkpoint.json
```

至少记录：

```json
{
  "model_id": "P-A",
  "config_id": "previous_week",
  "quantile": 0.95,
  "gamma_load": 0.5,
  "gamma_pv": 0.5,
  "completed_dates": [],
  "failed_dates": [],
  "last_completed_date": null
}
```

恢复时必须校验参数一致。

已完成日期不得重复计算，除非显式使用 `--restart`。

### B4：成本汇总

每个 stress_id 必须独立调用：

```python
evaluate_cost(dispatch_results=stress_frame)
```

每天取：

```StressScenarioMaxCost
```

全年只汇总每天的最大压力成本，不得把所有压力情形直接求和。

建议输出：

```text
results/c_uc/uc_daily_cost.csv
results/c_uc/uc_cost_summary.json
```

字段至少包括：

- date
- model_id
- config_id
- quantile
- gamma_load
- gamma_pv
- stress_scenario_max_cost
- robust_objective_cost
- runtime_seconds
- status

### B5：结果字段

最终 `uc_dispatch.csv.gz` 至少保留：

- stress_id
- date
- slot
- model_id
- config_id
- quantile
- gamma_load
- gamma_pv
- load_deviation
- pv_deviation
- planned_grid
- planned_charge
- planned_discharge
- actual_grid
- actual_charge
- actual_discharge
- soc
- normal_cost
- adjustment_cost
- emergency_cost
- total_cost

### B6：失败处理

单日失败时：

- 写入 `failed_dates`；
- 记录错误原因；
- 不删除已完成分块；
- 继续下一个日期；
- 最终状态为 `PARTIAL` 或 `FAILED`，不能伪装为 PASS。

## 推荐实现结构

建议在 `scripts/c_run_uc.py` 中拆分：

```python
load_forecast_for_day(...)
load_bounds_for_day(...)
run_one_day(...)
write_day_chunk(...)
update_checkpoint(...)
merge_chunks(...)
```

`src/optimization/uc_model.py` 只在确有必要时修改。优先只修改运行入口，避免触碰模型内核。

## 小规模验证顺序

不要直接跑全年。

### 测试1：单日

```powershell
uv run --locked python scripts/c_run_uc.py `
  --model-id P-A `
  --config-id previous_week `
  --date 2025-02-02 `
  --quantile 0.95 `
  --gamma-load 0.5 `
  --gamma-pv 0.5
```

完成标准：

- 121 个压力情形；
- 每个压力情形 144 个 slot；
- C3 验收仍为 PASS。

### 测试2：连续三日

运行 2025-02-02 至 2025-02-04。

检查：

- 生成三个独立 chunk；
- checkpoint 包含三个完成日期；
- 重新运行时跳过已完成日期；
- 合并结果行数正确；
- 内存不会随日期线性增长。

### 测试3：中断恢复

在第四日人为停止后重新运行：

- 前三日不得重复计算；
- 第四日可以继续；
- 参数不一致时必须拒绝恢复。

## 全量运行

每次只运行一个模型配置。

建议顺序：

1. P-A / previous_day
2. P-A / previous_week
3. P-A / rolling_median_7d
4. P-B / rolling_freeze_calendar_ols_v1
5. P-C / equal_weight_pa3_pb1

不要与队员A的 U-B 全量任务共用同一个 Python 进程。

## 完成标准

- 全部334天处理完成；
- 2月1日未错误调用 U-C；
- 每日压力情形完整；
- 分块文件可独立读取；
- checkpoint 可恢复；
- 每日成本均由 `evaluate_cost()` 计算；
- `StressScenarioMaxCost` 可复核；
- C3 验收 PASS；
- 输出 runtime、输入参数和失败日期；
- 不修改冻结模型定义。

## 不得提交的内容

- 不要提交半成品全量 dispatch；
- 不要把旧单日结果伪装为全年结果；
- 不要覆盖 U-A、U-B 或旧 Monthly Freeze 结果；
- 不要修改 B 的预测和场景生成逻辑；
- 不要修改 C 验收器来绕过失败。

## 交付给项目负责人

完成后报告：

- 修改文件；
- 新增文件；
- 分块数量；
- 完成日期数量；
- 失败日期；
- 最大内存；
- 总 runtime；
- C3 验收命令和结果；
- 是否可以进入全量 baseline 汇总。
