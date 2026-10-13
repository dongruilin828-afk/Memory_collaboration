# AI 对话记忆导出


<hr style="border: 0; border-top: 5px solid #2563EB; margin: 48px 0 24px 0;">

## 🔵 👤 用户提问

[📄 泰戈尔.pptx](./documents/%E6%B3%B0%E6%88%88%E5%B0%94.pptx)（PPTX 19.05MB）

告诉我ppt讲了什么、


<hr style="border: 0; border-top: 5px solid #9333EA; margin: 48px 0 24px 0;">

## 🟣 🤖 AI 回答

这份PPT是一份关于印度诗人**泰戈尔**的名人介绍，封面署名李思恒、张家瑞。整体按四个板块展开：

**01 作家简介**

* 泰戈尔（Rabindranath Tagore，1861—1941），印度诗人、文学家、社会活动家、哲学家、印度民族主义者。
* 代表作有《吉檀迦利》《飞鸟集》《园丁集》《新月集》《家庭与世界》《文明的危机》等。
* 童年：出生富裕家庭，是父母最小的儿子，昵称“拉比”；不喜欢刻板学校生活，但受家庭文学熏陶，13岁开始写诗。
* 社会活动：投身印度民族运动，写爱国诗篇；后主张做“建设性”工作，失望后退出运动，埋头文学创作。
* 反对国家主义，访问日本、美国、加拿大，曾遭美国移民官员扣留盘问。
* 反法西斯：谴责意大利侵略阿比西尼亚、西班牙叛乱、德国侵略捷克斯洛伐克。
* 1919年“阿姆利则惨案”后，写信抗议并放弃英国国王授予的“爵士”称号。
* 1924年访问中国，同情中国人民；1930年访问苏联，写《俄罗斯书简》，向往社会主义。
* 晚年继续反法西斯，1941年去世，成千上万市民送葬。

**02 创作特色**

* 作品充满爱国主义和民主主义精神，反映印度人民在帝国主义、封建种姓制度压迫下的反抗。
* 多取材印度现实生活，反映殖民主义、封建制度、愚昧落后下的悲惨命运，以及新思想冲击下社会变化和新一代觉醒。
* 善恶观：乐观主义，认为世界朝绝对善发展，恶最终转化为善；通过无私善行获得宇宙生命/道德生命。
* 女性视角：塑造不同种姓、阶层的女性形象，如童养媳、守寡少女、陪葬寡妇、传统家庭妇女、知识女性等，常是传统陋习牺牲品、爱情追逐者或理想中的印度新女性。

**03 人物评价**

* 国际反侵略运动中国分会评价：泰戈尔是歌颂自然的诗人，也是改革现实的健将；是东方精神的号兵，也是国际主义的旗手；是印度的儿子，也是亚洲文化的卫士、世界文明的前驱。
* 茅盾评价：泰戈尔是人格洁白的诗人，怜悯弱者、同情被压迫者，鼓励爱国精神，激起印度青年反抗英国帝国主义。

**04 名人名言**

* 重点介绍了：“天空中没有留下翅膀的痕迹，但我已经飞过。”
* PPT解释为：经过而无需留下痕迹，伟大无需被铭记，这是一种精神高度。

最后以“谢谢观看”结束。整体就是一份介绍**泰戈尔生平经历、创作思想、人物评价和代表名言**的展示型PPT。


<hr style="border: 0; border-top: 5px solid #2563EB; margin: 48px 0 24px 0;">

## 🔵 👤 用户提问

你能生成一个一样的ppt吗


<hr style="border: 0; border-top: 5px solid #9333EA; margin: 48px 0 24px 0;">

## 🟣 🤖 AI 回答

可以，但要分清“一样”的程度：

* **内容/结构一样**：可以，我能按你上传的 21 页内容，复刻成封面、目录、01 作家简介、02 创作特色、03 人物评价、04 名人名言、谢谢观看等分页。
* **视觉 100% 一样**：做不到。因为我没有原 PPT 的母版、主题、字体、图标、插画素材，也不能在聊天里直接发一个 `.pptx` 二进制文件给你。

