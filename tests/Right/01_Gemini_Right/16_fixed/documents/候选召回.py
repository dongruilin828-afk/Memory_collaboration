"""
候选召回与硬过滤主入口文件 (Main Entry)

为了防止代码臃肿，我们已经将大文件进行了优雅的拆分：
- mock_data.py: 存放高仿真的模拟景点数据。
- recall_pipeline.py: 存放核心的算法逻辑（冲突处理、7路召回、硬过滤、兜底经理）。
- test_cases.py: 存放各种用户极端与常规场景的测试用例。

直接运行此文件即可看到所有测试场景的演示！
"""

import sys
import os

# 确保能正确导入同目录下的模块
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from test_cases import test_scenario_1, test_scenario_2, test_scenario_3

if __name__ == "__main__":
    print("="*80)
    print("[开始] 欢迎来到智能旅行伴侣系统 - 核心召回引擎演示")
    print("="*80)
    
    # 跑测试用例 1: 极端苛刻场景
    test_scenario_1()
    
    # 跑测试用例 2: 普通高预算休闲游
    test_scenario_2()
    
    # 跑测试用例 3: 免费+特定区域的兜底挑战
    test_scenario_3()