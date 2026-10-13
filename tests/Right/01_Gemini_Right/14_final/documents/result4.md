# 测试运行结果

## Test Case 1: 常规情侣周末游 - 中等预算，偏好休闲与地标打卡

### 📌 用户画像详情 (User Profile)
- **基本信息:** 2天游 | 2人 | 预算: medium
- **群体特征:** couple | 特殊人群: 无
- **强制约束:** 必去: 外滩 | 必避: 排队久
- **兴趣偏好:** 分类: 现代地标与都市景观, 逛吃与商业街区 | 标签: 摩天楼, 观景台, 步行街, 城市俯瞰, 夜景, 美食打卡
- **旅行目的:** photo_checkin, relaxation
- **软性偏好:** 强度: medium_low | 空间: mixed | 人群: moderate

### 🎯 召回候选数量: 55

**Top 10 候选景点:**
1. **外滩** (上海) | 得分: 145.0 | 召回来源: must_see_recall, style_recall, interest_tag_recall
   - 命中特征: *name: 外滩 | categories: 现代地标与都市景观 | experience_tags: 夜景*
2. **金茂大厦** (上海) | 得分: 100.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 现代地标与都市景观 | structure_tags: 摩天楼,观景台 | experience_tags: 城市俯瞰,夜景*
3. **金茂大厦88层观光厅** (上海) | 得分: 100.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 现代地标与都市景观 | structure_tags: 摩天楼,观景台 | experience_tags: 城市俯瞰,夜景 | must_avoid_conflict: 排队久*
4. **上海环球金融中心** (上海) | 得分: 85.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 现代地标与都市景观 | structure_tags: 摩天楼,观景台 | experience_tags: 城市俯瞰*
5. **东方明珠广播电视塔** (上海) | 得分: 80.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 现代地标与都市景观 | structure_tags: 观景台 | experience_tags: 城市俯瞰,夜景 | must_avoid_conflict: 排队久*
6. **上海中心大厦** (上海) | 得分: 80.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 现代地标与都市景观 | structure_tags: 摩天楼 | experience_tags: 城市俯瞰,夜景 | must_avoid_conflict: 排队久*
7. **陆家嘴** (上海) | 得分: 80.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 现代地标与都市景观 | structure_tags: 摩天楼 | experience_tags: 城市俯瞰,夜景*
8. **上海之巅观光厅** (上海) | 得分: 70.0 | 召回来源: interest_tag_recall
   - 命中特征: *structure_tags: 摩天楼,观景台 | experience_tags: 城市俯瞰,夜景*
9. **上海环球港环球观光台** (上海) | 得分: 70.0 | 召回来源: interest_tag_recall
   - 命中特征: *structure_tags: 摩天楼,观景台 | experience_tags: 城市俯瞰,夜景*
10. **黄浦江游览** (上海) | 得分: 65.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 现代地标与都市景观 | structure_tags: 摩天楼 | experience_tags: 夜景 | must_avoid_conflict: 排队久*

---

## Test Case 2: 特种兵大学生 - 极低预算，高强度，重度探索

### 📌 用户画像详情 (User Profile)
- **基本信息:** 2天游 | 4人 | 预算: budget
- **群体特征:** classmates | 特殊人群: 无
- **强制约束:** 必去: 上海博物馆(人民广场馆) | 必避: 展览期间人流密集
- **兴趣偏好:** 分类: 历史与文化古迹, 艺文与科教空间 | 标签: 古镇, 历史博物馆, 朝代 / 时期, 特展
- **旅行目的:** exploration, photo_checkin
- **软性偏好:** 强度: high | 空间: mixed | 人群: None

### 🎯 召回候选数量: 52

**Top 10 候选景点:**
1. **上海博物馆(人民广场馆)** (上海) | 得分: 100.0 | 召回来源: must_see_recall
   - 命中特征: *name: 上海博物馆(人民广场馆)*
2. **上海朱家角古镇旅游区** (上海) | 得分: 74.0 | 召回来源: style_recall, interest_tag_recall, profile_scenario_recall
   - 命中特征: *categories: 历史与文化古迹 | structure_tags: 古镇 | experience_tags: 朝代 / 时期 | intensity: medium | indoor_outdoor: mixed | cost_level: free*
3. **七宝古镇** (上海) | 得分: 74.0 | 召回来源: style_recall, interest_tag_recall, profile_scenario_recall
   - 命中特征: *categories: 历史与文化古迹 | structure_tags: 古镇 | experience_tags: 朝代 / 时期 | intensity: medium | indoor_outdoor: mixed | cost_level: free*
4. **新场古镇** (上海) | 得分: 74.0 | 召回来源: style_recall, interest_tag_recall, profile_scenario_recall
   - 命中特征: *categories: 历史与文化古迹 | structure_tags: 古镇 | experience_tags: 朝代 / 时期 | intensity: medium | indoor_outdoor: mixed | cost_level: free*
5. **枫泾古镇** (上海) | 得分: 74.0 | 召回来源: style_recall, interest_tag_recall, profile_scenario_recall
   - 命中特征: *categories: 历史与文化古迹 | structure_tags: 古镇 | experience_tags: 朝代 / 时期 | intensity: medium | indoor_outdoor: mixed | cost_level: low*
6. **川沙古镇** (上海) | 得分: 44.0 | 召回来源: interest_tag_recall, profile_scenario_recall
   - 命中特征: *structure_tags: 古镇 | experience_tags: 朝代 / 时期 | intensity: medium | indoor_outdoor: mixed | cost_level: free*
7. **练塘古镇** (上海) | 得分: 44.0 | 召回来源: interest_tag_recall, profile_scenario_recall
   - 命中特征: *structure_tags: 古镇 | experience_tags: 朝代 / 时期 | intensity: medium | indoor_outdoor: mixed | cost_level: free*
8. **玉佛禅寺** (上海) | 得分: 39.0 | 召回来源: style_recall, profile_scenario_recall
   - 命中特征: *categories: 历史与文化古迹 | intensity: medium | indoor_outdoor: mixed | cost_level: low*
9. **龙华寺** (上海) | 得分: 39.0 | 召回来源: style_recall, profile_scenario_recall
   - 命中特征: *categories: 历史与文化古迹 | intensity: medium | indoor_outdoor: mixed | cost_level: low*
10. **上海文庙** (上海) | 得分: 39.0 | 召回来源: style_recall, profile_scenario_recall
   - 命中特征: *categories: 历史与文化古迹 | intensity: medium | indoor_outdoor: mixed | cost_level: low*

---

## Test Case 3: 带娃家庭游 - 高预算，低强度，需要推车无障碍

### 📌 用户画像详情 (User Profile)
- **基本信息:** 4天游 | 3人 | 预算: high
- **群体特征:** parent_child | 特殊人群: toddler
- **强制约束:** 必去: 上海迪士尼度假区 | 必避: 商场人流大, 部分店铺上午营业较晚
- **兴趣偏好:** 分类: 主题游乐与动物园, 自然风光与公园 | 标签: 综合乐园, 城市公园, 亲子项目, 巡游, 亲水
- **旅行目的:** family_fun, relaxation
- **软性偏好:** 强度: low | 空间: outdoor | 人群: quiet

### 🎯 召回候选数量: 60

**Top 10 候选景点:**
1. **上海迪士尼度假区** (上海) | 得分: 165.0 | 召回来源: must_see_recall, style_recall, interest_tag_recall
   - 命中特征: *name: 上海迪士尼度假区 | categories: 主题游乐与动物园 | structure_tags: 综合乐园 | experience_tags: 巡游*
2. **锦江乐园(暂停营业)** (上海) | 得分: 65.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 主题游乐与动物园 | structure_tags: 综合乐园 | experience_tags: 亲子项目*
3. **奈尔宝家庭中心(上海森兰花园城店)** (上海) | 得分: 65.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 主题游乐与动物园 | structure_tags: 综合乐园 | experience_tags: 亲子项目*
4. **上海乐高乐园度假区** (上海) | 得分: 60.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 主题游乐与动物园 | experience_tags: 亲子项目,巡游*
5. **上海千古情景区** (上海) | 得分: 50.0 | 召回来源: interest_tag_recall
   - 命中特征: *structure_tags: 综合乐园 | experience_tags: 亲子项目,巡游*
6. **上海世纪公园** (上海) | 得分: 35.0 | 召回来源: interest_tag_recall
   - 命中特征: *structure_tags: 城市公园 | experience_tags: 亲水*
7. **上海鲁迅公园** (上海) | 得分: 35.0 | 召回来源: interest_tag_recall
   - 命中特征: *structure_tags: 城市公园 | experience_tags: 亲水*
8. **上海大宁公园** (上海) | 得分: 35.0 | 召回来源: interest_tag_recall
   - 命中特征: *structure_tags: 城市公园 | experience_tags: 亲水*
9. **上海长风公园** (上海) | 得分: 35.0 | 召回来源: interest_tag_recall
   - 命中特征: *structure_tags: 城市公园 | experience_tags: 亲水*
10. **北外滩滨江绿地** (上海) | 得分: 35.0 | 召回来源: interest_tag_recall
   - 命中特征: *structure_tags: 城市公园 | experience_tags: 亲水*

---

## Test Case 4: 银发族夕阳红 - 适老电梯需求，文化体验为主

### 📌 用户画像详情 (User Profile)
- **基本信息:** 4天游 | 2人 | 预算: medium
- **群体特征:** elderly | 特殊人群: senior
- **强制约束:** 必去: 静安寺 | 必避: 需爬山步行, 位置偏远，交通不便
- **兴趣偏好:** 分类: 历史与文化古迹, 自然风光与公园 | 标签: 名人故居, 寺庙, 植物园, 讲解导览, 祈福, 赏花
- **旅行目的:** culture_learning, wellness
- **软性偏好:** 强度: low | 空间: mixed | 人群: moderate

### 🎯 召回候选数量: 80

**Top 10 候选景点:**
1. **静安寺** (上海) | 得分: 205.0 | 召回来源: must_see_recall, style_recall, interest_tag_recall, profile_scenario_recall
   - 命中特征: *name: 静安寺 | categories: 历史与文化古迹 | structure_tags: 寺庙 | experience_tags: 祈福,讲解导览 | elderly_scenario: elderly | intensity: medium | indoor_outdoor: mixed | cost_level: medium | suitable_groups: elderly*