我能给你的替代方案有：

1. **逐页文字稿**：把每页标题、正文、排版位置整理好，你直接复制进 PowerPoint。
2. **Python 自动生成脚本**：用 `python-pptx` 写一个脚本，运行后生成 `.pptx`，包含同样的页数、标题、目录、章节页和文字内容；配色可以做成紫橙渐变、红色标题等近似风格，图片用占位框或简单图形代替。
3. **你提供原模板/图片素材**：我可以把文字精确填进原模板，做到接近原版。

如果你要，我现在就可以直接给你完整方案。请回复你想要哪种：

* **“脚本”**：我发完整 `python-pptx` 代码，你运行后生成 PPT；
* **“文字稿”**：我按 21 页逐页列出内容；
* **“都要”**：脚本 + 逐页文字稿一起给。


<hr style="border: 0; border-top: 5px solid #2563EB; margin: 48px 0 24px 0;">

## 🔵 👤 用户提问

你能写出代码，然后我本地运行生成ppt吗


<hr style="border: 0; border-top: 5px solid #9333EA; margin: 48px 0 24px 0;">

## 🟣 🤖 AI 回答

可以。下面是一份完整的 `python-pptx` 脚本，你保存为 `generate_tagore_ppt.py`，在本地安装依赖后运行，就会生成一个近似原版的 `泰戈尔_复刻.pptx`。

> 说明：由于无法获取原 PPT 的模板、字体、图标和插画素材，代码用形状、色块、占位框和文字来复刻内容与结构。视觉上不会 100% 一样，但页数、标题、正文、章节和主要排版都尽量对应。

### 1. 安装依赖

```
pip install python-pptx
```

### 2. 保存以下代码并运行

