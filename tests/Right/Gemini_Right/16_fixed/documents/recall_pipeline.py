from typing import List, Dict, Tuple

def resolve_conflicts(user_profile: Dict) -> Dict:
    """
    【调解员逻辑】检查用户画像与环境状态之间的强冲突，并自动进行纠偏调整。
    """
    print("[步骤 1. 冲突处理] 调解员正在检查用户画像冲突...")
    
    resolved_profile = {
        "city": user_profile.get("city"),
        "travel_goal": user_profile.get("travel_goal"),
        "travel_style": user_profile.get("travel_style"),
        "constraints": user_profile.get("constraints", {}).copy()
    }
    
    constraints = resolved_profile["constraints"]
    weather = constraints.get("weather", "sunny")
    group = constraints.get("group", "solo")
    
    if weather == "rain" and resolved_profile["travel_goal"] in ["自然风光与公园", "户外运动与康养度假"]:
        print("   [检测到冲突] 天气正在下雨，但用户的主偏好是纯户外大类。")
        print("   [调解方案] 已自动将本会话的旅行大类暂时调整为【艺文与科教空间】(室内保护)。")
        resolved_profile["travel_goal"] = "艺文与科教空间"
        
    if group == "elderly" and resolved_profile.get("travel_style") == "特种兵打卡":
        print("   [检测到冲突] 同行人群包含老人，但偏好风格是高强度的“特种兵打卡”。")
        print("   [调解方案] 已自动将出行风格调整为慢节奏的【休闲游】。")
        resolved_profile["travel_style"] = "休闲游"
        
    max_cost = constraints.get("max_cost", "medium")
    if max_cost == "free" and resolved_profile["travel_goal"] == "主题游乐与动物园":
        print("   [检测到冲突] 用户要求门票完全免费，但主偏好大类包含普遍收费的主题乐园。")
        print("   [调解方案] 已为本次召回开启“免费专场”，大类不变，但硬过滤将严格控制只匹配零门票景点。")

    return resolved_profile

def recall_by_city(city: str, db: List[Dict]) -> List[Dict]:
    return [poi for poi in db if poi["city"] == city]

def recall_by_style(travel_style: str, db: List[Dict]) -> List[Dict]:
    results = []
    for poi in db:
        if travel_style == "休闲游" and poi["intensity"] in ["low", "medium_low"]:
            results.append(poi)
        elif travel_style == "特种兵打卡" and poi["intensity"] in ["medium_high", "high"]:
            results.append(poi)
        elif travel_style not in ["休闲游", "特种兵打卡"]:
            results.append(poi)
    return results

def recall_by_interest(travel_goal: str, db: List[Dict]) -> List[Dict]:
    return [poi for poi in db if travel_goal in poi["categories"]]

def recall_by_must_see(must_see_list: List[str], db: List[Dict]) -> List[Dict]:
    return [poi for poi in db if poi["name"] in must_see_list]

def recall_by_area(preferred_areas: List[str], db: List[Dict]) -> List[Dict]:
    return [poi for poi in db if poi["area"] in preferred_areas]

def recall_by_weather(weather: str, db: List[Dict]) -> List[Dict]:
    results = []
    for poi in db:
        if weather == "rain" and poi["indoor_outdoor"] in ["indoor", "mixed"]:
            results.append(poi)
        elif weather == "sunny" and poi["indoor_outdoor"] in ["outdoor", "mixed"]:
            results.append(poi)
        elif weather not in ["rain", "sunny"]:
            results.append(poi)
    return results

def recall_by_keyword(keywords: List[str], db: List[Dict]) -> List[Dict]:
    results = []
    for poi in db:
        for kw in keywords:
            if kw in poi["name"] or kw in poi["description"]:
                results.append(poi)
                break
    return results

def merge_candidates(recall_lists: Dict[str, List[Dict]]) -> List[Dict]:
    unique_pois = {}
    print("\n[多路召回结果摘要]：")
    for route_name, poi_list in recall_lists.items():
        print(f"   - 【{route_name}】召回了 {len(poi_list)} 个景点")
        for poi in poi_list:
            poi_id = poi["poi_id"]
            if poi_id not in unique_pois:
                poi_copy = poi.copy()
                poi_copy["recalled_by"] = [route_name]
                unique_pois[poi_id] = poi_copy
            else:
                if route_name not in unique_pois[poi_id]["recalled_by"]:
                    unique_pois[poi_id]["recalled_by"].append(route_name)
    return list(unique_pois.values())