2. **龙华寺** (上海) | 得分: 105.0 | 召回来源: style_recall, interest_tag_recall, profile_scenario_recall
   - 命中特征: *categories: 历史与文化古迹 | structure_tags: 寺庙 | experience_tags: 祈福,讲解导览 | elderly_scenario: elderly | intensity: medium | indoor_outdoor: mixed | cost_level: low | suitable_groups: elderly*
3. **真如寺** (上海) | 得分: 105.0 | 召回来源: style_recall, interest_tag_recall, profile_scenario_recall
   - 命中特征: *categories: 历史与文化古迹 | structure_tags: 寺庙 | experience_tags: 祈福,讲解导览 | elderly_scenario: elderly | intensity: medium | indoor_outdoor: mixed | cost_level: low | suitable_groups: elderly*
4. **宝山寺** (上海) | 得分: 105.0 | 召回来源: style_recall, interest_tag_recall, profile_scenario_recall
   - 命中特征: *categories: 历史与文化古迹 | structure_tags: 寺庙 | experience_tags: 祈福,讲解导览 | elderly_scenario: elderly | intensity: medium | indoor_outdoor: mixed | cost_level: low | suitable_groups: elderly*
5. **沉香阁** (上海) | 得分: 105.0 | 召回来源: style_recall, interest_tag_recall, profile_scenario_recall
   - 命中特征: *categories: 历史与文化古迹 | structure_tags: 寺庙 | experience_tags: 祈福,讲解导览 | elderly_scenario: elderly | intensity: medium_low | indoor_outdoor: mixed | cost_level: low | suitable_groups: elderly*
6. **东林寺** (上海) | 得分: 105.0 | 召回来源: style_recall, interest_tag_recall, profile_scenario_recall
   - 命中特征: *categories: 历史与文化古迹 | structure_tags: 寺庙 | experience_tags: 祈福,讲解导览 | elderly_scenario: elderly | intensity: medium | indoor_outdoor: mixed | cost_level: low | suitable_groups: elderly*
7. **玉佛禅寺** (上海) | 得分: 90.0 | 召回来源: style_recall, interest_tag_recall, profile_scenario_recall
   - 命中特征: *categories: 历史与文化古迹 | structure_tags: 寺庙 | experience_tags: 祈福 | elderly_scenario: elderly | intensity: medium | indoor_outdoor: mixed | cost_level: low | suitable_groups: elderly*
8. **上海宋庆龄故居纪念馆** (上海) | 得分: 90.0 | 召回来源: style_recall, interest_tag_recall, profile_scenario_recall
   - 命中特征: *categories: 历史与文化古迹 | structure_tags: 名人故居 | experience_tags: 讲解导览 | elderly_scenario: elderly | intensity: medium_low | indoor_outdoor: mixed | cost_level: low | suitable_groups: elderly*
9. **法华塔** (上海) | 得分: 90.0 | 召回来源: style_recall, interest_tag_recall, profile_scenario_recall
   - 命中特征: *categories: 历史与文化古迹 | structure_tags: 寺庙 | experience_tags: 讲解导览 | elderly_scenario: elderly | intensity: medium_low | indoor_outdoor: mixed | cost_level: free | suitable_groups: elderly*
10. **上海文庙** (上海) | 得分: 85.0 | 召回来源: style_recall, interest_tag_recall, profile_scenario_recall
   - 命中特征: *categories: 历史与文化古迹 | experience_tags: 祈福,讲解导览 | elderly_scenario: elderly | intensity: medium | indoor_outdoor: mixed | cost_level: low | suitable_groups: elderly*

---

## Test Case 5: 商务出差顺便游 - 奢华预算，单人极短时间

### 📌 用户画像详情 (User Profile)
- **基本信息:** 1天游 | 1人 | 预算: luxury
- **群体特征:** business | 特殊人群: 无
- **强制约束:** 必去: 上海中心大厦 | 必避: 目前装修中
- **兴趣偏好:** 分类: 现代地标与都市景观, 演出与休闲夜生活 | 标签: 摩天楼, 酒吧街, 城市俯瞰, 微醺社交
- **旅行目的:** relaxation
- **软性偏好:** 强度: medium_low | 空间: indoor | 人群: quiet

### 🎯 召回候选数量: 45

**Top 10 候选景点:**
1. **上海中心大厦** (上海) | 得分: 165.0 | 召回来源: must_see_recall, style_recall, interest_tag_recall
   - 命中特征: *name: 上海中心大厦 | categories: 现代地标与都市景观 | structure_tags: 摩天楼 | experience_tags: 城市俯瞰*
2. **FOUND158下沉式广场** (上海) | 得分: 65.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 演出与休闲夜生活 | structure_tags: 酒吧街 | experience_tags: 微醺社交*
3. **INS Comedy** (上海) | 得分: 65.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 演出与休闲夜生活 | structure_tags: 酒吧街 | experience_tags: 微醺社交*
4. **今潮8弄** (上海) | 得分: 65.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 演出与休闲夜生活 | structure_tags: 酒吧街 | experience_tags: 微醺社交*
5. **上海环球金融中心** (上海) | 得分: 65.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 现代地标与都市景观 | structure_tags: 摩天楼 | experience_tags: 城市俯瞰*
6. **金茂大厦** (上海) | 得分: 65.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 现代地标与都市景观 | structure_tags: 摩天楼 | experience_tags: 城市俯瞰*
7. **林肯爵士乐上海中心(外滩中央商场店)** (上海) | 得分: 45.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 演出与休闲夜生活 | experience_tags: 微醺社交*
8. **东方明珠广播电视塔** (上海) | 得分: 45.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 现代地标与都市景观 | experience_tags: 城市俯瞰*
9. **陆家嘴** (上海) | 得分: 35.0 | 召回来源: interest_tag_recall
   - 命中特征: *structure_tags: 摩天楼 | experience_tags: 城市俯瞰*
10. **金茂大厦88层观光厅** (上海) | 得分: 35.0 | 召回来源: interest_tag_recall
   - 命中特征: *structure_tags: 摩天楼 | experience_tags: 城市俯瞰*

---

## Test Case 6: 闺蜜探店游 - 纯室内逛吃与美学打卡

### 📌 用户画像详情 (User Profile)
- **基本信息:** 3天游 | 2人 | 预算: affordable
- **群体特征:** friends | 特殊人群: 无
- **强制约束:** 必去: 无 | 必避: 空间狭小，节假日拥挤
- **兴趣偏好:** 分类: 逛吃与商业街区, 艺文与科教空间 | 标签: 潮流街区, 美术馆, 文创园区, 咖啡甜品, 美学打卡, 潮流购物
- **旅行目的:** photo_checkin, social_bonding
- **软性偏好:** 强度: medium | 空间: indoor | 人群: lively

### 🎯 召回候选数量: 64

**Top 10 候选景点:**
1. **上海美术馆(中华艺术宫)** (上海) | 得分: 65.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 艺文与科教空间 | structure_tags: 美术馆 | experience_tags: 美学打卡*
2. **浦东美术馆(暂停开放)** (上海) | 得分: 65.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 艺文与科教空间 | structure_tags: 美术馆 | experience_tags: 美学打卡*
3. **上海M50创意园** (上海) | 得分: 65.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 艺文与科教空间 | structure_tags: 文创园区 | experience_tags: 美学打卡*
4. **上海震旦博物馆** (上海) | 得分: 65.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 艺文与科教空间 | structure_tags: 美术馆 | experience_tags: 美学打卡*
5. **上海余德耀美术馆** (上海) | 得分: 65.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 艺文与科教空间 | structure_tags: 美术馆 | experience_tags: 美学打卡*
6. **上海外滩美术馆** (上海) | 得分: 65.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 艺文与科教空间 | structure_tags: 美术馆 | experience_tags: 美学打卡*
7. **上海田子坊** (上海) | 得分: 50.0 | 召回来源: interest_tag_recall
   - 命中特征: *structure_tags: 潮流街区 | experience_tags: 咖啡甜品,潮流购物*
8. **上生新所** (上海) | 得分: 50.0 | 召回来源: interest_tag_recall
   - 命中特征: *structure_tags: 潮流街区 | experience_tags: 咖啡甜品,潮流购物*
9. **巨富大厦** (上海) | 得分: 50.0 | 召回来源: interest_tag_recall
   - 命中特征: *structure_tags: 潮流街区 | experience_tags: 咖啡甜品,潮流购物*
10. **张园** (上海) | 得分: 50.0 | 召回来源: interest_tag_recall
   - 命中特征: *structure_tags: 潮流街区 | experience_tags: 咖啡甜品,潮流购物*

---

## Test Case 7: 孕妇安全游 - 极度关注电梯与身体状态

### 📌 用户画像详情 (User Profile)
- **基本信息:** 3天游 | 2人 | 预算: medium
- **群体特征:** couple | 特殊人群: pregnant
- **强制约束:** 必去: 无 | 必避: 参观时间较短, 人多拥挤
- **兴趣偏好:** 分类: 自然风光与公园, 艺文与科教空间 | 标签: 城市公园, 美术馆, 安静参观, 野餐
- **旅行目的:** wellness, relaxation
- **软性偏好:** 强度: low | 空间: mixed | 人群: quiet

### 🎯 召回候选数量: 55

**Top 10 候选景点:**
1. **上海世纪公园** (上海) | 得分: 65.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 自然风光与公园 | structure_tags: 城市公园 | experience_tags: 野餐*
2. **陆家嘴中心绿地** (上海) | 得分: 65.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 自然风光与公园 | structure_tags: 城市公园 | experience_tags: 野餐*
3. **上海大宁公园** (上海) | 得分: 65.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 自然风光与公园 | structure_tags: 城市公园 | experience_tags: 野餐*
4. **上海长风公园** (上海) | 得分: 65.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 自然风光与公园 | structure_tags: 城市公园 | experience_tags: 野餐*
5. **复兴公园** (上海) | 得分: 65.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 自然风光与公园 | structure_tags: 城市公园 | experience_tags: 野餐*
6. **上海植物园** (上海) | 得分: 50.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 自然风光与公园 | structure_tags: 城市公园*
7. **上海鲁迅公园** (上海) | 得分: 50.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 自然风光与公园 | structure_tags: 城市公园*
8. **漕溪公园** (上海) | 得分: 50.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 自然风光与公园 | structure_tags: 城市公园*
9. **桂林公园(暂停开放)** (上海) | 得分: 50.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 自然风光与公园 | structure_tags: 城市公园*
10. **静安雕塑公园** (上海) | 得分: 50.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 自然风光与公园 | structure_tags: 城市公园*

