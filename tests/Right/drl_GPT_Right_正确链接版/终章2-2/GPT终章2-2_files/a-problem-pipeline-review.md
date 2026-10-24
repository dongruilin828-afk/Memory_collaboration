# A 题 pipeline 快速试跑复盘

## 已走通

1. `PDF → problem-analysis`：完整读取四页题面并识别四问依赖。
2. `附件 → data-analysis`：读取环境温湿、收缩半径和结果模板结构。
3. `model-selection`：比较显式差分、隐式有限体积、半解析和 ALE 模型。
4. `mathematical-modeling`：形成固定半径控制方程、边界和问题 4 移动坐标方向。
5. `scripts → results`：可复现脚本生成 JSON baseline。
6. `paper-writing`：形成问题、方法、结果、限制的草稿证据链。
7. `competition-review`：主动标出传质边界、终止时间和移动边界三项阻断问题。
8. `Git → GitHub`：提交后推送并比较本地与远端 SHA。

## 暴露的问题

- Windows 终端默认编码会使中文路径和字段在控制台显示乱码，但 Python 读写数据本身正确。
- 当前 `uv` 不可调用，试跑使用系统 Python；正式环境复现仍需补齐 `uv sync`。
- 总流程的 `data-analysis` 和 `visualization` 路由存在，但快速任务没有自动生成统一的赛题工作目录或命名约定。
- 显式逐秒 Python 循环不适合 72 h 非线性求解，应尽快升级为向量化隐式方案。
- pipeline 能阻止把未验证数值当成最终结果，这是本次试跑中最重要的质量门槛。

## 建议改进

1. 后续增加一个轻量赛题初始化脚本，只创建 `docs/<problem>`、运行入口和结果清单，不增加框架。
2. 在 `code-review` Skill 中明确加入守恒误差与网格收敛检查。
3. 在提交检查表中加入“题目要求的 Excel 模板是否逐单元格核对”。
4. 团队统一 UTF-8 终端和可调用的 `uv` 环境。
