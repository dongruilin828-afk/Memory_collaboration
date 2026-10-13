# recall_pipeline.py
import copy
from typing import List, Dict, Tuple

def resolve_conflicts(user_profile: Dict) -> Dict:
    """
    【步骤 1. 冲突处理】检查用户画像与环境状态之间的强冲突，并自动进行纠偏调整。
    """
    print("[步骤 1. 冲突处理] 调解员正在检查用户画像冲突...")
    
    resolved_profile = {
        "city": user_profile.get("city"),
        "travel_goal": user_profile.get("travel_goal"),
        # 【修复 Bug 5】保留最初的原始旅行目标火种，供兜底经理在放宽天气时精准还原
        "original_travel_goal": user_profile.get("travel_goal"), 
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

# ==========================================
# 7路基础召回函数群
# ==========================================
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
    cleaned_must_see = [name.strip() for name in must_see_list]
    return [poi for poi in db if poi["name"].strip() in cleaned_must_see]

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

ROUTE_WEIGHTS = {
    "必去强制": 100,
    "关键词RAG": 50,
    "兴趣偏好": 30,
    "片区锚点": 20,
    "旅行风格": 10,
    "天气适配": 5,
    "城市匹配": 1
}

def merge_candidates(recall_lists: Dict[str, List[Dict]]) -> List[Dict]:
    unique_pois = {}
    print("\n[多路召回结果摘要]：")
    for route_name, poi_list in recall_lists.items():
        print(f"   - 【{route_name}】召回了 {len(poi_list)} 个景点")
        
    k = 60  
    for route_name, poi_list in recall_lists.items():
        weight = ROUTE_WEIGHTS.get(route_name, 1)
        for rank_idx, poi in enumerate(poi_list):
            poi_id = poi["poi_id"]
            rank = rank_idx + 1  
            rrf_contribution = (weight * 100.0) / (k + rank)
            
            if poi_id not in unique_pois:
                poi_copy = poi.copy()
                poi_copy["recalled_by"] = [route_name]
                poi_copy["match_score"] = round(rrf_contribution, 2)
                unique_pois[poi_id] = poi_copy
            else:
                if route_name not in unique_pois[poi_id]["recalled_by"]:
                    unique_pois[poi_id]["recalled_by"].append(route_name)
                    unique_pois[poi_id]["match_score"] = round(unique_pois[poi_id]["match_score"] + rrf_contribution, 2)
                    
    sorted_pois = sorted(list(unique_pois.values()), key=lambda x: x["match_score"], reverse=True)
    return sorted_pois

def hard_filter(candidates: List[Dict], trip_request: Dict, cost_map: Dict) -> Tuple[List[Dict], List[Dict]]:
    """
    【安全质检员】执行绝对严格的硬过滤。
    """
    passed = []
    discarded = []
    constraints = trip_request["constraints"]
    # 【修复 Bug 1】全量使用 .get() 防御 KeyError，避免依赖默认画像时死机
    max_cost_val = cost_map.get(constraints.get("max_cost", "medium"), 2) 
    weather = constraints.get("weather", "sunny")
    group = constraints.get("group", "solo")
    must_avoid = constraints.get("must_avoid", [])
    must_see = [name.strip() for name in constraints.get("must_see", [])]
    travel_goal = trip_request.get("travel_goal", "")
    
    for poi in candidates:
        reason = None
        poi_name_stripped = poi["name"].strip()
        
        # ----------------------------------------------------
        # 【红线层：最高优先级】安全与生命红线，纵有免死金牌也绝对不豁免！
        # ----------------------------------------------------
        # 【修复 Bug 4】闭馆、极端高危、生理超载拦截必须凌驾于 must_see 之上
        if poi.get("is_closed", False):
            reason = "景点当前处于【闭馆维修】状态"
        elif weather == "rain" and poi["indoor_outdoor"] == "outdoor" and poi["intensity"] in ["medium_high", "high"]:
            reason = "雨天出行，纯室外且体力消耗极大的景点存在【安全隐患】"
        elif group == "elderly" and poi["intensity"] == "high":
            reason = "同行人群包含【老年人】，高强度的陡峭或刺激景点不适宜出行"
            
        # ----------------------------------------------------
        # 【豁免层】必去清单免死金牌（仅能豁免偏好、预算及避雷标签）
        # ----------------------------------------------------
        elif poi_name_stripped in must_see:
            pass # 安全合规的情况下，必去景点直接豁免后续过滤
            
        # ----------------------------------------------------
        # 【常规偏好与约束层】
        # ----------------------------------------------------
        else:
            # 用户主动避雷标签过滤
            for avoid_tag in must_avoid:
                if avoid_tag in poi["name"] or avoid_tag in poi["description"] or avoid_tag in poi.get("risk_tags", []):
                    reason = f"触发了用户明确要求的避雷标签【{avoid_tag}】"
                    break
            
            if not reason:
                # 大类匹配过滤
                if travel_goal and travel_goal not in poi["categories"]:
                    reason = f"不符合用户的主目标偏好【{travel_goal}】"
                # 消费预算过滤
                elif cost_map.get(poi["cost_level"], 0) > max_cost_val:
                    reason = f"消费级别【{poi['cost_level']}】高于用户上限【{constraints.get('max_cost', 'medium')}】"
                    
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

def fallback_manager(original_candidates, trip_request, cost_map, threshold=3):
    """
    【修复 Bug 3】这里的 trip_request 已经是深拷贝后的独立安全副本，尽情篡改绝不外泄
    """
    print(f"\n[报警：景点数量不足] 硬过滤后合格景点少于 {threshold} 个！启动智能兜底...")
    relaxed_steps = []
    
    passed, discarded = hard_filter(original_candidates, trip_request, cost_map)
    
    cost_levels = ["free", "low", "medium", "high"]
    # 【修复 Bug 1】使用 .get() 防御 KeyError
    curr_cost = trip_request["constraints"].get("max_cost", "medium") 
    
    # 【修复 Bug 2】防范 ValueError 定时炸弹，执行非法词安全容错降级
    if curr_cost not in cost_levels:
        print(f"   [安全警告] 检测到非规范预算词【{curr_cost}】，系统已自动安全降级为【medium】。")
        curr_cost = "medium"
        
    curr_idx = cost_levels.index(curr_cost)
   
    # 策略 1: 预算渐进式提升
    while len(passed) < threshold and curr_idx < 3:
        curr_idx += 1
        new_cost = cost_levels[curr_idx]
        print(f"   [兜底激活] 预算级别提升：从【{curr_cost}】放宽至【{new_cost}】...")
        relaxed_steps.append(f"预算放宽至 {new_cost}")
        trip_request["constraints"]["max_cost"] = new_cost
        curr_cost = new_cost
        passed, discarded = hard_filter(original_candidates, trip_request, cost_map)
        
    # 策略 2: 天气智能放宽 (仅限下雨天且人数依然不足时生效)
    if len(passed) < threshold and trip_request["constraints"].get("weather", "sunny") == "rain":
        print("   [兜底激活] 允许在阴雨天选择“室外/混合”但无安全隐患的景点...")
        relaxed_steps.append("放宽雨天室外限制")
        # 【修复 Bug 5】放宽天气时，必须同步还原最初的原始大类偏好，否则室外景点会被大类硬拦截误杀
        if "original_travel_goal" in trip_request:
            trip_request["travel_goal"] = trip_request["original_travel_goal"]
            
        # 【修复 Bug 1】拒绝全量覆盖！采用“加法去重并集”，确保原有室内火种不被抹杀
        new_passed, new_discarded = hard_filter(original_candidates, trip_request, cost_map)
        
        existing_ids = {p["poi_id"] for p in passed}
        for np in new_passed:
            if np["poi_id"] not in existing_ids:
                passed.append(np)
                
        # 同步将新的丢弃件并入原始丢弃池
        discarded.extend(new_discarded)
        
    passed = sorted(passed, key=lambda x: x.get("match_score", 0), reverse=True)
    # 【修复 Bug 2】必须同步返回最新重过滤后的丢弃列表，维护全局状态一致
    return passed, discarded, relaxed_steps

def run_recall_pipeline(user_profile: Dict, db: List[Dict], cost_map: Dict) -> Tuple[List[Dict], List[Dict], List[str]]:
    print("\n" + "="*60)
    print(" [智能旅行规划系统 - 冲突处理与统一召回流水线] 启动！")
    print("="*60)
    
    resolved_profile = resolve_conflicts(user_profile)
    raw_candidates = execute_recall_all_routes(resolved_profile, db)
    print(f"\n [第一轮多路召回合并去重] 共搜罗到 {len(raw_candidates)} 个初始景点候选项。")
    
    passed, discarded = hard_filter(raw_candidates, resolved_profile, cost_map)
    relaxed_steps = []
    
    if len(passed) < 3:
        # 【修复 Bug 3】执行深拷贝！将兜底放宽的“篡改破坏”彻底隔离在沙盒中，保障传给下游大模型的画像绝不泄露变形
        fallback_profile = copy.deepcopy(resolved_profile)
        passed, discarded, relaxed_steps = fallback_manager(raw_candidates, fallback_profile, cost_map, threshold=3)
        
    # 【完美主义终极修复：根除日志悖论】
    # 因为兜底策略做了加法并集，某些景点可能第一轮被剔除，但第二轮复活进入了 passed。
    # 执行“单调性清洗”并按 poi_id 去重，已经在 passed 里的景点，绝对不能出现在丢弃日志中！
    passed_ids = {p["poi_id"] for p in passed}
    unique_discarded = {}
    for d in discarded:
        if d["poi_id"] not in passed_ids:
            unique_discarded[d["poi_id"]] = d
    discarded = list(unique_discarded.values())

    # 【修复 Bug 2】彻底解决日志悖论！把安全质检员的报告整体挪到兜底决策流之后！
    # 控制台打印的 [合格]/[剔除] 永远是尘埃落定的最终状态，调试体验满分！
    print(f"\n [安全质检员 - 最终过滤报告]：")
    print(f"   [合格] 最终输送合格景点 {len(passed)} 个")
    print(f"   [剔除] 最终拦截不合格景点 {len(discarded)} 个")
    for d in discarded:
        print(f"      - 【{d['name']}】：被剔除，原因：{d['discard_reason']}")
        
    print("\n" + "="*60)
    print(f" 【第一阶段：统一候选召回与硬过滤】 顺利跑通！")
    
    if passed:
        max_score = passed[0]["match_score"]
        for p in passed:
            # 【修复 Bug 3】保留原始 RRF 现场绝对分指纹，拒绝物理销毁
            p["raw_match_score"] = p["match_score"]
            p["match_score"] = round((p["match_score"] / max_score) * 100.0, 2)
            p["normalized_score"] = p["match_score"]
            
    print(f"   最终向打分层输送了 {len(passed)} 个完美景点候选种子：")
    for p in passed:
        print(f"      - 【{p['name']}】 (加权 RRF 匹配度得分: {p['match_score']})")
    if relaxed_steps:
        print(f"   [提示] 由于用户过滤限制过紧，系统启动了兜底机制并放宽了：{relaxed_steps}")
    print("="*60)
            
    return passed, discarded, relaxed_steps