```
# -*- coding: utf-8 -*-
"""
生成《泰戈尔》名人介绍 PPT 复刻版
运行：
    pip install python-pptx
    python generate_tagore_ppt.py
输出：
    泰戈尔_复刻.pptx
"""

from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE
from pptx.oxml.ns import qn
from pptx.oxml.xmlchemy import OxmlElement

# ========== 颜色 ==========
BLACK = RGBColor(0x33, 0x33, 0x33)
DARK = RGBColor(0x3A, 0x2A, 0x3A)
GRAY = RGBColor(0x88, 0x88, 0x88)
LIGHT = RGBColor(0xF7, 0xF3, 0xF8)
LIGHT_PURPLE = RGBColor(0xEE, 0xE2, 0xF2)
PURPLE = RGBColor(0x6A, 0x2C, 0x70)
DARK_PURPLE = RGBColor(0x4B, 0x1E, 0x54)
ORANGE = RGBColor(0xF2, 0x8C, 0x28)
RED = RGBColor(0xD9, 0x4A, 0x4A)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
CARD = RGBColor(0xFA, 0xF7, 0xFB)

# ========== 页面尺寸 16:9 ==========
SLIDE_W = 13.333
SLIDE_H = 7.5

prs = Presentation()
prs.slide_width = Inches(SLIDE_W)
prs.slide_height = Inches(SLIDE_H)
blank_layout = prs.slide_layouts[6]


def set_run_font(run, name="微软雅黑", size=18, bold=False, color=BLACK):
    """设置 run 的中英文字体"""
    run.font.name = name
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = color

    rPr = run._r.get_or_add_rPr()
    for tag in ("a:ea", "a:cs"):
        el = rPr.find(qn(tag))
        if el is None:
            el = OxmlElement(tag)
            rPr.append(el)
        el.set("typeface", name)


def add_text(slide, left, top, width, height, text,
             font_size=18, bold=False, color=BLACK,
             align=PP_ALIGN.LEFT, font_name="微软雅黑",
             line_spacing=1.15, anchor=MSO_ANCHOR.TOP):
    """添加文本框"""
    txBox = slide.shapes.add_textbox(
        Inches(left), Inches(top), Inches(width), Inches(height)
    )
    tf = txBox.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    tf.text = text
    for p in tf.paragraphs:
        p.alignment = align
        p.line_spacing = line_spacing
        for run in p.runs:
            set_run_font(run, font_name, font_size, bold, color)
    return tf


def add_rect(slide, left, top, width, height, fill_color,
             line_color=None, shape=MSO_SHAPE.RECTANGLE):
    """添加矩形/圆形"""
    shp = slide.shapes.add_shape(
        shape, Inches(left), Inches(top), Inches(width), Inches(height)
    )
    shp.fill.solid()
    shp.fill.fore_color.rgb = fill_color
    if line_color is None:
        shp.line.fill.background()
    else:
        shp.line.color.rgb = line_color
    return shp


def add_page_number(slide, num):
    add_text(slide, 12.3, 7.05, 0.8, 0.3, str(num),
             font_size=10, color=GRAY, align=PP_ALIGN.RIGHT)


def add_section_slide(num, title, en):
    """章节页"""
    slide = prs.slides.add_slide(blank_layout)
    add_rect(slide, 0, 0, SLIDE_W, SLIDE_H, LIGHT)
    add_text(slide, 1.0, 1.7, 3.0, 2.0, num,
             font_size=80, bold=True, color=RED)
    add_text(slide, 4.0, 2.1, 8.0, 1.0, title,
             font_size=40, bold=True, color=DARK)
    add_text(slide, 4.0, 3.2, 8.0, 0.5, en,
             font_size=16, color=GRAY)
    add_rect(slide, 4.0, 3.9, 4.0, 0.05, RED)
    return slide


def add_content_slide(num, title, en=None):
    """内容页标题栏"""
    slide = prs.slides.add_slide(blank_layout)
    add_rect(slide, 0, 0, SLIDE_W, SLIDE_H, WHITE)
    add_rect(slide, 0, 0, SLIDE_W, 1.2, LIGHT_PURPLE)
    add_text(slide, 0.6, 0.25, 2.0, 0.6, num,
             font_size=28, bold=True, color=RED)
    add_text(slide, 1.55, 0.25, 9.0, 0.6, title,
             font_size=28, bold=True, color=DARK)
    if en:
        add_text(slide, 1.55, 0.82, 9.0, 0.3, en,
                 font_size=12, color=GRAY)
    add_rect(slide, 0.6, 1.2, 12.1, 0.03, RED)
    return slide


def add_card(slide, left, top, width, height, title, body,
             title_color=RED):
    """卡片"""
    add_rect(slide, left, top, width, height, CARD, line_color=LIGHT_PURPLE)
    add_text(slide, left + 0.25, top + 0.18, width - 0.5, 0.4,
             title, font_size=20, bold=True, color=title_color)
    add_text(slide, left + 0.25, top + 0.7, width - 0.5, height - 0.9,
             body, font_size=14, color=BLACK, line_spacing=1.25)


def add_image_placeholder(slide, left, top, width, height, text="图片占位"):
    add_rect(slide, left, top, width, height, RGBColor(0xEF, 0xEA, 0xF2),
             line_color=RGBColor(0xD8, 0xCC, 0xE0))
    add_text(slide, left, top + height / 2 - 0.2, width, 0.4, text,
             font_size=14, color=GRAY, align=PP_ALIGN.CENTER)


# ============================================================
# 第 1 页：封面
# ============================================================
slide = prs.slides.add_slide(blank_layout)
add_rect(slide, 0, 0, SLIDE_W, SLIDE_H, PURPLE)
add_rect(slide, 0, 4.8, SLIDE_W, 2.7, ORANGE)
add_rect(slide, 0, 0, 5.0, SLIDE_H, DARK_PURPLE)
add_text(slide, 0.8, 0.45, 11.5, 0.5,
         "作者简介 / 创作特色 / 人物评价 / 名人名言",
         font_size=12, color=WHITE)
add_text(slide, 0.8, 1.9, 11.5, 1.2,
         "RABINDRANATH TAGORE",
         font_size=44, bold=True, color=WHITE)
add_text(slide, 0.8, 3.1, 11.5, 1.0,
         "泰戈尔 名人介绍",
         font_size=36, bold=True, color=WHITE)
add_text(slide, 0.8, 6.45, 11.5, 0.5,
         "李思恒 张家瑞",
         font_size=18, color=WHITE)
add_page_number(slide, 1)


# ============================================================
# 第 2 页：目录
# ============================================================
slide = prs.slides.add_slide(blank_layout)
add_rect(slide, 0, 0, 5.2, SLIDE_H, PURPLE)
add_rect(slide, 0, 4.8, 5.2, 2.7, ORANGE)
add_text(slide, 0.7, 1.5, 4.0, 1.5, "目录",
         font_size=66, bold=True, color=WHITE)
add_text(slide, 2.8, 2.45, 2.0, 0.5, "CONTNETS",
         font_size=14, color=WHITE)
add_text(slide, 0.7, 6.6, 4.0, 0.4,
         "RABINDRANATH TAGORE",
         font_size=11, color=WHITE)

items = [
    ("01", "作家简介", "AUTHOR PROFILE"),
    ("02", "创作特色", "CREATIVE FEATURES"),
    ("03", "人物评价", "CHARACTER EVALUATION"),
    ("04", "名人名言", "FAMOUS QUOTES"),
]
y = 1.15
for num, title, en in items:
    add_rect(slide, 6.7, y, 0.75, 0.75, WHITE, line_color=RED, shape=MSO_SHAPE.OVAL)
    add_text(slide, 6.7, y + 0.15, 0.75, 0.4, num,
             font_size=18, bold=True, color=RED, align=PP_ALIGN.CENTER)
    add_text(slide, 7.75, y - 0.05, 4.5, 0.5, title,
             font_size=25, bold=True, color=DARK)
    add_text(slide, 7.75, y + 0.45, 4.5, 0.3, en,
             font_size=12, color=GRAY)
    y += 1.35
add_page_number(slide, 2)


# ============================================================
# 第 3 页：章节 01 作家简介
# ============================================================
slide = add_section_slide("01", "作家简介", "AUTHOR PROFILE")
add_page_number(slide, 3)


# ============================================================
# 第 4 页：泰戈尔简介
# ============================================================
slide = add_content_slide("01", "作家简介", "AUTHOR PROFILE")
add_text(slide, 0.7, 1.55, 7.5, 0.6,
         "拉宾德拉纳特·泰戈尔",
         font_size=30, bold=True, color=RED)
add_text(slide, 0.7, 2.25, 7.5, 3.6,
         "（Rabindranath Tagore，1861年5月7日—1941年8月7日）\n\n"
         "印度诗人、文学家、社会活动家、哲学家和印度民族主义者。\n\n"
         "代表作有《吉檀迦利》《飞鸟集》《家庭与世界》《园丁集》《新月集》《最后的诗篇》《文明的危机》等。",
         font_size=17, color=BLACK, line_spacing=1.35)
add_image_placeholder(slide, 8.7, 1.7, 3.8, 4.4, "头像 / 眼镜胡子 占位")
add_page_number(slide, 4)


# ============================================================
# 第 5 页：出生富裕家庭
# ============================================================
slide = add_content_slide("01", "作家简介", "AUTHOR PROFILE")
add_text(slide, 0.7, 1.5, 11.8, 0.5,
         "出生富裕家庭",
         font_size=26, bold=True, color=RED)
add_text(slide, 0.7, 2.05, 11.8, 0.7,
         "由于是父母最小的儿子，泰戈尔被家人亲昵地叫做“拉比”，成为家庭中每个成员钟爱的孩子，但大家对他并不溺爱。",
         font_size=15, color=BLACK, line_spacing=1.25)

add_card(slide, 0.7, 3.0, 5.8, 1.7, "儿时",
         "小拉比在加尔各答先后进过四所学校，虽然他对这四所学校都不喜欢，但他在长兄和姐姐的监督下受到良好的教育。")
add_card(slide, 6.8, 3.0, 5.8, 1.7, "学习",
         "泰戈尔在文学方面的修养首先来自家庭环境的熏陶，他进过东方学院、师范学院和孟加拉学院。")
add_card(slide, 0.7, 4.95, 5.8, 1.7, "性格",
         "但是他生性自由，厌恶刻板的学校生活，没有完成学校的正规学习课程。")
add_card(slide, 6.8, 4.95, 5.8, 1.7, "创作",
         "他从小就醉心于诗歌创作，从13岁起就开始写诗，诗中洋溢着反对殖民主义和热爱祖国的情绪。")
add_page_number(slide, 5)


# ============================================================
# 第 6 页：印度民族运动 / 建设性运动
# ============================================================
slide = add_content_slide("01", "作家简介", "AUTHOR PROFILE")
add_text(slide, 0.7, 1.55, 11.8, 0.5,
         "PART 01 印度民族运动",
         font_size=24, bold=True, color=RED)
add_text(slide, 0.7, 2.15, 11.8, 1.6,
         "印度民族运动进入高潮时期，孟加拉人民和全印度的人民都起来反对孟加拉分裂的决定，形成了轰轰烈烈的反帝爱国运动。"
         "泰戈尔毅然投身于这个运动，充满激情的爱国人义愤填膺，写出了大量的爱国主义诗篇。",
         font_size=16, color=BLACK, line_spacing=1.35)

add_text(slide, 0.7, 4.1, 11.8, 0.5,
         "PART 02 “建设性”的运动",
         font_size=24, bold=True, color=RED)
add_text(slide, 0.7, 4.7, 11.8, 1.8,
         "他主张多做“建设性”的工作，比如到农村去发展自己的工业，消灭贫困与愚昧等等，但部分群众不接受他的意见，"
         "由于失望，他便退出运动。从此以后，他过着远离现实斗争的迟隐生活，埋头于文学创作。",
         font_size=16, color=BLACK, line_spacing=1.35)
add_page_number(slide, 6)


# ============================================================
# 第 7 页：反对国家主义
# ============================================================
slide = add_content_slide("01", "作家简介", "AUTHOR PROFILE")
add_text(slide, 0.7, 1.6, 8.2, 0.5,
         "反对国家主义",
         font_size=26, bold=True, color=RED)
add_text(slide, 0.7, 2.3, 8.2, 4.2,
         "1916年，泰戈尔来到日本，他对日本这样充满生机的一个新兴国家，颇多感慨。"
         "后来他从日本又到了美国，以“国家主义”为题，作了许多报告，他谴责东方和西方的“国家主义”。"
         "他对美国一向没有好感，那里的民族歧视使他深恶痛绝。美国的报纸和侦探机关从舆论上和行动上也常常给他带来麻烦。"
         "1929年，他访问了加拿大之后到了美国，又遭到美国移民官员扣留和盘问。",
         font_size=16, color=BLACK, line_spacing=1.4)
add_image_placeholder(slide, 9.3, 2.0, 3.2, 3.9, "人物插图占位")
add_page_number(slide, 7)


# ============================================================
# 第 8 页：反法西斯声援
# ============================================================
slide = add_content_slide("01", "作家简介", "AUTHOR PROFILE")
add_text(slide, 0.7, 1.5, 11.8, 0.5,
         "反法西斯声援",
         font_size=26, bold=True, color=RED)
add_card(slide, 0.7, 2.2, 3.8, 3.6, "阿比西尼亚",
         "1934年，意大利法西斯军队侵略阿比西尼亚（埃塞俄比亚），泰戈尔立即严厉谴责。")
add_card(slide, 4.8, 2.2, 3.8, 3.6, "西班牙",
         "1936年，西班牙爆发了反对共和国政府的叛乱，他站在共和国政府一边，明确反对法西斯头子佛朗哥的倒行逆施。")
add_card(slide, 8.9, 2.2, 3.8, 3.6, "捷克斯洛伐克",
         "1938年，德国法西斯侵略捷克斯洛伐克，他写信给在那儿的朋友，表示对捷克斯洛伐克人民的关怀和声援。")
add_page_number(slide, 8)


# ============================================================
# 第 9 页：阿姆利则惨案 / 访问中国
# ============================================================
slide = add_content_slide("01", "作家简介", "AUTHOR PROFILE")
add_text(slide, 0.7, 1.6, 8.2, 0.5,
         "阿姆利则惨案 与 访问中国",
         font_size=26, bold=True, color=RED)
add_text(slide, 0.7, 2.3, 8.2, 4.2,
         "1919年，发生了“阿姆利则惨案”，英国军队开枪打死了1000多印度平民。"
         "泰戈尔非常气愤，挺身而出，写了一封义正辞严的信给印度总督，提出抗议，并声明放弃英国国王给他的“爵士”称号。\n\n"
         "1924年，他访问了中国。他从年幼起就向往这个古老而富饶的东方大国，并且十分同情中国人民的处境，"
         "写文怒斥英国殖民主义者的鸦片贸易。这次访问终于实现了他多年的愿望。",
         font_size=16, color=BLACK, line_spacing=1.4)
add_image_placeholder(slide, 9.3, 2.0, 3.2, 3.9, "打字机 / 羽毛笔 占位")
add_page_number(slide, 9)


# ============================================================
# 第 10 页：向往社会主义
# ============================================================
slide = add_content_slide("01", "作家简介", "AUTHOR PROFILE")
add_text(slide, 0.7, 1.6, 11.8, 0.5,
         "向往社会主义",
         font_size=26, bold=True, color=RED)
add_text(slide, 0.7, 2.3, 7.8, 4.2,
         "1930年，泰戈尔访问了年轻的社会主义国家苏联。他在那里看到了一个神奇的世界，使他极为振奋，兴之所至，"
         "写成了歌颂苏联的《俄罗斯书简》一书。他虽然不充分了解社会主义，但是他向往这个崭新社会，"
         "想把这个神奇的世界搬到印度人民中去。他对世界上第一个社会主义国家的向往始终如一，"
         "在80岁生日述怀的文章中，还特别强调和赞扬苏联的成就。别人的攻击并没有影响他心目中苏联的美好形象。",
         font_size=16, color=BLACK, line_spacing=1.4)
add_image_placeholder(slide, 8.9, 2.0, 3.6, 3.9, "书籍插图占位")
add_page_number(slide, 10)


# ============================================================
# 第 11 页：晚年事迹
# ============================================================
slide = add_content_slide("01", "作家简介", "AUTHOR PROFILE")
add_text(slide, 0.7, 1.6, 8.2, 0.5,
         "晚年事迹",
         font_size=26, bold=True, color=RED)
add_text(slide, 0.7, 2.3, 8.2, 4.2,
         "1939年，德国法西斯悍然发动世界大战，他又应欧洲朋友之邀，撰文怒斥德国“领袖”的不义行径。"
         "泰戈尔一贯痛恨法西斯，但是对被欺压的弱小民族，他则表示无限同情，特别是对中国，他更是始终抱有好感与希望。\n\n"
         "1941年8月6日，泰戈尔在加尔各答祖居宅第里平静地离开人世，成千上万的市民为他送葬。",
         font_size=16, color=BLACK, line_spacing=1.4)
add_text(slide, 9.3, 2.3, 3.2, 0.5, "不怕法西斯",
         font_size=20, bold=True, color=ORANGE, align=PP_ALIGN.CENTER)
add_text(slide, 9.3, 2.9, 3.2, 0.5, "勇于发声",
         font_size=20, bold=True, color=RED, align=PP_ALIGN.CENTER)
add_image_placeholder(slide, 9.3, 3.6, 3.2, 2.3, "人物插图占位")
add_page_number(slide, 11)


# ============================================================
# 第 12 页：章节 02 创作特色
# ============================================================
slide = add_section_slide("02", "创作特色", "CREATIVE FEATURES")
add_page_number(slide, 12)


# ============================================================
# 第 13 页：创作特色概述
# ============================================================
slide = add_content_slide("02", "创作特色", "CREATIVE FEATURES")
add_card(slide, 0.7, 1.65, 5.8, 2.1, "爱国主义 / 种姓制度",
         "他的作品反映了印度人民在帝国主义和封建种姓制度压迫下要求改变自己命运的强烈愿望，"
         "描写了他们不屈不挠的反抗斗争，充满了鲜明的爱国主义和民主主义精神。")
add_card(slide, 6.8, 1.65, 5.8, 2.1, "记录现实生活",
         "其创作多取材于印度现实生活，反映出印度人民在殖民主义、封建制度、愚昧落后思想的重重压迫下的悲惨命运，"
         "描绘出在新思想的冲击下印度社会的变化及新一代的觉醒，同时也记载着他个人的精神探索历程。")
add_text(slide, 0.7, 4.2, 11.8, 2.0,
         "泰戈尔的作品既关注民族命运，也关注个体精神探索；既有现实批判，也有哲学沉思。",
         font_size=17, color=BLACK, line_spacing=1.35)
add_page_number(slide, 13)


# ============================================================
# 第 14 页：善恶观念 / 道德生命
# ============================================================
slide = add_content_slide("02", "创作特色", "CREATIVE FEATURES")
add_text(slide, 0.7, 1.6, 5.8, 0.5, "01",
         font_size=40, bold=True, color=RED)
add_text(slide, 0.7, 2.2, 5.8, 0.5, "善恶观念",
         font_size=26, bold=True, color=DARK)
add_text(slide, 0.7, 2.9, 5.8, 3.4,
         "泰戈尔是个乐观主义者，他认为世界是朝着绝对的善发展的，坚信恶最终将转化为善。"
         "他认为，我们之所以有痛苦，是因为我们感受到有限，但这并不是固定不变的，并不是最终的，欢乐亦是如此。",
         font_size=16, color=BLACK, line_spacing=1.4)

add_text(slide, 6.9, 1.6, 5.8, 0.5, "02",
         font_size=40, bold=True, color=ORANGE)
add_text(slide, 6.9, 2.2, 5.8, 0.5, "道德生命",
         font_size=26, bold=True, color=DARK)
add_text(slide, 6.9, 2.9, 5.8, 3.4,
         "因此，善恶并不是绝对的存在，但对于有限的我们来说却是真实的，"
         "必须通过无私善行的实践而与无限者的活动统一起来，以获得宇宙生命或道德生命。",
         font_size=16, color=BLACK, line_spacing=1.4)
add_page_number(slide, 14)


# ============================================================
# 第 15 页：女性视角
# ============================================================
slide = add_content_slide("02", "创作特色", "CREATIVE FEATURES")
add_text(slide, 0.7, 1.6, 11.8, 0.5,
         "女性视角",
         font_size=26, bold=True, color=RED)
add_text(slide, 0.7, 2.4, 11.8, 4.0,
         "泰戈尔作品中的女性来自各种不同的种姓和阶层，也有着不同的身份。"
         "如童养媳、守寡少女、陪葬寡妇、被骗失身的幼女、印度传统家庭妇女、"
         "受过高等教育的名媛、拥有新思想的知识女性等，这些女性形象身份或单一呈现，或揉合纷杂，"
         "往往被塑造成传统陋习的牺牲品、美满爱情的追逐者和作者理想中的印度新型女性。",
         font_size=17, color=BLACK, line_spacing=1.45)
add_page_number(slide, 15)


# ============================================================
# 第 16 页：章节 03 人物评价
# ============================================================
slide = add_section_slide("03", "人物评价", "CHARACTER EVALUATION")
add_page_number(slide, 16)


# ============================================================
# 第 17 页：国际反侵略运动中国分会评价
# ============================================================
slide = add_content_slide("03", "人物评价", "CHARACTER EVALUATION")
add_text(slide, 0.7, 1.6, 11.8, 0.5,
         "国际反侵略运动中国分会",
         font_size=24, bold=True, color=RED)
add_text(slide, 0.7, 2.5, 11.8, 4.0,
         "“泰戈尔是歌颂自然的诗人，也是改革现实的健将；是东方精神的号兵，也是国际主义的旗手；"
         "是印度的儿子，也是亚洲文化的卫士、世界文明的前驱；他曾为印度不合作运动而忿怒，"
         "他曾为中国反侵略战争而呐喊，他曾为东方兄弟的命运而忧思，他曾为西方朋友的学术而奔驰。”",
         font_size=18, color=BLACK, line_spacing=1.5)
add_page_number(slide, 17)


# ============================================================
# 第 18 页：茅盾评价
# ============================================================
slide = add_content_slide("03", "人物评价", "CHARACTER EVALUATION")
add_text(slide, 0.7, 1.6, 8.0, 0.5,
         "茅盾",
         font_size=28, bold=True, color=RED)
add_text(slide, 0.7, 2.15, 8.0, 0.4,
         "中国现代作家",
         font_size=14, color=GRAY)
add_text(slide, 0.7, 2.9, 8.0, 3.6,
         "“泰戈尔是一个人格洁白的诗人”\n"
         "“一个怜悯弱者，同情于被压迫人们的诗人”\n"
         "“一个鼓励爱国精神，激起印度青年反抗英国帝国主义的诗人”",
         font_size=18, color=BLACK, line_spacing=1.5)
add_image_placeholder(slide, 9.3, 2.0, 3.2, 4.0, "DOCUMENT 1 占位")
add_page_number(slide, 18)


# ============================================================
# 第 19 页：章节 04 名人名言
# ============================================================
slide = add_section_slide("04", "名人名言", "FAMOUS QUOTES")
add_page_number(slide, 19)


# ============================================================
# 第 20 页：名言
# ============================================================
slide = add_content_slide("04", "名人名言", "FAMOUS QUOTES")
add_text(slide, 0.7, 1.8, 11.8, 1.2,
         "天空中没有留下翅膀的痕迹，但我已经飞过。",
         font_size=30, bold=True, color=RED, align=PP_ALIGN.CENTER)
add_text(slide, 1.5, 3.4, 10.3, 3.0,
         "这句是泰戈尔最宝贵、最深邃的智慧的乍现。诗人所想表达的，是一种如何看待世界的方式。"
         "当泰戈尔看见天空没有翅膀的痕迹，他却告诉自己，我曾经飞过，我已拥抱，所以无悔。"
         "经过而无需留下痕迹，伟大无需被铭记，这是一种精神的高度！",
         font_size=17, color=BLACK, line_spacing=1.5, align=PP_ALIGN.CENTER)
add_page_number(slide, 20)


# ============================================================
# 第 21 页：谢谢观看
# ============================================================
slide = prs.slides.add_slide(blank_layout)
add_rect(slide, 0, 0, SLIDE_W, SLIDE_H, PURPLE)
add_rect(slide, 0, 4.9, SLIDE_W, 2.6, ORANGE)
add_text(slide, 1.0, 2.6, 11.3, 1.5,
         "谢谢观看",
         font_size=54, bold=True, color=WHITE, align=PP_ALIGN.CENTER)
add_page_number(slide, 21)


# ========== 保存 ==========
output = "泰戈尔_复刻.pptx"
prs.save(output)
print(f"已生成：{output}")
```

### 3. 运行

在终端进入脚本所在目录，执行：

```
python generate_tagore_ppt.py
```

运行成功后，当前目录会出现：

```
泰戈尔_复刻.pptx
```

如果你本地没有中文字体“微软雅黑”，可以打开 PPT 后全选替换为系统自带中文字体，例如 Mac 用“PingFang SC”，Windows 用“微软雅黑”或“等线”。

