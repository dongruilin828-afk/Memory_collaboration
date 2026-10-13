from mock_data import MOCK_DB, COST_MAP
from recall_pipeline import run_recall_pipeline

TEST_PROFILES = [
    # ==========================================
    # 类别 A：基础常规需求 (1-10组，应该非常顺利拿到丰富结果)
    # ==========================================
    {"city": "上海", "travel_goal": "现代地标与都市景观", "travel_style": "休闲游", "constraints": {"max_cost": "high", "weather": "sunny", "group": "couple", "preferred_areas": [], "must_see": [], "must_avoid": [], "keywords": []}},
    {"city": "上海", "travel_goal": "主题游乐与动物园", "travel_style": "特种兵打卡", "constraints": {"max_cost": "high", "weather": "sunny", "group": "friends", "preferred_areas": ["浦东"], "must_see": [], "must_avoid": [], "keywords": ["游乐", "花车"]}},
    {"city": "上海", "travel_goal": "艺文与科教空间", "travel_style": "休闲游", "constraints": {"max_cost": "low", "weather": "sunny", "group": "solo", "preferred_areas": ["黄浦"], "must_see": ["上海博物馆"], "must_avoid": [], "keywords": ["历史"]}},
    {"city": "上海", "travel_goal": "逛吃与商业街区", "travel_style": "休闲游", "constraints": {"max_cost": "medium", "weather": "sunny", "group": "friends", "preferred_areas": ["徐汇", "黄浦"], "must_see": [], "must_avoid": [], "keywords": ["网红", "咖啡"]}},
    {"city": "上海", "travel_goal": "历史与宗教古迹", "travel_style": "休闲游", "constraints": {"max_cost": "low", "weather": "sunny", "group": "elderly", "preferred_areas": [], "must_see": [], "must_avoid": [], "keywords": ["祈福"]}},
    {"city": "上海", "travel_goal": "自然风光与公园", "travel_style": "休闲游", "constraints": {"max_cost": "free", "weather": "sunny", "group": "parent_child", "preferred_areas": [], "must_see": [], "must_avoid": [], "keywords": ["露营", "骑行"]}},
    {"city": "上海", "travel_goal": "现代地标与都市景观", "travel_style": "特种兵打卡", "constraints": {"max_cost": "medium", "weather": "sunny", "group": "solo", "preferred_areas": ["浦东", "黄浦"], "must_see": ["外滩"], "must_avoid": [], "keywords": ["夜景"]}},
    {"city": "上海", "travel_goal": "演出与休闲夜生活", "travel_style": "休闲游", "constraints": {"max_cost": "high", "weather": "sunny", "group": "couple", "preferred_areas": ["静安", "黄浦"], "must_see": [], "must_avoid": [], "keywords": ["杂技", "酒吧"]}},
    {"city": "上海", "travel_goal": "艺文与科教空间", "travel_style": "休闲游", "constraints": {"max_cost": "medium", "weather": "sunny", "group": "parent_child", "preferred_areas": ["浦东"], "must_see": [], "must_avoid": [], "keywords": ["宇宙", "科普"]}},
    {"city": "上海", "travel_goal": "逛吃与商业街区", "travel_style": "休闲游", "constraints": {"max_cost": "high", "weather": "sunny", "group": "friends", "preferred_areas": ["黄浦"], "must_see": ["新天地"], "must_avoid": [], "keywords": []}},

    # ==========================================
    # 类别 B：进阶约束限制 (11-20组，旨在触发你的硬过滤策略，如避雷、天气、人群)
    # ==========================================
    # 11: 带老人，但选了高强度大类，测试体力过滤
    {"city": "上海", "travel_goal": "户外运动与康养度假", "travel_style": "休闲游", "constraints": {"max_cost": "medium", "weather": "sunny", "group": "elderly", "preferred_areas": ["松江"], "must_see": [], "must_avoid": [], "keywords": []}},
    # 12: 下雨天选了纯室外大类，测试天气过滤
    {"city": "上海", "travel_goal": "自然风光与公园", "travel_style": "休闲游", "constraints": {"max_cost": "low", "weather": "rain", "group": "friends", "preferred_areas": [], "must_see": [], "must_avoid": [], "keywords": []}},
    # 13: 测试明确的 must_avoid 避雷标签
    {"city": "上海", "travel_goal": "现代地标与都市景观", "travel_style": "特种兵打卡", "constraints": {"max_cost": "high", "weather": "sunny", "group": "solo", "preferred_areas": [], "must_see": [], "must_avoid": ["排队久"], "keywords": []}},
    # 14: 预算极低，过滤高消费地标
    {"city": "上海", "travel_goal": "演出与休闲夜生活", "travel_style": "休闲游", "constraints": {"max_cost": "free", "weather": "sunny", "group": "friends", "preferred_areas": [], "must_see": [], "must_avoid": [], "keywords": []}},
    # 15: 强制访问正处于闭馆的场馆，测试 is_closed 过滤
    {"city": "上海", "travel_goal": "历史与宗教古迹", "travel_style": "休闲游", "constraints": {"max_cost": "low", "weather": "sunny", "group": "solo", "preferred_areas": [], "must_see": ["中共一大纪念馆"], "must_avoid": [], "keywords": []}},
    # 16: 雨天特种兵打卡，测试雨天高危过滤
    {"city": "上海", "travel_goal": "主题游乐与动物园", "travel_style": "特种兵打卡", "constraints": {"max_cost": "high", "weather": "rain", "group": "friends", "preferred_areas": [], "must_see": ["上海迪士尼乐园"], "must_avoid": [], "keywords": []}},
    # 17: 避开商业化严重的地方
    {"city": "上海", "travel_goal": "历史与宗教古迹", "travel_style": "休闲游", "constraints": {"max_cost": "medium", "weather": "sunny", "group": "couple", "preferred_areas": ["黄浦"], "must_see": [], "must_avoid": ["商业化严重"], "keywords": []}},
    # 18: 恐高人群测试
    {"city": "上海", "travel_goal": "现代地标与都市景观", "travel_style": "休闲游", "constraints": {"max_cost": "high", "weather": "sunny", "group": "solo", "preferred_areas": ["浦东"], "must_see": [], "must_avoid": ["恐高"], "keywords": []}},
    # 19: 带小孩去夜场演出，可能因为没交集而被剔除
    {"city": "上海", "travel_goal": "演出与休闲夜生活", "travel_style": "休闲游", "constraints": {"max_cost": "high", "weather": "sunny", "group": "parent_child", "preferred_areas": [], "must_see": [], "must_avoid": [], "keywords": []}},
    # 20: 避免去暴晒的地方
    {"city": "上海", "travel_goal": "主题游乐与动物园", "travel_style": "休闲游", "constraints": {"max_cost": "medium", "weather": "sunny", "group": "friends", "preferred_areas": [], "must_see": [], "must_avoid": ["暴晒"], "keywords": []}},

    # ==========================================
    # 类别 C：极端条件与兜底挑战 (21-30组，旨在触发你代码中的 resolve_conflicts 和 fallback_manager)
    # ==========================================
    # 21: [冲突处理测试] 天气下雨，且主偏好是户外自然风光
    {"city": "上海", "travel_goal": "自然风光与公园", "travel_style": "休闲游", "constraints": {"max_cost": "medium", "weather": "rain", "group": "couple", "preferred_areas": [], "must_see": [], "must_avoid": [], "keywords": []}},
    # 22: [冲突处理测试] 同行有老人，但是要“特种兵打卡”
    {"city": "上海", "travel_goal": "现代地标与都市景观", "travel_style": "特种兵打卡", "constraints": {"max_cost": "medium", "weather": "sunny", "group": "elderly", "preferred_areas": [], "must_see": [], "must_avoid": [], "keywords": []}},
    # 23: [冲突处理测试] 要去主题乐园，但是预算设成了“免费”
    {"city": "上海", "travel_goal": "主题游乐与动物园", "travel_style": "休闲游", "constraints": {"max_cost": "free", "weather": "sunny", "group": "parent_child", "preferred_areas": [], "must_see": [], "must_avoid": [], "keywords": []}},
    # 24: [兜底挑战] 将区域卡死在一个很小的偏远区，预算又极低
    {"city": "上海", "travel_goal": "现代地标与都市景观", "travel_style": "休闲游", "constraints": {"max_cost": "free", "weather": "sunny", "group": "solo", "preferred_areas": ["奉贤", "崇明"], "must_see": [], "must_avoid": [], "keywords": []}},
    # 25: [兜底挑战] 雨天要去松江区找室内免费景点 (几乎没有)
    {"city": "上海", "travel_goal": "艺文与科教空间", "travel_style": "休闲游", "constraints": {"max_cost": "free", "weather": "rain", "group": "friends", "preferred_areas": ["松江"], "must_see": [], "must_avoid": [], "keywords": []}},
    # 26: [综合极端] 预算 free + 避雷人流密集 + 避雷室外 + 特定偏好
    {"city": "上海", "travel_goal": "逛吃与商业街区", "travel_style": "休闲游", "constraints": {"max_cost": "free", "weather": "rain", "group": "couple", "preferred_areas": ["静安"], "must_see": [], "must_avoid": ["人流密集", "人多拥挤"], "keywords": []}},
    # 27: [兜底挑战] 全避雷测试，几乎把所有 tag 都写进 must_avoid
    {"city": "上海", "travel_goal": "主题游乐与动物园", "travel_style": "休闲游", "constraints": {"max_cost": "high", "weather": "sunny", "group": "friends", "preferred_areas": [], "must_see": [], "must_avoid": ["排队久", "门票贵", "体力消耗极大", "暴晒"], "keywords": []}},
    # 28: [冲突调解] 老人出游 + 雨天 + 特种兵打卡 + 自然风光
    {"city": "上海", "travel_goal": "自然风光与公园", "travel_style": "特种兵打卡", "constraints": {"max_cost": "medium", "weather": "rain", "group": "elderly", "preferred_areas": [], "must_see": [], "must_avoid": [], "keywords": []}},
    # 29: [兜底挑战] 预算极低，却要求只能在浦东新区进行演出活动
    {"city": "上海", "travel_goal": "演出与休闲夜生活", "travel_style": "休闲游", "constraints": {"max_cost": "low", "weather": "sunny", "group": "couple", "preferred_areas": ["浦东"], "must_see": [], "must_avoid": [], "keywords": []}},
    # 30: [综合测试] 一个极其刁钻的用户，要免费、要小众、不能有风险
    {"city": "上海", "travel_goal": "现代地标与都市景观", "travel_style": "休闲游", "constraints": {"max_cost": "free", "weather": "sunny", "group": "solo", "preferred_areas": ["普陀", "杨浦"], "must_see": [], "must_avoid": ["人多拥挤", "交通不便", "排队久"], "keywords": ["小众", "发呆"]}}
]