---

## Test Case 8: 硬核徒步爱好者 - 极致拉满步行时长

### 📌 用户画像详情 (User Profile)
- **基本信息:** 2天游 | 1人 | 预算: affordable
- **群体特征:** solo | 特殊人群: 无
- **强制约束:** 必去: chi K11 art museum美术馆(上海K11购物艺术中心) | 必避: 无
- **兴趣偏好:** 分类: 自然风光与公园, 户外运动与康养度假 | 标签: 森林, 湿地, 徒步, 观鸟, 运动挑战
- **旅行目的:** adventure, wellness
- **软性偏好:** 强度: high | 空间: outdoor | 人群: None

### 🎯 召回候选数量: 64

**Top 10 候选景点:**
1. **chi K11 art museum美术馆(上海K11购物艺术中心)** (上海) | 得分: 100.0 | 召回来源: must_see_recall
   - 命中特征: *name: chi K11 art museum美术馆(上海K11购物艺术中心)*
2. **上海海湾国家森林公园** (上海) | 得分: 55.0 | 召回来源: interest_tag_recall
   - 命中特征: *structure_tags: 森林,湿地 | experience_tags: 徒步*
3. **青西郊野公园** (上海) | 得分: 55.0 | 召回来源: interest_tag_recall
   - 命中特征: *structure_tags: 森林,湿地 | experience_tags: 徒步*
4. **米市渡松南郊野公园** (上海) | 得分: 55.0 | 召回来源: interest_tag_recall
   - 命中特征: *structure_tags: 森林,湿地 | experience_tags: 徒步*
5. **西沙明珠湖景区-西沙湿地** (上海) | 得分: 50.0 | 召回来源: interest_tag_recall
   - 命中特征: *structure_tags: 湿地 | experience_tags: 徒步,观鸟*
6. **东方绿舟** (上海) | 得分: 45.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 户外运动与康养度假 | experience_tags: 运动挑战*
7. **耀雪冰雪世界** (上海) | 得分: 45.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 户外运动与康养度假 | experience_tags: 运动挑战*
8. **金山城市沙滩** (上海) | 得分: 45.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 户外运动与康养度假 | experience_tags: 运动挑战*
9. **碧海金沙** (上海) | 得分: 45.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 户外运动与康养度假 | experience_tags: 运动挑战*
10. **上海卫智马术俱乐部2期** (上海) | 得分: 45.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 户外运动与康养度假 | experience_tags: 运动挑战*

---

## Test Case 9: 铲屎官携宠出游 - 仅去允许宠物入内的户外

### 📌 用户画像详情 (User Profile)
- **基本信息:** 2天游 | 2人 | 预算: medium
- **群体特征:** family | 特殊人群: pet_owner
- **强制约束:** 必去: 无 | 必避: 季节性开放
- **兴趣偏好:** 分类: 自然风光与公园, 户外运动与康养度假 | 标签: 草地, 露营地, 野餐, 过夜停留
- **旅行目的:** family_fun, relaxation
- **软性偏好:** 强度: medium | 空间: outdoor | 人群: moderate

### 🎯 召回候选数量: 57

**Top 10 候选景点:**
1. **上海申隆生态园** (上海) | 得分: 65.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 户外运动与康养度假 | structure_tags: 露营地 | experience_tags: 过夜停留*
2. **上海高家庄生态园** (上海) | 得分: 65.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 户外运动与康养度假 | structure_tags: 露营地 | experience_tags: 过夜停留*
3. **上海紫海鹭缘** (上海) | 得分: 65.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 户外运动与康养度假 | structure_tags: 露营地 | experience_tags: 过夜停留*
4. **东方绿舟** (上海) | 得分: 45.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 户外运动与康养度假 | experience_tags: 过夜停留*
5. **上海佘山世茂艾美酒店** (上海) | 得分: 45.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 户外运动与康养度假 | experience_tags: 过夜停留*
6. **上海市国际旅游度假区** (上海) | 得分: 45.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 户外运动与康养度假 | experience_tags: 过夜停留*
7. **太阳岛旅游度假区** (上海) | 得分: 45.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 户外运动与康养度假 | experience_tags: 过夜停留*
8. **生态崇明(长岭店)** (上海) | 得分: 45.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 户外运动与康养度假 | experience_tags: 过夜停留*
9. **瀛东生态村** (上海) | 得分: 45.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 户外运动与康养度假 | experience_tags: 过夜停留*
10. **上海瑞华果园** (上海) | 得分: 45.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 户外运动与康养度假 | experience_tags: 过夜停留*

---

## Test Case 10: 纯穷游羊毛党 - 免费景点硬约束

### 📌 用户画像详情 (User Profile)
- **基本信息:** 3天游 | 1人 | 预算: budget
- **群体特征:** solo | 特殊人群: 无
- **强制约束:** 必去: 无 | 必避: 商业化较重
- **兴趣偏好:** 分类: 自然风光与公园, 现代地标与都市景观 | 标签: 城市公园, 滨水天际线, 城市漫步, 摄影
- **旅行目的:** exploration, photo_checkin
- **软性偏好:** 强度: high | 空间: outdoor | 人群: None

### 🎯 召回候选数量: 48

**Top 10 候选景点:**
1. **万国建筑博览群** (上海) | 得分: 65.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 现代地标与都市景观 | structure_tags: 滨水天际线 | experience_tags: 城市漫步*
2. **滨江大道** (上海) | 得分: 65.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 现代地标与都市景观 | structure_tags: 滨水天际线 | experience_tags: 城市漫步*
3. **杨浦滨江** (上海) | 得分: 65.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 现代地标与都市景观 | structure_tags: 滨水天际线 | experience_tags: 城市漫步*
4. **外滩** (上海) | 得分: 65.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 现代地标与都市景观 | structure_tags: 滨水天际线 | experience_tags: 城市漫步*
5. **北外滩国客中心** (上海) | 得分: 50.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 现代地标与都市景观 | structure_tags: 滨水天际线*
6. **上海共青森林公园** (上海) | 得分: 35.0 | 召回来源: interest_tag_recall
   - 命中特征: *structure_tags: 城市公园 | experience_tags: 摄影*
7. **上海植物园** (上海) | 得分: 35.0 | 召回来源: interest_tag_recall
   - 命中特征: *structure_tags: 城市公园 | experience_tags: 摄影*
8. **陆家嘴中心绿地** (上海) | 得分: 35.0 | 召回来源: interest_tag_recall
   - 命中特征: *structure_tags: 城市公园 | experience_tags: 摄影*
9. **中山公园** (上海) | 得分: 35.0 | 召回来源: interest_tag_recall
   - 命中特征: *structure_tags: 城市公园 | experience_tags: 摄影*
10. **漕溪公园** (上海) | 得分: 35.0 | 召回来源: interest_tag_recall
   - 命中特征: *structure_tags: 城市公园 | experience_tags: 摄影*

---

## Test Case 11: 全家老少三代同游 - 复杂人群约束，轮椅推车双需求

### 📌 用户画像详情 (User Profile)
- **基本信息:** 5天游 | 6人 | 预算: high
- **群体特征:** family | 特殊人群: senior, infant
- **强制约束:** 必去: 外滩 | 必避: 周边停车困难, 周边人流量大
- **兴趣偏好:** 分类: 现代地标与都市景观, 逛吃与商业街区, 艺文与科教空间 | 标签: 步行街, 科技馆, 观景台, 城市俯瞰, 亲子科普, 地方小吃
- **旅行目的:** family_fun, culture_learning
- **软性偏好:** 强度: medium_low | 空间: mixed | 人群: moderate

### 🎯 召回候选数量: 80

**Top 10 候选景点:**
1. **外滩** (上海) | 得分: 130.0 | 召回来源: must_see_recall, style_recall
   - 命中特征: *name: 外滩 | categories: 现代地标与都市景观*
2. **上海人民广场** (上海) | 得分: 71.0 | 召回来源: style_recall, profile_scenario_recall
   - 命中特征: *categories: 现代地标与都市景观 | family_scenario: parent_child | elderly_scenario: elderly | intensity: medium | indoor_outdoor: mixed | cost_level: free | suitable_groups: elderly,parent_child*
3. **东方明珠广播电视塔** (上海) | 得分: 65.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 现代地标与都市景观 | structure_tags: 观景台 | experience_tags: 城市俯瞰*
4. **上海环球金融中心** (上海) | 得分: 65.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 现代地标与都市景观 | structure_tags: 观景台 | experience_tags: 城市俯瞰*
5. **金茂大厦** (上海) | 得分: 65.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 现代地标与都市景观 | structure_tags: 观景台 | experience_tags: 城市俯瞰*
6. **金茂大厦88层观光厅** (上海) | 得分: 65.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 现代地标与都市景观 | structure_tags: 观景台 | experience_tags: 城市俯瞰*
7. **嘉定孔庙** (上海) | 得分: 41.0 | 召回来源: profile_scenario_recall
   - 命中特征: *family_scenario: parent_child | elderly_scenario: elderly | intensity: medium | indoor_outdoor: mixed | cost_level: free | suitable_groups: elderly,parent_child*
8. **黄炎培故居** (上海) | 得分: 41.0 | 召回来源: profile_scenario_recall
   - 命中特征: *family_scenario: parent_child | elderly_scenario: elderly | intensity: medium_low | indoor_outdoor: mixed | cost_level: free | suitable_groups: elderly,parent_child*
