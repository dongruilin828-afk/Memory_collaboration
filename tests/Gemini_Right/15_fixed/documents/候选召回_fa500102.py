"""
候选召回与硬过滤主入口文件 (Main Entry)

为了防止代码臃肿，我们已经将大文件进行了优雅的拆分：
- mock_data.py: 存放高仿真的模拟景点数据。
- recall_pipeline.py: 存放核心的算法逻辑（冲突处理、7路召回、硬过滤、兜底经理）。
- test_cases.py: 存放 30 组不同类别的自动化测试用例，覆盖基础常规、进阶约束与极端兜底情况。

直接运行此文件即可一键跑通 30 个复杂测试用例，并在控制台输出格式化的测试报告！
"""

import sys
import os

# 确保能正确导入同目录下的模块
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from test_cases import run_all_test_profiles

if __name__ == "__main__":
    print("="*80)
    print("[开始] 欢迎来到智能旅行伴侣系统 - 核心召回引擎演示")
    print("="*80)
    
    # 运行全部 30 个画像用例的自动化压力测试
    run_all_test_profiles()