def run_all_test_profiles():
    summary_results = []
    
    for idx, profile in enumerate(TEST_PROFILES, 1):
        category = "A (常规)" if idx <= 10 else ("B (进阶)" if idx <= 20 else "C (极端)")
        print(f"\n==============================================================")
        print(f" [运行测试 #{idx}] 类别: {category}")
        print(f" 画像: 目标={profile['travel_goal']}, 风格={profile['travel_style']}, 人群={profile['constraints'].get('group')}, 天气={profile['constraints'].get('weather')}, 预算={profile['constraints'].get('max_cost')}")
        print(f"==============================================================")
        
        final_pois, discarded_pois, steps = run_recall_pipeline(profile, MOCK_DB, COST_MAP)
        
        summary_results.append({
            "id": idx,
            "category": category,
            "goal": profile["travel_goal"],
            "recalled_count": len(final_pois),
            "final_pois": [f"{poi['name']}({poi['match_score']}分)" for poi in final_pois],
            "fallback_steps": steps
        })
        
    print("\n\n" + "="*80)
    print(" [完成] 所有 30 组自动化测试场景执行完毕！结果总览如下 ")
    print("="*80)
    print(f"{'编号':<4} | {'类别':<6} | {'主目标偏好':<12} | {'召回数':<5} | {'触发兜底/放宽':<20} | {'匹配景点候选'}")
    print("-"*100)
    for res in summary_results:
        poi_str = "、".join(res["final_pois"][:3])
        if len(res["final_pois"]) > 3:
            poi_str += f" 等共 {res['recalled_count']} 个"
        elif not res["final_pois"]:
            poi_str = "【无合适景点】"
            
        fallback_str = "、".join(res["fallback_steps"]) if res["fallback_steps"] else "无"
        
        # 针对中文字符对齐做简易处理
        goal_padded = res["goal"].ljust(12 - len(res["goal"]))
        
        print(f"#{res['id']:02d}  | {res['category']}  | {goal_padded} | {res['recalled_count']:^5d} | {fallback_str:<20} | {poi_str}")
    print("="*80)

if __name__ == "__main__":
    run_all_test_profiles()