9. **上海市龙华烈士陵园** (上海) | 得分: 41.0 | 召回来源: profile_scenario_recall
   - 命中特征: *family_scenario: parent_child | elderly_scenario: elderly | intensity: medium | indoor_outdoor: mixed | cost_level: free | suitable_groups: elderly,parent_child*
10. **上海市龙华烈士纪念馆** (上海) | 得分: 41.0 | 召回来源: profile_scenario_recall
   - 命中特征: *family_scenario: parent_child | elderly_scenario: elderly | intensity: medium | indoor_outdoor: mixed | cost_level: free | suitable_groups: elderly,parent_child*

---

## Test Case 12: 深夜蹦迪与夜景党 - 逆作息与夜经济偏好

### 📌 用户画像详情 (User Profile)
- **基本信息:** 2天游 | 3人 | 预算: high
- **群体特征:** friends | 特殊人群: 无
- **强制约束:** 必去: 巨鹿路 | 必避: 距离市区远, 季节性闭园
- **兴趣偏好:** 分类: 演出与休闲夜生活, 逛吃与商业街区 | 标签: Livehouse, 酒吧街, 夜市, 电子乐, 微醺社交, 夜宵, 夜经济
- **旅行目的:** social_bonding, relaxation
- **软性偏好:** 强度: medium_high | 空间: indoor | 人群: lively

### 🎯 召回候选数量: 49

**Top 10 候选景点:**
1. **巨鹿路** (上海) | 得分: 100.0 | 召回来源: must_see_recall
   - 命中特征: *name: 巨鹿路*
2. **INS Comedy** (上海) | 得分: 85.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 演出与休闲夜生活 | structure_tags: Livehouse,酒吧街 | experience_tags: 微醺社交*
3. **FOUND158下沉式广场** (上海) | 得分: 65.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 演出与休闲夜生活 | structure_tags: 酒吧街 | experience_tags: 微醺社交*
4. **林肯爵士乐上海中心(外滩中央商场店)** (上海) | 得分: 65.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 演出与休闲夜生活 | structure_tags: Livehouse | experience_tags: 微醺社交*
5. **今潮8弄** (上海) | 得分: 65.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 演出与休闲夜生活 | structure_tags: 酒吧街 | experience_tags: 微醺社交*
6. **阿文夜市豆浆油条** (上海) | 得分: 65.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 逛吃与商业街区 | structure_tags: 夜市 | experience_tags: 夜宵*
7. **首尔夜市(井亭天地生活广场店)** (上海) | 得分: 50.0 | 召回来源: interest_tag_recall
   - 命中特征: *structure_tags: 夜市 | experience_tags: 夜宵,夜经济*
8. **上海新天地** (上海) | 得分: 45.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 逛吃与商业街区 | experience_tags: 夜经济*
9. **上海大剧院** (上海) | 得分: 30.0 | 召回来源: style_recall
   - 命中特征: *categories: 演出与休闲夜生活*
10. **上海东方艺术中心** (上海) | 得分: 30.0 | 召回来源: style_recall
   - 命中特征: *categories: 演出与休闲夜生活*

---

## Test Case 13: 古镇文化沉浸游 - 喜爱小众静谧

### 📌 用户画像详情 (User Profile)
- **基本信息:** 2天游 | 1人 | 预算: medium
- **群体特征:** solo | 特殊人群: 无
- **强制约束:** 必去: 上海朱家角古镇旅游区 | 必避: 中午闭馆
- **兴趣偏好:** 分类: 历史与文化古迹, 自然风光与公园 | 标签: 古镇, 古桥, 古村, 文化类型, 摄影, 安静参观
- **旅行目的:** culture_learning, relaxation
- **软性偏好:** 强度: medium_low | 空间: outdoor | 人群: quiet

### 🎯 召回候选数量: 51

**Top 10 候选景点:**
1. **上海朱家角古镇旅游区** (上海) | 得分: 150.0 | 召回来源: must_see_recall, style_recall, interest_tag_recall
   - 命中特征: *name: 上海朱家角古镇旅游区 | categories: 历史与文化古迹 | structure_tags: 古镇*
2. **枫泾古镇** (上海) | 得分: 70.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 历史与文化古迹 | structure_tags: 古桥,古镇*
3. **新场古镇** (上海) | 得分: 67.0 | 召回来源: style_recall, interest_tag_recall, profile_scenario_recall
   - 命中特征: *categories: 历史与文化古迹 | structure_tags: 古镇 | intensity: medium | indoor_outdoor: mixed | cost_level: free | suitable_groups: solo*
4. **外白渡桥** (上海) | 得分: 67.0 | 召回来源: style_recall, interest_tag_recall, profile_scenario_recall
   - 命中特征: *categories: 历史与文化古迹 | structure_tags: 古桥 | intensity: medium_low | indoor_outdoor: outdoor | cost_level: free | suitable_groups: solo*
5. **七宝古镇** (上海) | 得分: 50.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 历史与文化古迹 | structure_tags: 古镇*
6. **静安寺** (上海) | 得分: 47.0 | 召回来源: style_recall, profile_scenario_recall
   - 命中特征: *categories: 历史与文化古迹 | intensity: medium | indoor_outdoor: mixed | cost_level: medium | suitable_groups: solo*
7. **玉佛禅寺** (上海) | 得分: 47.0 | 召回来源: style_recall, profile_scenario_recall
   - 命中特征: *categories: 历史与文化古迹 | intensity: medium | indoor_outdoor: mixed | cost_level: low | suitable_groups: solo*
8. **龙华寺** (上海) | 得分: 47.0 | 召回来源: style_recall, profile_scenario_recall
   - 命中特征: *categories: 历史与文化古迹 | intensity: medium | indoor_outdoor: mixed | cost_level: low | suitable_groups: solo*
9. **上海宋庆龄故居纪念馆** (上海) | 得分: 47.0 | 召回来源: style_recall, profile_scenario_recall
   - 命中特征: *categories: 历史与文化古迹 | intensity: medium_low | indoor_outdoor: mixed | cost_level: low | suitable_groups: solo*
10. **上海文庙** (上海) | 得分: 47.0 | 召回来源: style_recall, profile_scenario_recall
   - 命中特征: *categories: 历史与文化古迹 | intensity: medium | indoor_outdoor: mixed | cost_level: low | suitable_groups: solo*

---

## Test Case 14: 残障人士无障碍出行 - 硬性过滤轮椅与视觉辅助

### 📌 用户画像详情 (User Profile)
- **基本信息:** 3天游 | 2人 | 预算: affordable
- **群体特征:** family | 特殊人群: disabled
- **强制约束:** 必去: 无 | 必避: 位于古城墙上，需上下台阶, 周边旧改环境较杂乱, 夏季蚊虫较多
- **兴趣偏好:** 分类: 自然风光与公园, 现代地标与都市景观 | 标签: 城市广场, 滨水天际线, 观景, 城市俯瞰
- **旅行目的:** relaxation
- **软性偏好:** 强度: low | 空间: mixed | 人群: moderate

### 🎯 召回候选数量: 54

**Top 10 候选景点:**
1. **久事苏州河四行仓库码头** (上海) | 得分: 75.0 | 召回来源: style_recall, interest_tag_recall, profile_scenario_recall
   - 命中特征: *categories: 现代地标与都市景观 | structure_tags: 滨水天际线 | family_scenario: low | accessible_scenario: low | intensity: low | indoor_outdoor: mixed | cost_level: medium*
2. **陆家嘴** (上海) | 得分: 65.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 现代地标与都市景观 | structure_tags: 滨水天际线 | experience_tags: 城市俯瞰*
3. **万国建筑博览群** (上海) | 得分: 50.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 现代地标与都市景观 | structure_tags: 滨水天际线*
4. **上海人民广场** (上海) | 得分: 50.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 现代地标与都市景观 | structure_tags: 城市广场*
5. **北外滩国客中心** (上海) | 得分: 50.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 现代地标与都市景观 | structure_tags: 滨水天际线*
6. **滨江大道** (上海) | 得分: 50.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 现代地标与都市景观 | structure_tags: 滨水天际线*
7. **杨浦滨江** (上海) | 得分: 50.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 现代地标与都市景观 | structure_tags: 滨水天际线*
8. **黄浦江游览** (上海) | 得分: 50.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 现代地标与都市景观 | structure_tags: 滨水天际线*
9. **悠游苏州河外滩源码头** (上海) | 得分: 50.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 现代地标与都市景观 | structure_tags: 滨水天际线*
10. **外滩** (上海) | 得分: 50.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 现代地标与都市景观 | structure_tags: 滨水天际线*

---

## Test Case 15: 极奢康养度假客 - 度假村与慢生活

### 📌 用户画像详情 (User Profile)
- **基本信息:** 4天游 | 2人 | 预算: luxury
- **群体特征:** couple | 特殊人群: 无
- **强制约束:** 必去: 无 | 必避: 景点规模较小, 设施较老旧
- **兴趣偏好:** 分类: 户外运动与康养度假, 自然风光与公园 | 标签: 度假村, 康养中心, 湿地, 慢度假, 泡汤疗愈, 亲水
- **旅行目的:** wellness, relaxation
- **软性偏好:** 强度: low | 空间: mixed | 人群: quiet

### 🎯 召回候选数量: 80

**Top 10 候选景点:**
1. **上海佘山世茂艾美酒店** (上海) | 得分: 100.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 户外运动与康养度假 | structure_tags: 度假村,康养中心 | experience_tags: 慢度假,泡汤疗愈*
2. **太阳岛旅游度假区** (上海) | 得分: 80.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 户外运动与康养度假 | structure_tags: 度假村 | experience_tags: 慢度假,泡汤疗愈*
3. **上海东禾九谷开心农场** (上海) | 得分: 80.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 户外运动与康养度假 | structure_tags: 度假村 | experience_tags: 慢度假,泡汤疗愈*
4. **上海市国际旅游度假区** (上海) | 得分: 65.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 户外运动与康养度假 | structure_tags: 度假村 | experience_tags: 慢度假*
5. **碧海金沙** (上海) | 得分: 65.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 户外运动与康养度假 | structure_tags: 度假村 | experience_tags: 慢度假*
6. **上海黄浦江游艇会** (上海) | 得分: 65.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 户外运动与康养度假 | structure_tags: 度假村 | experience_tags: 慢度假*
7. **瀛东生态村** (上海) | 得分: 65.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 户外运动与康养度假 | structure_tags: 度假村 | experience_tags: 慢度假*
8. **耀雪冰雪世界** (上海) | 得分: 50.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 户外运动与康养度假 | structure_tags: 度假村*
9. **涟泉大江户(莘庄店)(暂停营业)** (上海) | 得分: 45.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 户外运动与康养度假 | experience_tags: 泡汤疗愈*
10. **生态崇明(长岭店)** (上海) | 得分: 45.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 户外运动与康养度假 | experience_tags: 慢度假*