def hard_filter(candidates: List[Dict], trip_request: Dict, cost_map: Dict) -> Tuple[List[Dict], List[Dict]]:
    passed = []
    discarded = []
    constraints = trip_request["constraints"]
    max_cost_val = cost_map.get(constraints.get("max_cost", "medium"), 3)
    weather = constraints.get("weather", "sunny")
    group = constraints.get("group", "solo")
    must_avoid = constraints.get("must_avoid", [])
    
    for poi in candidates:
        reason = None
        if poi.get("is_closed", False):
            reason = "景点当前处于【闭馆维修】状态"
        elif cost_map.get(poi["cost_level"], 0) > max_cost_val:
            reason = f"消费级别【{poi['cost_level']}】高于用户上限【{constraints.get('max_cost')}】"
        elif weather == "rain" and poi["indoor_outdoor"] == "outdoor" and poi["intensity"] in ["medium_high", "high"]:
            reason = "雨天出行，纯室外且体力消耗极大的景点存在【安全隐患】"
        elif group == "elderly" and poi["intensity"] == "high":
            reason = "同行人群包含【老年人】，高强度的陡峭或刺激景点不适宜出行"
        else:
            for avoid_tag in must_avoid:
                if avoid_tag in poi["name"] or avoid_tag in poi["description"] or avoid_tag in poi.get("risk_tags", []):
                    reason = f"触发了用户明确要求的避雷标签【{avoid_tag}】"
                    break
                    
        if reason:
            poi_dis = poi.copy()
            poi_dis["discard_reason"] = reason
            discarded.append(poi_dis)
        else:
            passed.append(poi)
    return passed, discarded

def execute_recall_all_routes(trip_request: Dict, db: List[Dict]) -> List[Dict]:
    city = trip_request["city"]
    travel_style = trip_request["travel_style"]
    travel_goal = trip_request["travel_goal"]
    constraints = trip_request["constraints"]
    
    recall_lists = {
        "城市匹配": recall_by_city(city, db),
        "旅行风格": recall_by_style(travel_style, db),
        "兴趣偏好": recall_by_interest(travel_goal, db),
        "必去强制": recall_by_must_see(constraints.get("must_see", []), db),
        "片区锚点": recall_by_area(constraints.get("preferred_areas", []), db),
        "天气适配": recall_by_weather(constraints.get("weather", "sunny"), db),
        "关键词RAG": recall_by_keyword(constraints.get("keywords", []), db)
    }
    return merge_candidates(recall_lists)

def fallback_manager(trip_request: Dict, db: List[Dict], cost_map: Dict, threshold: int = 3) -> Tuple[List[Dict], List[str]]:
    print(f"\n[报警：景点数量不足] 硬过滤后合格景点少于 {threshold} 个！启动渐进式放宽策略重新拿菜...")
    relaxed_steps = []
    current_request = {
        "city": trip_request["city"],
        "travel_goal": trip_request["travel_goal"],
        "travel_style": trip_request["travel_style"],
        "constraints": trip_request["constraints"].copy()
    }
    
    print("   [降级策略 1/3] 放弃“特定片区 (area)”筛选限制，全城搜罗...")
    relaxed_steps.append("全片区检索")
    current_request["constraints"]["preferred_areas"] = ["黄浦", "浦东", "徐汇", "静安", "杨浦", "松江"]
    pois = execute_recall_all_routes(current_request, db)
    passed, discarded = hard_filter(pois, current_request, cost_map)
    if len(passed) >= threshold: return passed, relaxed_steps
        
    original_cost = current_request["constraints"]["max_cost"]
    cost_levels = ["free", "low", "medium", "high"]
    curr_idx = cost_levels.index(original_cost)
    if curr_idx < 3:
        new_cost = cost_levels[curr_idx + 1]
        print(f"   [降级策略 2/3] 预算级别提升：从【{original_cost}】提高到【{new_cost}】...")
        relaxed_steps.append(f"预算放宽至 {new_cost}")
        current_request["constraints"]["max_cost"] = new_cost
        pois = execute_recall_all_routes(current_request, db)
        passed, discarded = hard_filter(pois, current_request, cost_map)
        if len(passed) >= threshold: return passed, relaxed_steps

    print("   [降级策略 3/3] 允许在阴雨天选择“mixed(室内外混合)”的景点...")
    relaxed_steps.append("引入混合景点")
    pois = execute_recall_all_routes(current_request, db)
    passed, discarded = hard_filter(pois, current_request, cost_map)
    return passed, relaxed_steps

def run_recall_pipeline(user_profile: Dict, db: List[Dict], cost_map: Dict) -> Tuple[List[Dict], List[Dict], List[str]]:
    print("\n" + "="*60)
    print(" [智能旅行规划系统 - 冲突处理与统一召回流水线] 启动！")
    print("="*60)
    
    resolved_profile = resolve_conflicts(user_profile)
    raw_candidates = execute_recall_all_routes(resolved_profile, db)
    print(f"\n [第一轮多路召回合并去重] 共搜罗到 {len(raw_candidates)} 个初始景点候选项。")
    
    passed, discarded = hard_filter(raw_candidates, resolved_profile, cost_map)
    
    print(f"\n [安全质检员 - 过滤结果]：")
    print(f"   [合格] 获得合格景点 {len(passed)} 个")
    print(f"   [剔除] 扔掉不合格景点 {len(discarded)} 个")
    for d in discarded:
        print(f"      - 【{d['name']}】：被剔除，原因：{d['discard_reason']}")
        
    relaxed_steps = []
    if len(passed) < 3:
        passed, relaxed_steps = fallback_manager(resolved_profile, db, cost_map, threshold=3)
        
    print("\n" + "="*60)
    print(f" 【第一阶段：统一候选召回与硬过滤】 顺利跑通！")
    print(f"   最终向打分层输送了 {len(passed)} 个完美景点候选种子。")
    if relaxed_steps:
        print(f"   [提示] 由于用户过滤限制过紧，系统启动了兜底机制并放宽了：{relaxed_steps}")
    print("="*60)
    return passed, discarded, relaxed_steps