---

## Test Case 16: 资深吃货寻味之旅 - 行程围绕美食街区建立

### 📌 用户画像详情 (User Profile)
- **基本信息:** 3天游 | 3人 | 预算: medium
- **群体特征:** friends | 特殊人群: 无
- **强制约束:** 必去: 上海城隍庙 | 必避: 登楼票价高
- **兴趣偏好:** 分类: 逛吃与商业街区 | 标签: 小吃街, 夜市, 特色集市, 地方小吃, 美食打卡, 夜宵, 本地烟火
- **旅行目的:** exploration, social_bonding
- **软性偏好:** 强度: medium | 空间: mixed | 人群: lively

### 🎯 召回候选数量: 52

**Top 10 候选景点:**
1. **上海城隍庙** (上海) | 得分: 117.0 | 召回来源: must_see_recall, profile_scenario_recall
   - 命中特征: *name: 上海城隍庙 | intensity: medium | indoor_outdoor: mixed | cost_level: low | suitable_groups: friends*
2. **阿文夜市豆浆油条** (上海) | 得分: 95.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 逛吃与商业街区 | structure_tags: 夜市 | experience_tags: 地方小吃,夜宵,本地烟火*
3. **黄河路美食休闲街** (上海) | 得分: 65.0 | 召回来源: interest_tag_recall
   - 命中特征: *structure_tags: 小吃街 | experience_tags: 地方小吃,本地烟火,美食打卡*
4. **云南路老字号美食街** (上海) | 得分: 65.0 | 召回来源: interest_tag_recall
   - 命中特征: *structure_tags: 小吃街 | experience_tags: 地方小吃,本地烟火,美食打卡*
5. **真如高陵集市** (上海) | 得分: 65.0 | 召回来源: interest_tag_recall
   - 命中特征: *structure_tags: 特色集市 | experience_tags: 地方小吃,本地烟火,美食打卡*
6. **吴江路休闲街(四季坊店)(装修中)** (上海) | 得分: 50.0 | 召回来源: interest_tag_recall
   - 命中特征: *structure_tags: 小吃街 | experience_tags: 地方小吃,美食打卡*
7. **首尔夜市(井亭天地生活广场店)** (上海) | 得分: 50.0 | 召回来源: interest_tag_recall
   - 命中特征: *structure_tags: 夜市 | experience_tags: 夜宵,美食打卡*
8. **南京路步行街** (上海) | 得分: 45.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 逛吃与商业街区 | experience_tags: 地方小吃*
9. **上海新天地** (上海) | 得分: 45.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 逛吃与商业街区 | experience_tags: 美食打卡*
10. **上海田子坊** (上海) | 得分: 45.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 逛吃与商业街区 | experience_tags: 美食打卡*

---

## Test Case 17: 亲子科学营 - 场馆控与研学路线

### 📌 用户画像详情 (User Profile)
- **基本信息:** 4天游 | 3人 | 预算: affordable
- **群体特征:** parent_child | 特殊人群: 无
- **强制约束:** 必去: 上海天文馆(上海科技馆分馆), 上海自然博物馆 | 必避: 消费高
- **兴趣偏好:** 分类: 艺文与科教空间 | 标签: 科技馆, 天文馆 / 行星馆, 自然博物馆, 儿童博物馆, 互动体验, 亲子科普, 研学
- **旅行目的:** culture_learning, family_fun
- **软性偏好:** 强度: medium_low | 空间: indoor | 人群: moderate

### 🎯 召回候选数量: 64

**Top 10 候选景点:**
1. **上海天文馆(上海科技馆分馆)** (上海) | 得分: 215.0 | 召回来源: must_see_recall, style_recall, interest_tag_recall
   - 命中特征: *name: 上海天文馆(上海科技馆分馆) | categories: 艺文与科教空间 | structure_tags: 天文馆 / 行星馆,科技馆 | experience_tags: 互动体验,亲子科普,研学*
2. **上海自然博物馆** (上海) | 得分: 165.0 | 召回来源: must_see_recall, style_recall, interest_tag_recall
   - 命中特征: *name: 上海自然博物馆 | categories: 艺文与科教空间 | structure_tags: 自然博物馆 | experience_tags: 亲子科普*
3. **上海东方地质科普馆** (上海) | 得分: 85.0 | 召回来源: interest_tag_recall
   - 命中特征: *structure_tags: 科技馆,自然博物馆 | experience_tags: 互动体验,亲子科普,研学*
4. **上海航宇科普中心** (上海) | 得分: 85.0 | 召回来源: interest_tag_recall
   - 命中特征: *structure_tags: 天文馆 / 行星馆,科技馆 | experience_tags: 互动体验,亲子科普,研学*
5. **上海科技馆** (上海) | 得分: 80.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 艺文与科教空间 | structure_tags: 科技馆 | experience_tags: 互动体验,研学*
6. **上海城市规划展示馆** (上海) | 得分: 80.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 艺文与科教空间 | structure_tags: 科技馆 | experience_tags: 互动体验,研学*
7. **上海儿童博物馆** (上海) | 得分: 70.0 | 召回来源: interest_tag_recall
   - 命中特征: *structure_tags: 儿童博物馆,科技馆 | experience_tags: 互动体验,亲子科普*
8. **上海隧道科技馆** (上海) | 得分: 65.0 | 召回来源: interest_tag_recall
   - 命中特征: *structure_tags: 科技馆 | experience_tags: 互动体验,亲子科普,研学*
9. **上海眼镜博物馆** (上海) | 得分: 65.0 | 召回来源: interest_tag_recall
   - 命中特征: *structure_tags: 科技馆 | experience_tags: 互动体验,亲子科普,研学*
10. **上海消防博物馆** (上海) | 得分: 65.0 | 召回来源: interest_tag_recall
   - 命中特征: *structure_tags: 科技馆 | experience_tags: 互动体验,亲子科普,研学*

---

## Test Case 18: 二次元阿宅朝圣 - 潮流街区与室内乐园打卡

### 📌 用户画像详情 (User Profile)
- **基本信息:** 3天游 | 2人 | 预算: medium
- **群体特征:** classmates | 特殊人群: 无
- **强制约束:** 必去: 上海广播博物馆 | 必避: 交通较远
- **兴趣偏好:** 分类: 逛吃与商业街区, 主题游乐与动物园 | 标签: 潮流街区, 购物中心, 室内乐园, 潮流购物, 角色 IP, 全天游玩
- **旅行目的:** exploration, social_bonding
- **软性偏好:** 强度: medium_high | 空间: indoor | 人群: lively

### 🎯 召回候选数量: 63

**Top 10 候选景点:**
1. **上海广播博物馆** (上海) | 得分: 100.0 | 召回来源: must_see_recall
   - 命中特征: *name: 上海广播博物馆*
2. **上海世茂精灵之城主题乐园-蓝精灵乐园** (上海) | 得分: 65.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 主题游乐与动物园 | structure_tags: 室内乐园 | experience_tags: 角色 IP*
3. **机遇时空X-META·全感VR乐园·风起洛阳·苍兰诀** (上海) | 得分: 65.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 主题游乐与动物园 | structure_tags: 室内乐园 | experience_tags: 角色 IP*
4. **上海乐高探索中心** (上海) | 得分: 65.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 主题游乐与动物园 | structure_tags: 室内乐园 | experience_tags: 角色 IP*
5. **上海世嘉都市乐园JOYPOLIS(上海月星环球港店)** (上海) | 得分: 65.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 主题游乐与动物园 | structure_tags: 室内乐园 | experience_tags: 角色 IP*
6. **上海杜莎夫人蜡像馆** (上海) | 得分: 65.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 主题游乐与动物园 | structure_tags: 室内乐园 | experience_tags: 角色 IP*
7. **宝燕乐园(长江国际店)** (上海) | 得分: 39.0 | 召回来源: style_recall, profile_scenario_recall
   - 命中特征: *categories: 主题游乐与动物园 | intensity: medium_high | indoor_outdoor: indoor | cost_level: medium*
8. **上海大自然野生昆虫馆(东方明珠.爬宠昆虫探索中心)** (上海) | 得分: 39.0 | 召回来源: style_recall, profile_scenario_recall
   - 命中特征: *categories: 主题游乐与动物园 | intensity: medium | indoor_outdoor: indoor | cost_level: medium*
9. **长风室内动物园** (上海) | 得分: 39.0 | 召回来源: style_recall, profile_scenario_recall
   - 命中特征: *categories: 主题游乐与动物园 | intensity: medium | indoor_outdoor: indoor | cost_level: medium*
10. **上海田子坊** (上海) | 得分: 35.0 | 召回来源: interest_tag_recall
   - 命中特征: *structure_tags: 潮流街区 | experience_tags: 潮流购物*

---

## Test Case 19: 摄影法师采风 - 追逐日落光影，纯室外建筑与风光

### 📌 用户画像详情 (User Profile)
- **基本信息:** 3天游 | 1人 | 预算: affordable
- **群体特征:** solo | 特殊人群: 无
- **强制约束:** 必去: 上海老外街 | 必避: 下午关闭
- **兴趣偏好:** 分类: 自然风光与公园, 现代地标与都市景观 | 标签: 滨水天际线, 现代桥梁, 花海, 摄影, 建筑摄影, 日出 / 日落, 日落机位
- **旅行目的:** photo_checkin, exploration
- **软性偏好:** 强度: high | 空间: outdoor | 人群: quiet

### 🎯 召回候选数量: 49

**Top 10 候选景点:**
1. **上海老外街** (上海) | 得分: 100.0 | 召回来源: must_see_recall
   - 命中特征: *name: 上海老外街*
2. **万国建筑博览群** (上海) | 得分: 65.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 现代地标与都市景观 | structure_tags: 滨水天际线 | experience_tags: 建筑摄影*
3. **卢浦大桥** (上海) | 得分: 65.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 现代地标与都市景观 | structure_tags: 现代桥梁 | experience_tags: 建筑摄影*
4. **南浦大桥** (上海) | 得分: 65.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 现代地标与都市景观 | structure_tags: 现代桥梁 | experience_tags: 建筑摄影*
5. **久事苏州河四行仓库码头** (上海) | 得分: 65.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 现代地标与都市景观 | structure_tags: 滨水天际线 | experience_tags: 建筑摄影*
6. **北外滩国客中心** (上海) | 得分: 65.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 现代地标与都市景观 | structure_tags: 滨水天际线 | experience_tags: 日落机位*
7. **杨浦大桥** (上海) | 得分: 65.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 现代地标与都市景观 | structure_tags: 现代桥梁 | experience_tags: 建筑摄影*
8. **徐浦大桥** (上海) | 得分: 65.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 现代地标与都市景观 | structure_tags: 现代桥梁 | experience_tags: 建筑摄影*
9. **闵浦大桥** (上海) | 得分: 65.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 现代地标与都市景观 | structure_tags: 现代桥梁 | experience_tags: 建筑摄影*
10. **上海长江大桥** (上海) | 得分: 65.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 现代地标与都市景观 | structure_tags: 现代桥梁 | experience_tags: 建筑摄影*

---

## Test Case 20: 极速中转半日游 - 压榨时间，高效打卡地标

### 📌 用户画像详情 (User Profile)
- **基本信息:** 1天游 | 1人 | 预算: medium
- **群体特征:** solo | 特殊人群: 无
- **强制约束:** 必去: 陆家嘴 | 必避: 部分展览需提前预约, 商业化较重
- **兴趣偏好:** 分类: 现代地标与都市景观 | 标签: 高塔, 摩天楼, 地标打卡, 城市漫步
- **旅行目的:** photo_checkin, exploration
- **软性偏好:** 强度: high | 空间: mixed | 人群: None

### 🎯 召回候选数量: 45

**Top 10 候选景点:**
1. **陆家嘴** (上海) | 得分: 170.0 | 召回来源: must_see_recall, style_recall, interest_tag_recall
   - 命中特征: *name: 陆家嘴 | categories: 现代地标与都市景观 | structure_tags: 摩天楼,高塔*
2. **上海环球金融中心** (上海) | 得分: 65.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 现代地标与都市景观 | structure_tags: 摩天楼 | experience_tags: 地标打卡*
3. **金茂大厦** (上海) | 得分: 65.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 现代地标与都市景观 | structure_tags: 摩天楼 | experience_tags: 地标打卡*
4. **上海展览中心** (上海) | 得分: 65.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 现代地标与都市景观 | structure_tags: 高塔 | experience_tags: 地标打卡*
5. **黄浦江游览** (上海) | 得分: 65.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 现代地标与都市景观 | structure_tags: 摩天楼 | experience_tags: 地标打卡*
6. **万国建筑博览群** (上海) | 得分: 60.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 现代地标与都市景观 | experience_tags: 地标打卡,城市漫步*
7. **上海人民广场** (上海) | 得分: 60.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 现代地标与都市景观 | experience_tags: 地标打卡,城市漫步*
8. **滨江大道** (上海) | 得分: 60.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 现代地标与都市景观 | experience_tags: 地标打卡,城市漫步*
9. **东方明珠广播电视塔** (上海) | 得分: 50.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 现代地标与都市景观 | structure_tags: 高塔*
10. **上海中心大厦** (上海) | 得分: 50.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 现代地标与都市景观 | structure_tags: 摩天楼*

---

## Test Case 21: 毕业自驾游 - 偏好户外与自然保护地

### 📌 用户画像详情 (User Profile)
- **基本信息:** 6天游 | 4人 | 预算: medium
- **群体特征:** classmates | 特殊人群: 无
- **强制约束:** 必去: 滴水湖 | 必避: 无
- **兴趣偏好:** 分类: 自然风光与公园, 户外运动与康养度假 | 标签: 海岛, 国家公园 / 自然保护地, 露营地, 日出 / 日落, 过夜停留, 运动挑战
- **旅行目的:** adventure, social_bonding
- **软性偏好:** 强度: high | 空间: outdoor | 人群: quiet

### 🎯 召回候选数量: 80

**Top 10 候选景点:**
1. **滴水湖** (上海) | 得分: 115.0 | 召回来源: must_see_recall, interest_tag_recall
   - 命中特征: *name: 滴水湖 | experience_tags: 日出 / 日落*
2. **上海申隆生态园** (上海) | 得分: 65.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 户外运动与康养度假 | structure_tags: 露营地 | experience_tags: 过夜停留*
3. **上海高家庄生态园** (上海) | 得分: 65.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 户外运动与康养度假 | structure_tags: 露营地 | experience_tags: 过夜停留*
4. **上海紫海鹭缘** (上海) | 得分: 65.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 户外运动与康养度假 | structure_tags: 露营地 | experience_tags: 过夜停留*
5. **东方绿舟** (上海) | 得分: 60.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 户外运动与康养度假 | experience_tags: 过夜停留,运动挑战*
6. **耀雪冰雪世界** (上海) | 得分: 45.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 户外运动与康养度假 | experience_tags: 运动挑战*
7. **上海佘山世茂艾美酒店** (上海) | 得分: 45.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 户外运动与康养度假 | experience_tags: 过夜停留*
8. **上海市国际旅游度假区** (上海) | 得分: 45.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 户外运动与康养度假 | experience_tags: 过夜停留*
9. **太阳岛旅游度假区** (上海) | 得分: 45.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 户外运动与康养度假 | experience_tags: 过夜停留*
10. **生态崇明(长岭店)** (上海) | 得分: 45.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 户外运动与康养度假 | experience_tags: 过夜停留*

---

## Test Case 22: 情侣周年庆 - 浪漫至上，极简主题乐园行程

### 📌 用户画像详情 (User Profile)
- **基本信息:** 2天游 | 2人 | 预算: luxury
- **群体特征:** couple | 特殊人群: 无
- **强制约束:** 必去: 上海海昌海洋公园 | 必避: 周末人流大, 交通较远
- **兴趣偏好:** 分类: 主题游乐与动物园, 现代地标与都市景观 | 标签: 海洋馆, 观景台, 烟花 / 夜场, 动物互动, 城市俯瞰
- **旅行目的:** relaxation, photo_checkin
- **软性偏好:** 强度: low | 空间: mixed | 人群: moderate

### 🎯 召回候选数量: 49

**Top 10 候选景点:**
1. **上海海昌海洋公园** (上海) | 得分: 165.0 | 召回来源: must_see_recall, style_recall, interest_tag_recall
   - 命中特征: *name: 上海海昌海洋公园 | categories: 主题游乐与动物园 | structure_tags: 海洋馆 | experience_tags: 动物互动*
2. **上海长风海洋世界** (上海) | 得分: 65.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 主题游乐与动物园 | structure_tags: 海洋馆 | experience_tags: 动物互动*
3. **上海海洋水族馆** (上海) | 得分: 50.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 主题游乐与动物园 | structure_tags: 海洋馆*
4. **上海迪士尼度假区** (上海) | 得分: 45.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 主题游乐与动物园 | experience_tags: 烟花 / 夜场*
5. **上海野生动物园** (上海) | 得分: 45.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 主题游乐与动物园 | experience_tags: 动物互动*
6. **上海动物园** (上海) | 得分: 45.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 主题游乐与动物园 | experience_tags: 动物互动*
7. **百乐门(上海影视乐园店)** (上海) | 得分: 45.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 主题游乐与动物园 | experience_tags: 烟花 / 夜场*
8. **开心宠物乐园(上海徐汇区)** (上海) | 得分: 45.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 主题游乐与动物园 | experience_tags: 动物互动*
9. **上海大自然野生昆虫馆(东方明珠.爬宠昆虫探索中心)** (上海) | 得分: 45.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 主题游乐与动物园 | experience_tags: 动物互动*
10. **长风室内动物园** (上海) | 得分: 45.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 主题游乐与动物园 | experience_tags: 动物互动*

---

## Test Case 23: 盲盒随心飞体验客 - 无明显偏好，全靠推荐算法兜底

### 📌 用户画像详情 (User Profile)
- **基本信息:** 3天游 | 1人 | 预算: affordable
- **群体特征:** solo | 特殊人群: 无
- **强制约束:** 必去: 无 | 必避: 无
- **兴趣偏好:** 分类: 无 | 标签: 无
- **旅行目的:** exploration
- **软性偏好:** 强度: medium | 空间: None | 人群: None

### 🎯 召回候选数量: 15

**Top 10 候选景点:**
1. **静安寺** (上海) | 得分: 17.0 | 召回来源: profile_scenario_recall
   - 命中特征: *intensity: medium | indoor_outdoor: mixed | cost_level: medium | suitable_groups: solo*
2. **玉佛禅寺** (上海) | 得分: 17.0 | 召回来源: profile_scenario_recall
   - 命中特征: *intensity: medium | indoor_outdoor: mixed | cost_level: low | suitable_groups: solo*
3. **龙华寺** (上海) | 得分: 17.0 | 召回来源: profile_scenario_recall
   - 命中特征: *intensity: medium | indoor_outdoor: mixed | cost_level: low | suitable_groups: solo*
4. **新场古镇** (上海) | 得分: 17.0 | 召回来源: profile_scenario_recall
   - 命中特征: *intensity: medium | indoor_outdoor: mixed | cost_level: free | suitable_groups: solo*
5. **上海宋庆龄故居纪念馆** (上海) | 得分: 17.0 | 召回来源: profile_scenario_recall
   - 命中特征: *intensity: medium_low | indoor_outdoor: mixed | cost_level: low | suitable_groups: solo*
6. **上海文庙** (上海) | 得分: 17.0 | 召回来源: profile_scenario_recall
   - 命中特征: *intensity: medium | indoor_outdoor: mixed | cost_level: low | suitable_groups: solo*
7. **1933老场坊** (上海) | 得分: 17.0 | 召回来源: profile_scenario_recall
   - 命中特征: *intensity: medium | indoor_outdoor: mixed | cost_level: free | suitable_groups: solo*
8. **真如寺** (上海) | 得分: 17.0 | 召回来源: profile_scenario_recall
   - 命中特征: *intensity: medium | indoor_outdoor: mixed | cost_level: low | suitable_groups: solo*
9. **宝山寺** (上海) | 得分: 17.0 | 召回来源: profile_scenario_recall
   - 命中特征: *intensity: medium | indoor_outdoor: mixed | cost_level: low | suitable_groups: solo*
10. **沉香阁** (上海) | 得分: 17.0 | 召回来源: profile_scenario_recall
   - 命中特征: *intensity: medium_low | indoor_outdoor: mixed | cost_level: low | suitable_groups: solo*

---

## Test Case 24: 大型团建前序探路 - 关注场地容量与团队活动适宜性

### 📌 用户画像详情 (User Profile)
- **基本信息:** 3天游 | 2人 | 预算: medium
- **群体特征:** business | 特殊人群: 无
- **强制约束:** 必去: 无 | 必避: 热门演出票源紧张, 仅夜间营业
- **兴趣偏好:** 分类: 户外运动与康养度假, 艺文与科教空间 | 标签: 山地运动园区, 文创园区, 综合乐园, 运动挑战, 全天游玩, 建筑空间
- **旅行目的:** social_bonding, exploration
- **软性偏好:** 强度: medium | 空间: mixed | 人群: quiet

### 🎯 召回候选数量: 63

**Top 10 候选景点:**
1. **东方绿舟** (上海) | 得分: 65.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 户外运动与康养度假 | structure_tags: 山地运动园区 | experience_tags: 运动挑战*
2. **上海卫智马术俱乐部2期** (上海) | 得分: 65.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 户外运动与康养度假 | structure_tags: 山地运动园区 | experience_tags: 运动挑战*
3. **弹力小镇蹦床公园** (上海) | 得分: 65.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 户外运动与康养度假 | structure_tags: 山地运动园区 | experience_tags: 运动挑战*
4. **耀雪冰雪世界** (上海) | 得分: 45.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 户外运动与康养度假 | experience_tags: 运动挑战*
5. **金山城市沙滩** (上海) | 得分: 45.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 户外运动与康养度假 | experience_tags: 运动挑战*
6. **碧海金沙** (上海) | 得分: 45.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 户外运动与康养度假 | experience_tags: 运动挑战*
7. **SKINOW雪乐山室内滑雪(长风大悦城店)** (上海) | 得分: 45.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 户外运动与康养度假 | experience_tags: 运动挑战*
8. **上海佘山世茂艾美酒店** (上海) | 得分: 30.0 | 召回来源: style_recall
   - 命中特征: *categories: 户外运动与康养度假*
9. **上海市国际旅游度假区** (上海) | 得分: 30.0 | 召回来源: style_recall
   - 命中特征: *categories: 户外运动与康养度假*
10. **太阳岛旅游度假区** (上海) | 得分: 30.0 | 召回来源: style_recall
   - 命中特征: *categories: 户外运动与康养度假*

---

## Test Case 25: 极繁主义者 - 标签超载，用来测试冲突消解策略

### 📌 用户画像详情 (User Profile)
- **基本信息:** 3天游 | 2人 | 预算: medium
- **群体特征:** friends | 特殊人群: 无
- **强制约束:** 必去: 上海豫园, 静安寺, 武康大楼 | 必避: 人多拥挤
- **兴趣偏好:** 分类: 自然风光与公园, 逛吃与商业街区, 历史与文化古迹, 现代地标与都市景观, 艺文与科教空间 | 标签: 城市公园, 高塔, 购物中心, 寺庙, 美术馆, 观鸟, 潮流购物, 祈福, 夜游, 特展
- **旅行目的:** photo_checkin, culture_learning, exploration, relaxation, adventure
- **软性偏好:** 强度: high | 空间: mixed | 人群: quiet

### 🎯 召回候选数量: 49

**Top 10 候选景点:**
1. **静安寺** (上海) | 得分: 182.0 | 召回来源: must_see_recall, style_recall, interest_tag_recall, profile_scenario_recall
   - 命中特征: *name: 静安寺 | categories: 历史与文化古迹 | structure_tags: 寺庙 | experience_tags: 祈福 | intensity: medium | indoor_outdoor: mixed | cost_level: medium | suitable_groups: friends*
2. **上海豫园** (上海) | 得分: 130.0 | 召回来源: must_see_recall, style_recall
   - 命中特征: *name: 上海豫园 | categories: 历史与文化古迹*
3. **武康大楼** (上海) | 得分: 100.0 | 召回来源: must_see_recall
   - 命中特征: *name: 武康大楼*
4. **玉佛禅寺** (上海) | 得分: 82.0 | 召回来源: style_recall, interest_tag_recall, profile_scenario_recall
   - 命中特征: *categories: 历史与文化古迹 | structure_tags: 寺庙 | experience_tags: 祈福 | intensity: medium | indoor_outdoor: mixed | cost_level: low | suitable_groups: friends*
5. **龙华寺** (上海) | 得分: 82.0 | 召回来源: style_recall, interest_tag_recall, profile_scenario_recall
   - 命中特征: *categories: 历史与文化古迹 | structure_tags: 寺庙 | experience_tags: 祈福 | intensity: medium | indoor_outdoor: mixed | cost_level: low | suitable_groups: friends*
6. **真如寺** (上海) | 得分: 82.0 | 召回来源: style_recall, interest_tag_recall, profile_scenario_recall
   - 命中特征: *categories: 历史与文化古迹 | structure_tags: 寺庙 | experience_tags: 祈福 | intensity: medium | indoor_outdoor: mixed | cost_level: low | suitable_groups: friends*
7. **宝山寺** (上海) | 得分: 82.0 | 召回来源: style_recall, interest_tag_recall, profile_scenario_recall
   - 命中特征: *categories: 历史与文化古迹 | structure_tags: 寺庙 | experience_tags: 祈福 | intensity: medium | indoor_outdoor: mixed | cost_level: low | suitable_groups: friends*
8. **东林寺** (上海) | 得分: 82.0 | 召回来源: style_recall, interest_tag_recall, profile_scenario_recall
   - 命中特征: *categories: 历史与文化古迹 | structure_tags: 寺庙 | experience_tags: 祈福 | intensity: medium | indoor_outdoor: mixed | cost_level: low | suitable_groups: friends*
9. **沉香阁** (上海) | 得分: 65.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 历史与文化古迹 | structure_tags: 寺庙 | experience_tags: 祈福*
10. **上海朱家角古镇旅游区** (上海) | 得分: 47.0 | 召回来源: style_recall, profile_scenario_recall
   - 命中特征: *categories: 历史与文化古迹 | intensity: medium | indoor_outdoor: mixed | cost_level: free | suitable_groups: friends*

---

## Test Case 26: 纯看展星人 - 只去博物馆和画廊，室内极致偏好

### 📌 用户画像详情 (User Profile)
- **基本信息:** 3天游 | 1人 | 预算: affordable
- **群体特征:** solo | 特殊人群: 无
- **强制约束:** 必去: 上海万象城购物中心 | 必避: 距离市区远，交通时间长, 参观时间较短
- **兴趣偏好:** 分类: 艺文与科教空间, 历史与文化古迹 | 标签: 美术馆, 艺术馆, 综合博物馆, 安静参观, 特展, 建筑空间
- **旅行目的:** culture_learning, exploration
- **软性偏好:** 强度: medium | 空间: indoor | 人群: quiet

### 🎯 召回候选数量: 58

**Top 10 候选景点:**
1. **上海万象城购物中心** (上海) | 得分: 100.0 | 召回来源: must_see_recall
   - 命中特征: *name: 上海万象城购物中心*
2. **龙美术馆(西岸馆)** (上海) | 得分: 70.0 | 召回来源: interest_tag_recall
   - 命中特征: *structure_tags: 美术馆,艺术馆 | experience_tags: 建筑空间,特展*
3. **McaM** (上海) | 得分: 70.0 | 召回来源: interest_tag_recall
   - 命中特征: *structure_tags: 美术馆,艺术馆 | experience_tags: 建筑空间,特展*
4. **上海苏宁艺术馆** (上海) | 得分: 70.0 | 召回来源: interest_tag_recall
   - 命中特征: *structure_tags: 美术馆,艺术馆 | experience_tags: 安静参观,建筑空间*
5. **上海美术馆(中华艺术宫)** (上海) | 得分: 50.0 | 召回来源: interest_tag_recall
   - 命中特征: *structure_tags: 美术馆 | experience_tags: 安静参观,建筑空间*
6. **浦东美术馆(暂停开放)** (上海) | 得分: 50.0 | 召回来源: interest_tag_recall
   - 命中特征: *structure_tags: 美术馆 | experience_tags: 建筑空间,特展*
7. **西岸艺术中心** (上海) | 得分: 50.0 | 召回来源: interest_tag_recall
   - 命中特征: *structure_tags: 美术馆 | experience_tags: 建筑空间,特展*
8. **上海余德耀美术馆** (上海) | 得分: 50.0 | 召回来源: interest_tag_recall
   - 命中特征: *structure_tags: 美术馆 | experience_tags: 建筑空间,特展*
9. **上海外滩美术馆** (上海) | 得分: 50.0 | 召回来源: interest_tag_recall
   - 命中特征: *structure_tags: 美术馆 | experience_tags: 建筑空间,特展*
10. **上海艺仓美术馆** (上海) | 得分: 50.0 | 召回来源: interest_tag_recall
   - 命中特征: *structure_tags: 美术馆 | experience_tags: 建筑空间,特展*

---

## Test Case 27: 温泉养生游 - 慢节奏疗愈与康养

### 📌 用户画像详情 (User Profile)
- **基本信息:** 2天游 | 2人 | 预算: high
- **群体特征:** couple | 特殊人群: 无
- **强制约束:** 必去: 无 | 必避: 距离市区远
- **兴趣偏好:** 分类: 户外运动与康养度假, 自然风光与公园 | 标签: 温泉, 度假村, 森林, 泡汤疗愈, 慢度假
- **旅行目的:** wellness, relaxation
- **软性偏好:** 强度: low | 空间: indoor | 人群: quiet

### 🎯 召回候选数量: 49

**Top 10 候选景点:**
1. **太阳岛旅游度假区** (上海) | 得分: 100.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 户外运动与康养度假 | structure_tags: 度假村,温泉 | experience_tags: 慢度假,泡汤疗愈*
2. **上海佘山世茂艾美酒店** (上海) | 得分: 80.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 户外运动与康养度假 | structure_tags: 度假村 | experience_tags: 慢度假,泡汤疗愈*
3. **上海东禾九谷开心农场** (上海) | 得分: 80.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 户外运动与康养度假 | structure_tags: 度假村 | experience_tags: 慢度假,泡汤疗愈*
4. **上海市国际旅游度假区** (上海) | 得分: 65.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 户外运动与康养度假 | structure_tags: 度假村 | experience_tags: 慢度假*
5. **涟泉大江户(莘庄店)(暂停营业)** (上海) | 得分: 65.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 户外运动与康养度假 | structure_tags: 温泉 | experience_tags: 泡汤疗愈*
6. **碧海金沙** (上海) | 得分: 65.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 户外运动与康养度假 | structure_tags: 度假村 | experience_tags: 慢度假*
7. **上海黄浦江游艇会** (上海) | 得分: 65.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 户外运动与康养度假 | structure_tags: 度假村 | experience_tags: 慢度假*
8. **瀛东生态村** (上海) | 得分: 65.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 户外运动与康养度假 | structure_tags: 度假村 | experience_tags: 慢度假 | must_avoid_conflict: 距离市区远*
9. **耀雪冰雪世界** (上海) | 得分: 50.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 户外运动与康养度假 | structure_tags: 度假村*
10. **生态崇明(长岭店)** (上海) | 得分: 45.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 户外运动与康养度假 | experience_tags: 慢度假 | must_avoid_conflict: 距离市区远*

---

## Test Case 28: 演出场馆周边顺道游 - 有确定锚点的区域召回测试

### 📌 用户画像详情 (User Profile)
- **基本信息:** 2天游 | 2人 | 预算: medium
- **群体特征:** friends | 特殊人群: 无
- **强制约束:** 必去: 上海大剧院 | 必避: 周末及节假日人流拥挤
- **兴趣偏好:** 分类: 演出与休闲夜生活, 逛吃与商业街区 | 标签: 演艺秀场, 音乐厅, 商圈, 音乐会, 夜游, 夜宵
- **旅行目的:** social_bonding, relaxation
- **软性偏好:** 强度: medium_low | 空间: mixed | 人群: lively

### 🎯 召回候选数量: 47

**Top 10 候选景点:**
1. **上海大剧院** (上海) | 得分: 145.0 | 召回来源: must_see_recall, style_recall, interest_tag_recall
   - 命中特征: *name: 上海大剧院 | categories: 演出与休闲夜生活 | experience_tags: 音乐会*
2. **梅赛德斯-奔驰文化中心** (上海) | 得分: 85.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 演出与休闲夜生活 | structure_tags: 演艺秀场,音乐厅 | experience_tags: 音乐会*
3. **今潮8弄** (上海) | 得分: 80.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 演出与休闲夜生活 | structure_tags: 演艺秀场 | experience_tags: 夜游,音乐会*
4. **上海东方艺术中心** (上海) | 得分: 65.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 演出与休闲夜生活 | structure_tags: 音乐厅 | experience_tags: 音乐会*
5. **凯迪拉克·上海音乐厅** (上海) | 得分: 65.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 演出与休闲夜生活 | structure_tags: 音乐厅 | experience_tags: 音乐会*
6. **林肯爵士乐上海中心(外滩中央商场店)** (上海) | 得分: 65.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 演出与休闲夜生活 | structure_tags: 音乐厅 | experience_tags: 音乐会*
7. **捷豹上海交响音乐厅** (上海) | 得分: 65.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 演出与休闲夜生活 | structure_tags: 音乐厅 | experience_tags: 音乐会*
8. **INS Comedy** (上海) | 得分: 65.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 演出与休闲夜生活 | structure_tags: 演艺秀场 | experience_tags: 夜游*
9. **上海马戏城** (上海) | 得分: 50.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 演出与休闲夜生活 | structure_tags: 演艺秀场*
10. **大世界** (上海) | 得分: 50.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 演出与休闲夜生活 | structure_tags: 演艺秀场*

---

## Test Case 29: 体育迷看赛事 - 激情与赛事导向并结合夜生活

### 📌 用户画像详情 (User Profile)
- **基本信息:** 3天游 | 4人 | 预算: affordable
- **群体特征:** friends | 特殊人群: 无
- **强制约束:** 必去: 大境阁 | 必避: 周一多数画廊闭馆
- **兴趣偏好:** 分类: 演出与休闲夜生活, 户外运动与康养度假 | 标签: 酒吧街, 山地运动园区, 微醺社交, 夜游, 运动挑战
- **旅行目的:** social_bonding, adventure
- **软性偏好:** 强度: medium_high | 空间: mixed | 人群: lively

### 🎯 召回候选数量: 46

**Top 10 候选景点:**
1. **大境阁** (上海) | 得分: 100.0 | 召回来源: must_see_recall
   - 命中特征: *name: 大境阁*
2. **东方绿舟** (上海) | 得分: 65.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 户外运动与康养度假 | structure_tags: 山地运动园区 | experience_tags: 运动挑战*
3. **上海卫智马术俱乐部2期** (上海) | 得分: 65.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 户外运动与康养度假 | structure_tags: 山地运动园区 | experience_tags: 运动挑战*
4. **弹力小镇蹦床公园** (上海) | 得分: 65.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 户外运动与康养度假 | structure_tags: 山地运动园区 | experience_tags: 运动挑战*
5. **FOUND158下沉式广场** (上海) | 得分: 50.0 | 召回来源: interest_tag_recall
   - 命中特征: *structure_tags: 酒吧街 | experience_tags: 夜游,微醺社交*
6. **INS新乐园** (上海) | 得分: 50.0 | 召回来源: interest_tag_recall
   - 命中特征: *structure_tags: 酒吧街 | experience_tags: 夜游,微醺社交*
7. **今潮8弄** (上海) | 得分: 50.0 | 召回来源: interest_tag_recall
   - 命中特征: *structure_tags: 酒吧街 | experience_tags: 夜游,微醺社交*
8. **耀雪冰雪世界** (上海) | 得分: 45.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 户外运动与康养度假 | experience_tags: 运动挑战*
9. **金山城市沙滩** (上海) | 得分: 45.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 户外运动与康养度假 | experience_tags: 运动挑战*
10. **碧海金沙** (上海) | 得分: 45.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 户外运动与康养度假 | experience_tags: 运动挑战*

---

## Test Case 30: 过境免签老外游中国 - 偏好标志性传统文化与全景地标

### 📌 用户画像详情 (User Profile)
- **基本信息:** 5天游 | 2人 | 预算: high
- **群体特征:** couple | 特殊人群: 无
- **强制约束:** 必去: 上海豫园, 外滩 | 必避: 夜间嘈杂拥挤
- **兴趣偏好:** 分类: 历史与文化古迹, 现代地标与都市景观, 逛吃与商业街区 | 标签: 名人故居, 滨水天际线, 地方小吃, 建筑摄影, 文化类型
- **旅行目的:** culture_learning, exploration
- **软性偏好:** 强度: medium | 空间: mixed | 人群: moderate

### 🎯 召回候选数量: 80

**Top 10 候选景点:**
1. **外滩** (上海) | 得分: 135.0 | 召回来源: must_see_recall, interest_tag_recall
   - 命中特征: *name: 外滩 | structure_tags: 滨水天际线 | experience_tags: 建筑摄影*
2. **上海豫园** (上海) | 得分: 130.0 | 召回来源: must_see_recall, style_recall
   - 命中特征: *name: 上海豫园 | categories: 历史与文化古迹*
3. **上海宋庆龄故居纪念馆** (上海) | 得分: 50.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 历史与文化古迹 | structure_tags: 名人故居*
4. **鲁迅故居** (上海) | 得分: 50.0 | 召回来源: style_recall, interest_tag_recall
   - 命中特征: *categories: 历史与文化古迹 | structure_tags: 名人故居*
5. **上海朱家角古镇旅游区** (上海) | 得分: 47.0 | 召回来源: style_recall, profile_scenario_recall
   - 命中特征: *categories: 历史与文化古迹 | intensity: medium | indoor_outdoor: mixed | cost_level: free | suitable_groups: couple*
6. **七宝古镇** (上海) | 得分: 47.0 | 召回来源: style_recall, profile_scenario_recall
   - 命中特征: *categories: 历史与文化古迹 | intensity: medium | indoor_outdoor: mixed | cost_level: free | suitable_groups: couple*
7. **新场古镇** (上海) | 得分: 47.0 | 召回来源: style_recall, profile_scenario_recall
   - 命中特征: *categories: 历史与文化古迹 | intensity: medium | indoor_outdoor: mixed | cost_level: free | suitable_groups: couple*
8. **枫泾古镇** (上海) | 得分: 47.0 | 召回来源: style_recall, profile_scenario_recall
   - 命中特征: *categories: 历史与文化古迹 | intensity: medium | indoor_outdoor: mixed | cost_level: low | suitable_groups: couple*
9. **上海广富林文化遗址** (上海) | 得分: 47.0 | 召回来源: style_recall, profile_scenario_recall
   - 命中特征: *categories: 历史与文化古迹 | intensity: medium_high | indoor_outdoor: mixed | cost_level: medium | suitable_groups: couple*
10. **上海城隍庙** (上海) | 得分: 47.0 | 召回来源: style_recall, profile_scenario_recall
   - 命中特征: *categories: 历史与文化古迹 | intensity: medium | indoor_outdoor: mixed | cost_level: low | suitable_groups: couple*

---

