# AI 对话记忆导出


<hr style="border: 0; border-top: 5px solid #2563EB; margin: 48px 0 24px 0;">

## 🔵 👤 用户提问

import pdfplumber
import requests
import random
import hashlib
import re
import json
import os
from datetime import datetime
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
import os

# ===================== 【安全】从环境变量读取密钥，代码无明文 =====================
try:
    APPID = os.environ["BAIDU_FANYI_APPID"]
    SECRET_KEY = os.environ["BAIDU_FANYI_SECRET"]
except KeyError:
    raise Exception("请先设置环境变量 BAIDU_FANYI_APPID 和 BAIDU_FANYI_SECRET")

MONTHLY_FREE_QUOTA = 1000000  # 高级版每月100万字符
OUTPUT_PDF = "D:\\小说\\哈利波特\\Harry Potter_translated.pdf"
# ==============================================================================

# 配置文件
QUOTA_FILE = "translation_quota.json"    # 额度记录
PROGRESS_FILE = "translation_progress.json"  # 翻译进度（断点）

# 注册中文字体
pdfmetrics.registerFont(UnicodeCIDFont('STSong-Light'))
CN_FONT = 'STSong-Light'

# ===================== 1. 额度管理（每月自动重置） =====================
def load_quota():
    if not os.path.exists(QUOTA_FILE):
        return {"used_chars": 0, "last_reset_date": datetime.now().strftime("%Y-%m-01")}
    try:
        with open(QUOTA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {"used_chars": 0, "last_reset_date": datetime.now().strftime("%Y-%m-01")}

def save_quota(used_chars, reset_date):
    with open(QUOTA_FILE, "w", encoding="utf-8") as f:
        json.dump({"used_chars": used_chars, "last_reset_date": reset_date}, f, indent=2)

def check_and_reset_quota():
    data = load_quota()
    today = datetime.now()
    current_month = today.strftime("%Y-%m-01")
    if data["last_reset_date"] != current_month:
        save_quota(0, current_month)
        print("🔄 新月份，额度已重置为 100万字符")
        return 0
    return data["used_chars"]

def check_quota(text_len):
    used = check_and_reset_quota()
    remaining = MONTHLY_FREE_QUOTA - used
    return remaining >= text_len, used, remaining

def add_used_chars(chars):
    used = check_and_reset_quota()
    new_used = used + chars
    save_quota(new_used, datetime.now().strftime("%Y-%m-01"))
    return new_used

# ===================== 2. 断点续传：记录/读取翻译进度 =====================
def load_progress():
    if not os.path.exists(PROGRESS_FILE):
        return 1  # 默认从第1页开始
    try:
        with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
            return json.load(f).get("last_finished_page", 1)
    except:
        return 1

def save_progress(page_num):
    with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
        json.dump({"last_finished_page": page_num}, f, indent=2)

def clear_progress():
    if os.path.exists(PROGRESS_FILE):
        os.remove(PROGRESS_FILE)

# ===================== 3. 百度翻译API =====================
def split_text(text, max_len=4500):
    sentences = text.replace("\n", " ").split(". ")
    blocks, cur = [], ""
    for s in sentences:
        if len(cur) + len(s) + 2 <= max_len:
            cur += s + ". "
        else:
            blocks.append(cur.strip())
            cur = s + ". "
    if cur:
        blocks.append(cur.strip())
    return blocks

def baidu_translate(q):
    if not q.strip():
        return "", 0
    text_len = len(q.strip())
    enough, used, remaining = check_quota(text_len)
    if not enough:
        return f"[额度已用完] 本月已用{used}/{MONTHLY_FREE_QUOTA}，剩余{remaining}，下月继续", 0

    blocks = split_text(q)
    res_list, total_cost = [], 0
    for b in blocks:
        if not b.strip(): continue
        salt = str(random.randint(1,10000))
        sign = hashlib.md5((APPID + b + salt + SECRET_KEY).encode()).hexdigest()
        try:
            r = requests.post("https://fanyi-api.baidu.com/api/trans/vip/translate",
                              data={"q":b,"from":"en","to":"zh","appid":APPID,"salt":salt,"sign":sign},
                              timeout=10).json()
            if "trans_result" in r:
                res_list.append(r["trans_result"][0]["dst"])
                total_cost += len(b.strip())
            else:
                res_list.append(f"[失败:{r.get('error_code')}]")
        except Exception as e:
            res_list.append(f"[异常:{str(e)}]")
    return "".join(res_list), total_cost

# ===================== 4. 自动换行 =====================
def wrap_line(text, max_w, font, size, c):
    if not text: return []
    segs = re.split(r"([。，！？；])", text)
    lines, cur = [], ""
    for s in segs:
        if not s: continue
        if c.stringWidth(cur+s, font, size) < max_w:
            cur += s
        else:
            lines.append(cur)
            cur = s
    if cur: lines.append(cur)
    return lines

# ===================== 5. 主函数：断点续翻 + 异常保存 =====================
def translate_pdf_resumable(input_pdf):
    start_page = load_progress()
    print(f"🚀 从第 {start_page} 页开始继续翻译")

    with pdfplumber.open(input_pdf) as pdf:
        total_pages = len(pdf.pages)
        c = canvas.Canvas(OUTPUT_PDF)
        font_size, line_h, margin = 11, 16, 30

        # 先跳过已经翻译过的页（只创建空页，不处理）
        for idx in range(start_page - 1):
            page = pdf.pages[idx]
            c.setPageSize((page.width, page.height))
            c.showPage()

        # 从断点开始翻译
        for idx in range(start_page - 1, total_pages):
            page = pdf.pages[idx]
            current_page_num = idx + 1
            print(f"\n正在翻译第 {current_page_num}/{total_pages} 页")

            c.setPageSize((page.width, page.height))
            c.setFont(CN_FONT, font_size)
            words = page.extract_words()
            full_text = " ".join(w["text"] for w in words) if words else ""

            # 翻译
            cn_text, cost = baidu_translate(full_text)

            # 额度用完 → 立即保存并退出
            if "额度已用完" in cn_text:
                print(f"\n⚠️ 额度不足，已翻译到第 {current_page_num - 1} 页")
                print(f"✅ 已自动保存已翻译内容到：{OUTPUT_PDF}")
                print(f"📌 下次运行将从第 {current_page_num} 页继续翻译")
                save_progress(current_page_num)
                c.showPage()
                c.save()
                return

            # 绘制译文
            lines = wrap_line(cn_text, page.width - 2*margin, CN_FONT, font_size, c)
            y = page.height - margin
            for line in lines:
                if y < margin:
                    c.showPage()
                    c.setFont(CN_FONT, font_size)
                    y = page.height - margin
                c.drawString(margin, y, line.strip())
                y -= line_h

            # 累计额度
            if cost > 0:
                new_used = add_used_chars(cost)
                print(f"📊 已用额度：{new_used}/{MONTHLY_FREE_QUOTA}")

            # 保存当前页进度
            save_progress(current_page_num)
            c.showPage()

        # 全部翻译完成
        c.save()
        clear_progress()
        print(f"\n🎉 全书翻译完成！已保存至：{OUTPUT_PDF}")

# ===================== 运行 =====================
if __name__ == '__main__':
    translate_pdf_resumable(
        input_pdf="D:\\小说\\哈利波特\\Harry Potter.pdf"
    )
评价一下这段代码
…
显示更多


<hr style="border: 0; border-top: 5px solid #9333EA; margin: 48px 0 24px 0;">

## 🟣 🤖 AI 回答

整体评价：**思路不错，已经不是“简单调用翻译 API”的脚本了，而是一个带额度管理、断点续翻、异常处理和 PDF 输出的完整小工具。**  
但如果你的目标是“稳定地把一本几百页的小说翻译完，并且中断后继续”，目前还有几个比较严重的问题。

我按 **代码质量 → 功能正确性 → 断点续传 → 百度 API → PDF → 可改进方案** 来看。

### 1. 总体评分

| 方面 | 评价 |
| --- | --- |
| 整体结构 | ⭐⭐⭐⭐☆ |
| 可读性 | ⭐⭐⭐⭐☆ |
| 安全性 | ⭐⭐⭐⭐☆ |
| 额度管理 | ⭐⭐⭐⭐☆ |
| 断点续传 | ⭐⭐⭐☆☆ |
| API 调用 | ⭐⭐⭐☆☆ |
| PDF 生成 | ⭐⭐⭐☆☆ |
| 大型小说长期运行稳定性 | ⭐⭐☆☆☆ |
| 翻译质量 | ⭐⭐⭐☆☆ |
| 综合 | **7/10** |

---

## 2. 做得比较好的地方

### ① API 密钥没有直接写进代码

这一点是对的：

Python

`APPID = os.environ["BAIDU_FANYI_APPID"]
SECRET_KEY = os.environ["BAIDU_FANYI_SECRET"]`

比这样安全很多：

Python

`APPID = "xxxx"
SECRET_KEY = "xxxx"`

尤其是如果以后把代码上传 GitHub，**绝对不要把百度 API 密钥直接提交进去**。

---

### ② 有额度记录

你用了：

Python

`translation_quota.json`

记录：

JSON

`{
"used_chars": 123456,
"last_reset_date": "2026-10-01"
}`

而且：

Python

`check_and_reset_quota()`

会自动判断月份。

这个设计挺实用，因为你不是单纯依赖百度 API 返回的额度，而是自己维护一个本地计数器。

---

### ③ 有断点续翻

这个思路非常适合翻译长 PDF。

比如：

纯文本

`第 1 页
第 2 页
...
第 137 页`

程序突然崩了。

下一次：

Python

`start_page = load_progress()`

理论上可以从第 138 页继续。

这比每次都从第一页重新翻译好很多。

---

### ④ PDF 中文字体处理是正确方向

你用了：

Python

`pdfmetrics.registerFont(UnicodeCIDFont('STSong-Light'))`

否则 ReportLab 默认字体经常无法正常显示中文。

这一点是很多第一次用 ReportLab 的人容易踩的坑。

---

# 3. 最大的问题：你的“断点续传”实际上有严重 Bug

这是我认为这份代码**最需要修改的地方**。

你现在：

Python

`c = canvas.Canvas(OUTPUT_PDF)`

然后：

Python

`for idx in range(start_page - 1):
page = pdf.pages[idx]
c.setPageSize((page.width, page.height))
c.showPage()`

你的想法是：

> 已经翻译过的页面不用重新翻译，前面生成几个空白页占位置。

问题是：

**你每次重新运行程序，canvas.Canvas(OUTPUT\_PDF) 都会重新创建 PDF。**

也就是说：

假设第一次翻译：

纯文本

`1 → 100页`

第二次运行：

纯文本

`start_page = 101`

程序会创建一个**全新的 PDF**，然后前 100 页只是：

纯文本

`空白页
空白页
空白页
...`

并不会把第一次生成的翻译内容接回来。

所以最终 PDF 会变成：

纯文本

`第1~100页：空白
第101页以后：翻译内容`

而不是：

纯文本

`第1~100页：第一次翻译内容
第101页以后：第二次翻译内容`

### 这是当前代码最大的逻辑问题。

---

# 4. save\_progress() 还有一个页码错误

这里：

Python

`if "额度已用完" in cn_text:
...
save_progress(current_page_num)`

你实际上**没有完成当前页**。

假设：

纯文本

`已经完成 100 页
正在翻译 101 页`

结果额度耗尽。

你保存：

Python

`save_progress(101)`

下一次：

Python

`start_page = 101`

这本身看起来没问题。

但你前面设计的 last\_finished\_page：

Python

`return json.load(f).get("last_finished_page", 1)`

语义上应该是：

> 最后完成的是哪一页

那么应该保存：

Python

`save_progress(current_page_num - 1)`

然后加载的时候：

Python

`start_page = last_finished_page + 1`

这样概念会更加清晰。

---

# 5. split\_text() 对英文小说并不理想

你现在：

Python

`sentences = text.replace("\n", " ").split(". ")`

这会产生不少问题。

例如：

纯文本

`Mr. Potter went to Hogwarts.`

会被切成：

纯文本

`Mr
Potter went to Hogwarts`

因为：

Python

`.split(". ")`

把：

纯文本

`Mr. Potter`

中的 .  也当成句号了。

小说里面大量存在：

纯文本

`Mr.
Mrs.
Dr.
Prof.
e.g.
etc.`

所以这个方法不适合文学作品。

---

# 6. 更严重的是：你没有真正控制百度 API 的请求长度

你写：

Python

`def split_text(text, max_len=4500):`

这看起来是在控制长度。

但是百度翻译 API 的限制不是简单地：

> “Python len() ≤ 4500 就一定安全”

尤其还涉及 URL/POST 参数、API 版本、字符计数规则等。

更稳妥的办法是：

**按照句子切分 + 控制每个请求的字符数 + 超长句再次切分。**

例如：

纯文本

`整页
↓
段落
↓
句子
↓
每批 3000～4000 字符
↓
百度 API`

而不是简单：

Python

`.split(". ")`

---

# 7. API 错误处理还不够

现在：

Python

`if "trans_result" in r:
...
else:
res_list.append(f"[失败:{r.get('error_code')}]")`

问题是：

**翻译失败以后，你仍然会把这一页当作正常完成。**

例如百度返回：

JSON

`{
"error_code": "54003"
}`

你的程序会生成：

纯文本

`[失败:54003]`

然后：

Python

`save_progress(current_page_num)`

于是这一页被标记为“已经完成”。

下一次运行不会重新翻译。

这会导致最终 PDF 里面出现：

纯文本

`[失败:54003]`

而且永远不会自动修复。

### 正确做法

如果 API 失败：

纯文本

`重试
↓
仍失败
↓
保存当前状态
↓
不要把当前页标记为完成
↓
退出`

例如：

Python

`for retry in range(3):
...`

---

# 8. 没有真正利用 requests.Session()

现在每次：

Python

`requests.post(...)`

都会独立发送请求。

如果一本小说有几百页、几千次 API 请求，可以考虑：

Python

`session = requests.Session()`

然后：

Python

`session.post(...)`

这样连接复用会更合理。

---

# 9. 你的“每月100万字符”统计有潜在误差

这里：

Python

`total_cost += len(b.strip())`

然后：

Python

`add_used_chars(cost)`

你统计的是**本地发送出去的字符串长度**。

这不一定等于百度实际计费字符数。

因此：

Python

`MONTHLY_FREE_QUOTA = 1000000`

最好理解成：

> 本程序自己的保守估算额度

而不是：

> 百度官方精确剩余额度

如果 API 返回实际字符消耗，应该优先使用 API 返回的数据。

---

# 10. PDF 排版目前比较简陋

现在最终 PDF 基本是：

纯文本

`Harry Potter translated.pdf
第一页：
翻译文字
翻译文字
翻译文字
...
第二页：
翻译文字
...`

但是小说翻译最好至少保留：

* 段落
* 空行
* 章节标题
* 页码
* 合理的行距
* 首行缩进
* 章节分页
* 标题字体
* 正文字体

现在：

Python

`full_text = " ".join(w["text"] for w in words)`

实际上已经把原 PDF 的段落结构**破坏掉了**。

例如原文：

纯文本

`Harry looked at the door.
He wondered who was outside.`

很可能变成：

纯文本

`Harry looked at the door. He wondered who was outside.`

翻译之后就没有原来的段落了。

---

# 11. 还有一个非常重要的问题：你没有保留原 PDF 的页面内容

你现在生成的是：

> **只有中文翻译的新 PDF**

而不是：

> **原版页面 + 中文翻译**

如果这是你想要的效果，那没问题。

但如果你想：

> 左边英文、右边中文

或者：

> 原文下面跟中文

那么目前这套 PDF 生成逻辑还需要重新设计。

---

# 12. wrap\_line() 也有一个潜在 Bug

这里：

Python

`if c.stringWidth(cur+s, font, size) < max_w:
cur += s
else:
lines.append(cur)
cur = s`

如果某个 s 本身就比 max\_w 长：

纯文本

`超长字符串`

那么：

Python

`lines.append(cur)
cur = s`

最终仍然会出现一行超出页面。

虽然中文一般比较少出现这种情况，但英文 URL、特殊字符串等可能造成问题。

---

# 13. except: 太宽泛

例如：

Python

`except:
return {"used_chars": 0...}`

这不太推荐。

最好：

Python

`except (json.JSONDecodeError, OSError):`

这样真正的程序 Bug 不会被悄悄吞掉。

否则以后出现问题时，你会很难定位。

---

# 14. 有一些小的代码质量问题

例如：

Python

`import os`

出现了两次。

以及：

Python

`from datetime import datetime`

这些没有问题，但可以清理。

另外建议增加：

Python

`from pathlib import Path`

这样路径会比：

Python

`"D:\\小说\\哈利波特\\Harry Potter.pdf"`

更加容易管理。

---

# 15. 我最建议你重新设计成这个结构

如果你的真实目标是：

> **把《Harry Potter.pdf》完整翻译成中文，几百页甚至上千页，百度 API 每月100万字符，中断后可以继续，而且最终 PDF 不丢页。**

那么我建议架构改成：

纯文本

`Harry Potter.pdf
│
▼
PDF 逐页读取
│
▼
提取段落/文本
│
▼
文本分块
│
▼
百度翻译 API
│
├── 成功 → 保存译文
│
└── 失败 → 自动重试
│
▼
page_001.json
page_002.json
page_003.json
...
▼
全部翻译完成
│
▼
最后统一生成 PDF`

这比你现在：

纯文本

`翻译一页
↓
直接写 PDF
↓
下一页`

要可靠得多。

---

# 16. 为什么我尤其推荐“先保存翻译结果，再生成 PDF”

例如翻译到第 237 页：

纯文本

`page_001.json
page_002.json
...
page_237.json`

突然电脑关机。

没关系。

下一次：

纯文本

`检查 page_001 ~ page_237`

发现都有。

直接：

纯文本

`从 page_238 开始`

最终全部完成：

纯文本

`JSON翻译结果
↓
PDF生成器
↓
Harry Potter_translated.pdf`

这样**翻译和 PDF 生成互相独立**。

这会比当前代码稳定很多。

---

## 17. 如果让我给这份代码定性

我会把它评价为：

> **“一个思路完整、已经具备实用雏形，但断点续传机制存在核心设计缺陷的 PDF 自动翻译脚本。”**

它不是垃圾代码，反而有不少不错的工程意识：

* 环境变量密钥
* 月度额度
* JSON 状态
* 断点续传
* API 超时
* 中文字体
* 自动换行
* 异常退出保存

这些说明你已经开始从“写一个能跑的脚本”往“写一个能长期运行的工具”方向走了。

但如果准备真的拿它去跑**整本《哈利·波特》**，我建议先不要直接运行。

**最优先应该修三个东西：**

1. 🔴 **修复 PDF 断点续传——目前会导致前面已经翻译的内容丢失**
2. 🔴 **API 失败自动重试，失败页不能标记为完成**
3. 🟠 **翻译结果独立持久化，最后再统一生成 PDF**

如果这三个改完，整体可靠性会提升一个档次。


<hr style="border: 0; border-top: 5px solid #2563EB; margin: 48px 0 24px 0;">

## 🔵 👤 用户提问

我希望你帮我升级，但要保留硬编码路径


<hr style="border: 0; border-top: 5px solid #9333EA; margin: 48px 0 24px 0;">

## 🟣 🤖 AI 回答

可以。下面这个版本我建议你直接替换原脚本。**所有路径继续硬编码**，不改成命令行参数，也不改成让你每次输入路径。

这版重点解决了你原代码里最严重的问题：**PDF 不再依赖“接着上次的 ReportLab PDF 继续写”**，而是采用“每页翻译结果缓存 → 随时可以从缓存重建 PDF”的方式。因此电脑崩溃、程序中断、额度耗尽后，已经完成的内容不会变成空白页。

Python

`import os
import re
import json
import time
import random
import hashlib
from datetime import datetime
from typing import Optional, Tuple, List, Dict
import pdfplumber
import requests
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
# ============================================================
# 0. 配置
# 按你的要求：保留硬编码路径
# ============================================================
INPUT_PDF = r"D:\小说\哈利波特\Harry Potter.pdf"
OUTPUT_PDF = r"D:\小说\哈利波特\Harry Potter_translated.pdf"
# 状态文件也固定放在小说目录
QUOTA_FILE = r"D:\小说\哈利波特\translation_quota.json"
PROGRESS_FILE = r"D:\小说\哈利波特\translation_progress.json"
CACHE_DIR = r"D:\小说\哈利波特\translation_cache"
# 你原来的额度设置
MONTHLY_FREE_QUOTA = 1_000_000
# 百度翻译 API
BAIDU_URL = "https://fanyi-api.baidu.com/api/trans/vip/translate"
SOURCE_LANG = "en"
TARGET_LANG = "zh"
# 每次 API 请求的字符上限。
# 这里故意留安全余量，不建议直接顶到接口极限。
MAX_CHARS_PER_REQUEST = 4_000
# API 重试
MAX_RETRIES = 3
RETRY_BASE_SECONDS = 2
# PDF 排版
FONT_NAME = "STSong-Light"
FONT_SIZE = 11
LINE_HEIGHT = 16
MARGIN = 30
FOOTER_SIZE = 8
# ============================================================
# 1. 初始化
# ============================================================
os.makedirs(CACHE_DIR, exist_ok=True)
pdfmetrics.registerFont(UnicodeCIDFont(FONT_NAME))
try:
APPID = os.environ["BAIDU_FANYI_APPID"]
SECRET_KEY = os.environ["BAIDU_FANYI_SECRET"]
except KeyError:
raise RuntimeError(
"请先设置环境变量 BAIDU_FANYI_APPID 和 BAIDU_FANYI_SECRET"
)
# 复用 HTTP 连接
SESSION = requests.Session()
# ============================================================
# 2. JSON 原子写入
# ============================================================
def atomic_write_json(path: str, data: dict) -> None:
"""
先写临时文件，再原子替换。
防止程序突然退出导致 JSON 文件写坏。
"""
directory = os.path.dirname(path)
if directory:
os.makedirs(directory, exist_ok=True)
temp_path = path + ".tmp"
with open(temp_path, "w", encoding="utf-8") as f:
json.dump(data, f, ensure_ascii=False, indent=2)
os.replace(temp_path, path)
# ============================================================
# 3. 月度额度管理
# ============================================================
def current_month() -> str:
return datetime.now().strftime("%Y-%m-01")
def load_quota() -> Dict:
if not os.path.exists(QUOTA_FILE):
return {
"used_chars": 0,
"last_reset_date": current_month(),
}
try:
with open(QUOTA_FILE, "r", encoding="utf-8") as f:
data = json.load(f)
return {
"used_chars": int(data.get("used_chars", 0)),
"last_reset_date": data.get(
"last_reset_date",
current_month()
),
}
except (OSError, ValueError, TypeError, json.JSONDecodeError):
print("⚠️ 额度文件损坏，将重新初始化。")
return {
"used_chars": 0,
"last_reset_date": current_month(),
}
def save_quota(used_chars: int) -> None:
atomic_write_json(
QUOTA_FILE,
{
"used_chars": int(used_chars),
"last_reset_date": current_month(),
}
)
def check_and_reset_quota() -> int:
data = load_quota()
month = current_month()
if data["last_reset_date"] != month:
save_quota(0)
print("🔄 新月份，程序记录的额度已重置为 100 万字符")
return 0
return max(0, data["used_chars"])
def sync_quota_from_cache() -> int:
"""
启动时根据成功缓存的页面核对额度。
用于解决：
API 成功
↓
页面缓存已经保存
↓
电脑突然断电
↓
quota.json 还没来得及保存
下次运行时可以根据缓存恢复额度记录。
"""
used = check_and_reset_quota()
month = current_month()
cached_cost = 0
try:
filenames = os.listdir(CACHE_DIR)
except OSError:
return used
for filename in filenames:
if not filename.endswith(".json"):
continue
path = os.path.join(CACHE_DIR, filename)
try:
with open(path, "r", encoding="utf-8") as f:
data = json.load(f)
if (
data.get("status") == "completed"
and data.get("usage_month") == month
):
cached_cost += int(data.get("cost_chars", 0))
except (OSError, ValueError, TypeError, json.JSONDecodeError):
continue
corrected = max(used, cached_cost)
if corrected != used:
save_quota(corrected)
print(
f"🔧 根据缓存校正额度："
f"{corrected}/{MONTHLY_FREE_QUOTA}"
)
return corrected
def check_quota(text_len: int) -> Tuple[bool, int, int]:
used = check_and_reset_quota()
remaining = max(0, MONTHLY_FREE_QUOTA - used)
return remaining >= text_len, used, remaining
def add_used_chars(chars: int) -> int:
"""
注意：
这里不要再调用 sync_quota_from_cache()。
因为当前页缓存已经写入后，
再从缓存统计一次会把当前页重复计算。
"""
used = check_and_reset_quota()
new_used = used + chars
save_quota(new_used)
return new_used
# ============================================================
# 4. 断点进度管理
# ============================================================
def load_progress() -> Dict:
if not os.path.exists(PROGRESS_FILE):
return {
"last_finished_page": 0,
"total_pages": None,
"input_pdf": INPUT_PDF,
}
try:
with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
data = json.load(f)
return {
"last_finished_page": int(
data.get("last_finished_page", 0)
),
"total_pages": data.get("total_pages"),
"input_pdf": data.get("input_pdf", INPUT_PDF),
}
except (OSError, ValueError, TypeError, json.JSONDecodeError):
return {
"last_finished_page": 0,
"total_pages": None,
"input_pdf": INPUT_PDF,
}
def save_progress(
last_finished_page: int,
total_pages: int
) -> None:
atomic_write_json(
PROGRESS_FILE,
{
"last_finished_page": int(last_finished_page),
"total_pages": int(total_pages),
"input_pdf": INPUT_PDF,
"updated_at": datetime.now().isoformat(
timespec="seconds"
),
}
)
def clear_progress() -> None:
try:
if os.path.exists(PROGRESS_FILE):
os.remove(PROGRESS_FILE)
except OSError:
pass
# ============================================================
# 5. 页面缓存
# ============================================================
def page_cache_path(page_num: int) -> str:
return os.path.join(
CACHE_DIR,
f"page_{page_num:04d}.json"
)
def text_hash(text: str) -> str:
return hashlib.sha256(
text.encode("utf-8")
).hexdigest()
def load_page_cache(
page_num: int,
source_text: str
) -> Optional[Dict]:
path = page_cache_path(page_num)
if not os.path.exists(path):
return None
try:
with open(path, "r", encoding="utf-8") as f:
data = json.load(f)
if data.get("status") != "completed":
return None
# 防止换了 PDF 后错误使用旧缓存
if data.get("source_hash") != text_hash(source_text):
return None
if "translated_text" not in data:
return None
return data
except (OSError, ValueError, TypeError, json.JSONDecodeError):
return None
def save_page_cache(
page_num: int,
source_text: str,
translated_text: str,
cost_chars: int
) -> None:
data = {
"status": "completed",
"page_num": page_num,
"source_hash": text_hash(source_text),
"input_chars": len(source_text),
"cost_chars": int(cost_chars),
"translated_text": translated_text,
"usage_month": current_month(),
"completed_at": datetime.now().isoformat(
timespec="seconds"
),
}
atomic_write_json(
page_cache_path(page_num),
data
)
# ============================================================
# 6. 文本清洗
# ============================================================
def normalize_text(text: str) -> str:
if not text:
return ""
text = text.replace("\r\n", "\n")
text = text.replace("\r", "\n")
# 压缩连续空格
lines = []
for line in text.split("\n"):
line = re.sub(r"[ \t]+", " ", line).strip()
lines.append(line)
# 最多保留一个连续空行
cleaned = []
blank_count = 0
for line in lines:
if line:
cleaned.append(line)
blank_count = 0
else:
blank_count += 1
if blank_count <= 1:
cleaned.append("")
return "\n".join(cleaned).strip()
# ============================================================
# 7. 英文文本智能分块
# ============================================================
ABBREVIATIONS = [
"Mr.",
"Mrs.",
"Ms.",
"Dr.",
"Prof.",
"St.",
"Jr.",
"Sr.",
"Inc.",
"Ltd.",
"e.g.",
"i.e.",
"vs.",
"No.",
"Fig.",
]
def protect_abbreviations(text: str) -> str:
for abbr in ABBREVIATIONS:
protected = abbr.replace(".", "<DOT>")
text = text.replace(abbr, protected)
return text
def restore_abbreviations(text: str) -> str:
return text.replace("<DOT>", ".")
def split_long_piece(
text: str,
max_len: int
) -> List[str]:
"""
单个句子本身超过 API 长度时：
优先按空格切；
连续无空格时最后才硬切。
"""
text = text.strip()
if not text:
return []
if len(text) <= max_len:
return [text]
pieces = []
current = ""
tokens = re.split(r"(\s+)", text)
for token in tokens:
if not token:
continue
if len(current) + len(token) <= max_len:
current += token
continue
if current.strip():
pieces.append(current.strip())
current = ""
# 当前 token 自身就超过限制
while len(token) > max_len:
pieces.append(token[:max_len])
token = token[max_len:]
current = token
if current.strip():
pieces.append(current.strip())
return pieces
def split_paragraph(
paragraph: str,
max_len: int
) -> List[str]:
protected = protect_abbreviations(paragraph)
# 尽量按照句号、问号、感叹号分句
sentences = re.split(
r'(?<=[.!?]["\')\]”’]?)'
r'\s+'
r'(?=[A-Z0-9“"\'(])',
protected
)
sentences = [
restore_abbreviations(sentence).strip()
for sentence in sentences
if sentence.strip()
]
chunks = []
current = ""
for sentence in sentences:
pieces = split_long_piece(
sentence,
max_len
)
for piece in pieces:
if len(current) + len(piece) + 1 <= max_len:
current = (
f"{current} {piece}"
).strip()
else:
if current:
chunks.append(current)
current = piece
if current:
chunks.append(current)
return chunks
def split_text(
text: str,
max_len: int = MAX_CHARS_PER_REQUEST
) -> List[str]:
text = normalize_text(text)
if not text:
return []
if len(text) <= max_len:
return [text]
blocks = []
# 双换行作为段落边界
paragraphs = re.split(
r"\n\s*\n",
text
)
for paragraph in paragraphs:
paragraph = paragraph.strip()
if not paragraph:
continue
paragraph_blocks = split_paragraph(
paragraph,
max_len
)
for block in paragraph_blocks:
if len(block) <= max_len:
blocks.append(block)
else:
blocks.extend(
split_long_piece(
block,
max_len
)
)
return blocks
# ============================================================
# 8. 百度翻译 API
# ============================================================
def baidu_translate_block(
q: str
) -> Tuple[str, int]:
q = q.strip()
if not q:
return "", 0
salt = str(
random.randint(1, 10000)
)
sign = hashlib.md5(
(
APPID
+ q
+ salt
+ SECRET_KEY
).encode("utf-8")
).hexdigest()
last_error = None
for attempt in range(
1,
MAX_RETRIES + 1
):
try:
response = SESSION.post(
BAIDU_URL,
data={
"q": q,
"from": SOURCE_LANG,
"to": TARGET_LANG,
"appid": APPID,
"salt": salt,
"sign": sign,
},
timeout=(10, 30),
)
response.raise_for_status()
try:
result = response.json()
except ValueError as e:
raise RuntimeError(
"百度 API 返回的不是合法 JSON"
) from e
if "trans_result" in result:
translated_parts = []
for item in result["trans_result"]:
dst = item.get("dst")
if dst is not None:
translated_parts.append(dst)
translated = "\n".join(
translated_parts
).strip()
return translated, len(q)
error_code = result.get(
"error_code",
"未知"
)
error_msg = result.get(
"error_msg",
""
)
raise RuntimeError(
f"百度 API 失败："
f"error_code={error_code}, "
f"error_msg={error_msg}"
)
except (
requests.RequestException,
RuntimeError
) as e:
last_error = e
if attempt < MAX_RETRIES:
wait_seconds = (
RETRY_BASE_SECONDS ** attempt
)
print(
f" ⚠️ API 请求失败，"
f"第 {attempt}/{MAX_RETRIES} 次重试"
)
print(
f" {e}"
)
time.sleep(
wait_seconds
)
else:
break
raise RuntimeError(
f"连续 {MAX_RETRIES} 次失败："
f"{last_error}"
)
def baidu_translate(
text: str
) -> Tuple[str, int]:
text = normalize_text(text)
if not text:
return "", 0
enough, used, remaining = check_quota(
len(text)
)
if not enough:
raise RuntimeError(
f"本月额度不足："
f"已用 {used}/{MONTHLY_FREE_QUOTA}，"
f"剩余 {remaining}，"
f"本页需要约 {len(text)} 字符。"
)
blocks = split_text(text)
if not blocks:
return "", 0
results = []
total_cost = 0
for index, block in enumerate(
blocks,
start=1
):
print(
f" API 请求 "
f"{index}/{len(blocks)}，"
f"本块 {len(block)} 字符"
)
translated, cost = (
baidu_translate_block(
block
)
)
results.append(translated)
total_cost += cost
# 稍微降低连续请求过快的风险
if index < len(blocks):
time.sleep(0.3)
translated_text = "\n\n".join(
x for x in results
if x.strip()
)
return translated_text, total_cost
# ============================================================
# 9. 中文/英文混排自动换行
# ============================================================
def wrap_text_to_lines(
text: str,
max_width: float,
font_name: str,
font_size: float
) -> List[str]:
lines = []
# 保留原有换行
for paragraph in text.split("\n"):
paragraph = paragraph.strip()
if not paragraph:
lines.append("")
continue
current = ""
last_space_pos = -1
for ch in paragraph:
test = current + ch
if pdfmetrics.stringWidth(
test,
font_name,
font_size
) <= max_width:
current = test
if ch.isspace():
last_space_pos = (
len(current) - 1
)
continue
# 当前行已经超宽
if current.strip():
# 如果是英文，优先在最近空格处换行
if last_space_pos > 0:
line = (
current[:last_space_pos]
.rstrip()
)
remainder = (
current[last_space_pos + 1:]
+ ch
)
lines.append(line)
current = (
remainder
.lstrip()
)
else:
lines.append(
current.rstrip()
)
current = ch
else:
current = ch
last_space_pos = (
len(current) - 1
if current
and current[-1].isspace()
else -1
)
if current.strip():
lines.append(
current.rstrip()
)
return lines
# ============================================================
# 10. 页脚
# ============================================================
def draw_footer(
c,
page_width: float,
source_page_num: int,
continued: bool
):
footer = (
f"原 PDF 第 {source_page_num} 页"
)
if continued:
footer += "（续）"
c.setFont(
FONT_NAME,
FOOTER_SIZE
)
c.drawCentredString(
page_width / 2,
12,
footer
)
# ============================================================
# 11. 从缓存重建 PDF
# ============================================================
def rebuild_output_pdf(
input_pdf: str
) -> None:
print("\n📄 正在从翻译缓存生成 PDF...")
with pdfplumber.open(input_pdf) as pdf:
c = canvas.Canvas(
OUTPUT_PDF
)
completed_pages = 0
for idx, page in enumerate(
pdf.pages,
start=1
):
source_text = normalize_text(
page.extract_text() or ""
)
cache = load_page_cache(
idx,
source_text
)
# 一旦出现缺失页，就停止。
# 避免 1、2、3、5 页都有，4 页没有时，
# 输出 PDF 出现页码错乱。
if cache is None:
print(
f" ⏹ PDF 重建到第 "
f"{idx - 1} 页停止"
)
break
translated_text = (
cache.get(
"translated_text",
""
).strip()
)
# 空白页
if not translated_text:
c.setPageSize(
(page.width, page.height)
)
draw_footer(
c,
page.width,
idx,
False
)
c.showPage()
completed_pages += 1
continue
c.setPageSize(
(page.width, page.height)
)
max_width = (
page.width
- 2 * MARGIN
)
y = (
page.height
- MARGIN
)
lines = wrap_text_to_lines(
translated_text,
max_width,
FONT_NAME,
FONT_SIZE
)
continued = False
for line in lines:
if y < (
MARGIN
+ FOOTER_SIZE
+ 10
):
draw_footer(
c,
page.width,
idx,
continued
)
c.showPage()
c.setPageSize(
(
page.width,
page.height
)
)
c.setFont(
FONT_NAME,
FONT_SIZE
)
y = (
page.height
- MARGIN
)
continued = True
if line == "":
y -= LINE_HEIGHT
continue
c.setFont(
FONT_NAME,
FONT_SIZE
)
c.drawString(
MARGIN,
y,
line
)
y -= LINE_HEIGHT
draw_footer(
c,
page.width,
idx,
continued
)
c.showPage()
completed_pages += 1
c.save()
print(
f"✅ PDF 已保存：{OUTPUT_PDF}"
)
print(
f"📄 已写入 {completed_pages} 个原 PDF 页面"
)
# ============================================================
# 12. 主翻译流程
# ============================================================
def translate_pdf_resumable(
input_pdf: str
) -> None:
if not os.path.exists(input_pdf):
raise FileNotFoundError(
f"找不到输入 PDF：{input_pdf}"
)
# 程序启动时先根据缓存校正一次额度
current_used = sync_quota_from_cache()
progress = load_progress()
print("=" * 65)
print("📚 PDF 自动翻译程序")
print("=" * 65)
print(f"输入文件：{input_pdf}")
print(f"输出文件：{OUTPUT_PDF}")
print(f"缓存目录：{CACHE_DIR}")
print(
f"当前额度："
f"{current_used}/{MONTHLY_FREE_QUOTA}"
)
print(
f"上次完成页："
f"{progress.get('last_finished_page', 0)}"
)
print("=" * 65)
with pdfplumber.open(input_pdf) as pdf:
total_pages = len(pdf.pages)
print(
f"📖 PDF 总页数：{total_pages}"
)
last_finished_page = (
progress.get(
"last_finished_page",
0
)
)
for idx, page in enumerate(
pdf.pages,
start=1
):
print(
f"\n========== "
f"第 {idx}/{total_pages} 页 "
f"=========="
)
# ------------------------------------------------
# A. 提取文字
# ------------------------------------------------
try:
source_text = normalize_text(
page.extract_text() or ""
)
except Exception as e:
print(
f"❌ 第 {idx} 页文本提取失败：{e}"
)
print(
" 当前页不会被标记为完成。"
)
rebuild_output_pdf(
input_pdf
)
save_progress(
last_finished_page,
total_pages
)
return
# ------------------------------------------------
# B. 优先检查缓存
# ------------------------------------------------
cached = load_page_cache(
idx,
source_text
)
if cached is not None:
print(
"♻️ 发现有效缓存，"
"跳过 API 翻译。"
)
last_finished_page = idx
save_progress(
last_finished_page,
total_pages
)
continue
# ------------------------------------------------
# C. 空白页
# ------------------------------------------------
if not source_text:
print(
"📄 本页没有可提取文字，"
"记为空白页。"
)
save_page_cache(
page_num=idx,
source_text="",
translated_text="",
cost_chars=0
)
last_finished_page = idx
save_progress(
last_finished_page,
total_pages
)
continue
# ------------------------------------------------
# D. 检查额度
# ------------------------------------------------
enough, used, remaining = (
check_quota(
len(source_text)
)
)
print(
f"本页字符数：{len(source_text)}"
)
print(
f"本月已用："
f"{used}/{MONTHLY_FREE_QUOTA}"
)
print(
f"本月剩余："
f"{remaining}"
)
if not enough:
print(
"\n⛔ 本月额度不足，"
"停止翻译。"
)
print(
f"✅ 已成功完成到第 "
f"{last_finished_page} 页"
)
# 根据已经成功缓存的内容更新 PDF
rebuild_output_pdf(
input_pdf
)
save_progress(
last_finished_page,
total_pages
)
return
# ------------------------------------------------
# E. 翻译本页
# ------------------------------------------------
try:
translated_text, cost = (
baidu_translate(
source_text
)
)
except Exception as e:
print(
f"\n❌ 第 {idx} 页翻译失败："
f"{e}"
)
print(
"⚠️ 当前页不会建立完成缓存。"
)
print(
" 下次运行会自动重新翻译这一页。"
)
# 已完成的部分仍然生成 PDF
rebuild_output_pdf(
input_pdf
)
save_progress(
last_finished_page,
total_pages
)
return
# ------------------------------------------------
# F. 先保存页面缓存
# ------------------------------------------------
# 这是整个断点续传机制的核心
save_page_cache(
page_num=idx,
source_text=source_text,
translated_text=translated_text,
cost_chars=cost
)
print(
f"💾 第 {idx} 页翻译结果已保存到缓存"
)
# ------------------------------------------------
# G. 再更新额度
# ------------------------------------------------
if cost > 0:
new_used = add_used_chars(
cost
)
print(
f"📊 当前额度："
f"{new_used}/"
f"{MONTHLY_FREE_QUOTA}"
)
# ------------------------------------------------
# H. 最后更新进度
# ------------------------------------------------
last_finished_page = idx
save_progress(
last_finished_page,
total_pages
)
print(
f"✅ 第 {idx} 页完成"
)
# ====================================================
# I. 检查是否全部完成
# ====================================================
print(
"\n🔍 正在检查是否所有页面都有有效缓存..."
)
all_completed = True
for idx, page in enumerate(
pdf.pages,
start=1
):
source_text = normalize_text(
page.extract_text() or ""
)
if load_page_cache(
idx,
source_text
) is None:
all_completed = False
print(
f"⚠️ 第 {idx} 页没有有效缓存"
)
break
# ====================================================
# J. 生成最终 PDF
# ====================================================
rebuild_output_pdf(
input_pdf
)
if all_completed:
clear_progress()
print("\n" + "=" * 65)
print("🎉 全书翻译完成！")
print("=" * 65)
print(
f"📄 输出：{OUTPUT_PDF}"
)
print(
f"📦 缓存：{CACHE_DIR}"
)
else:
print("\n⚠️ 当前还没有全部完成。")
print(
" 下次运行时会自动跳过已经完成的页面。"
)
# ============================================================
# 13. 运行
# ============================================================
if __name__ == "__main__":
try:
translate_pdf_resumable(
INPUT_PDF
)
except KeyboardInterrupt:
print(
"\n\n🛑 检测到手动中断。"
)
print(
"正在根据已经完成的缓存生成 PDF..."
)
try:
rebuild_output_pdf(
INPUT_PDF
)
print(
"✅ 已保存当前已完成内容。"
)
except Exception as e:
print(
f"⚠️ PDF 保存失败：{e}"
)
except Exception as e:
print(
f"\n❌ 程序发生未处理异常：{e}"
)
# 即使程序出现异常，
# 也尽量把已经成功缓存的页面做成 PDF
try:
rebuild_output_pdf(
INPUT_PDF
)
print(
"✅ 已根据缓存保存当前已完成内容。"
)
except Exception as pdf_error:
print(
f"⚠️ 无法重建 PDF：{pdf_error}"
)
raise`

### 这版和你原版最大的区别

**第一，真正的断点续传。**

程序会在：

纯文本

`D:\小说\哈利波特\translation_cache\`

生成：

纯文本

`page_0001.json
page_0002.json
page_0003.json
...`

例如翻译到第 237 页突然断电：

纯文本

`page_0001.json ✅
page_0002.json ✅
...
page_0237.json ✅
page_0238.json ❌`

再次运行时，1～237 页全部直接读取缓存，不再浪费百度额度，从 238 页继续。

更重要的是，**不会像原版那样重新创建一个 PDF，然后把前面页面变成空白页。**

---

**第二，API 失败不会被误判成“已经完成”。**

你的原代码可能产生：

纯文本

`[失败:54003]`

然后仍然：

Python

`save_progress(current_page_num)`

导致这一页永远被跳过去。

现在改成：

纯文本

`API失败
↓
自动重试 3 次
↓
还失败
↓
当前页不建立完成缓存
↓
下一次运行重新翻译`

这样安全很多。

---

**第三，程序突然关闭也尽量不丢翻译。**

我把保存顺序设计成：

纯文本

`百度翻译成功
↓
保存 page_xxxx.json
↓
更新额度
↓
更新 progress`

而且 JSON 都使用临时文件 + 原子替换。

所以突然关机时，最坏的情况一般只是**当前页需要重新尝试**，不会让前面几十页的结果消失。

---

**第四，缓存增加了 source\_hash。**

例如你后来把：

纯文本

`Harry Potter.pdf`

换成另一个版本，哪怕文件名完全一样：

纯文本

`D:\小说\哈利波特\Harry Potter.pdf`

程序也会比较每页的 SHA-256：

纯文本

`旧页面文字 hash
VS
新页面文字 hash`

不一致就不会错误使用旧翻译缓存。

---

**第五，我改掉了原来的：**

Python

`text.replace("\n", " ").split(". ")`

这种切法。

因为小说里有：

纯文本

`Mr. Potter
Mrs. Weasley
Dr. ...`

简单 split(". ") 很容易把句子切错。

现在会先处理常见缩写，再根据句子边界和长度进行分块。

---

**第六，保留了你原来的硬编码路径。**

仍然直接：

Python

`INPUT_PDF = r"D:\小说\哈利波特\Harry Potter.pdf"
OUTPUT_PDF = r"D:\小说\哈利波特\Harry Potter_translated.pdf"`

你不需要每次运行输入路径。

---

### 运行前要准备

你原来需要的库基本不变：

Bash

`pip install pdfplumber requests reportlab`

然后环境变量继续使用：

纯文本

`BAIDU_FANYI_APPID
BAIDU_FANYI_SECRET`

---

### 还有一个我建议下一步继续升级的地方

现在这版已经把\*\*“稳定翻译”\*\*解决得比较好了，但 PDF 的文本提取仍然依赖 pdfplumber.extract\_text()。

对于《哈利·波特》这类小说，下一步最值得升级的是\*\*“段落识别 + 章节标题识别 + 更好的小说排版”\*\*。这样最终生成的中文 PDF 会从现在的“翻译后的文字 PDF”，提升到更像一本真正的中文电子书。


<hr style="border: 0; border-top: 5px solid #2563EB; margin: 48px 0 24px 0;">

## 🔵 👤 用户提问

保持现在这样，不要再改了，但请你直接给我替换后的代码


<hr style="border: 0; border-top: 5px solid #9333EA; margin: 48px 0 24px 0;">

## 🟣 🤖 AI 回答

可以。下面就是**可直接替换你原代码的完整版本**。我保持上一版的功能，不再额外增加新的改动；同时继续保留你要求的**硬编码路径**。

Python

`import os
import re
import json
import time
import random
import hashlib
from datetime import datetime
from typing import Optional, Tuple, List, Dict
import pdfplumber
import requests
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
# ============================================================
# 0. 配置
# 按要求：保留硬编码路径
# ============================================================
INPUT_PDF = r"D:\小说\哈利波特\Harry Potter.pdf"
OUTPUT_PDF = r"D:\小说\哈利波特\Harry Potter_translated.pdf"
# 状态文件
QUOTA_FILE = r"D:\小说\哈利波特\translation_quota.json"
PROGRESS_FILE = r"D:\小说\哈利波特\translation_progress.json"
CACHE_DIR = r"D:\小说\哈利波特\translation_cache"
# 每月额度
MONTHLY_FREE_QUOTA = 1_000_000
# 百度翻译 API
BAIDU_URL = "https://fanyi-api.baidu.com/api/trans/vip/translate"
SOURCE_LANG = "en"
TARGET_LANG = "zh"
# 单次 API 请求最大字符数
MAX_CHARS_PER_REQUEST = 4_000
# API 重试次数
MAX_RETRIES = 3
RETRY_BASE_SECONDS = 2
# PDF 排版
FONT_NAME = "STSong-Light"
FONT_SIZE = 11
LINE_HEIGHT = 16
MARGIN = 30
FOOTER_SIZE = 8
# ============================================================
# 1. 初始化
# ============================================================
os.makedirs(CACHE_DIR, exist_ok=True)
pdfmetrics.registerFont(
UnicodeCIDFont(FONT_NAME)
)
try:
APPID = os.environ["BAIDU_FANYI_APPID"]
SECRET_KEY = os.environ["BAIDU_FANYI_SECRET"]
except KeyError:
raise RuntimeError(
"请先设置环境变量 BAIDU_FANYI_APPID 和 BAIDU_FANYI_SECRET"
)
# 复用 HTTP 连接
SESSION = requests.Session()
# ============================================================
# 2. JSON 原子写入
# ============================================================
def atomic_write_json(path: str, data: dict) -> None:
"""
先写临时文件，再原子替换。
防止程序突然退出导致 JSON 文件损坏。
"""
directory = os.path.dirname(path)
if directory:
os.makedirs(directory, exist_ok=True)
temp_path = path + ".tmp"
with open(temp_path, "w", encoding="utf-8") as f:
json.dump(
data,
f,
ensure_ascii=False,
indent=2
)
os.replace(temp_path, path)
# ============================================================
# 3. 月度额度管理
# ============================================================
def current_month() -> str:
return datetime.now().strftime("%Y-%m-01")
def load_quota() -> Dict:
if not os.path.exists(QUOTA_FILE):
return {
"used_chars": 0,
"last_reset_date": current_month()
}
try:
with open(
QUOTA_FILE,
"r",
encoding="utf-8"
) as f:
data = json.load(f)
return {
"used_chars": int(
data.get("used_chars", 0)
),
"last_reset_date": data.get(
"last_reset_date",
current_month()
)
}
except (
OSError,
ValueError,
TypeError,
json.JSONDecodeError
):
print("⚠️ 额度文件损坏，将重新初始化。")
return {
"used_chars": 0,
"last_reset_date": current_month()
}
def save_quota(used_chars: int) -> None:
atomic_write_json(
QUOTA_FILE,
{
"used_chars": int(used_chars),
"last_reset_date": current_month()
}
)
def check_and_reset_quota() -> int:
data = load_quota()
month = current_month()
if data["last_reset_date"] != month:
save_quota(0)
print(
"🔄 新月份，"
"程序记录的额度已重置为 100 万字符"
)
return 0
return max(
0,
data["used_chars"]
)
def sync_quota_from_cache() -> int:
"""
根据成功缓存的页面核对额度。
用于防止：
API 成功
↓
页面缓存保存成功
↓
程序突然退出
↓
quota.json 尚未来得及更新
"""
used = check_and_reset_quota()
month = current_month()
cached_cost = 0
try:
filenames = os.listdir(
CACHE_DIR
)
except OSError:
return used
for filename in filenames:
if not filename.endswith(".json"):
continue
path = os.path.join(
CACHE_DIR,
filename
)
try:
with open(
path,
"r",
encoding="utf-8"
) as f:
data = json.load(f)
if (
data.get("status") == "completed"
and data.get("usage_month") == month
):
cached_cost += int(
data.get("cost_chars", 0)
)
except (
OSError,
ValueError,
TypeError,
json.JSONDecodeError
):
continue
corrected = max(
used,
cached_cost
)
if corrected != used:
save_quota(corrected)
print(
f"🔧 根据缓存校正额度："
f"{corrected}/{MONTHLY_FREE_QUOTA}"
)
return corrected
def check_quota(
text_len: int
) -> Tuple[bool, int, int]:
used = check_and_reset_quota()
remaining = max(
0,
MONTHLY_FREE_QUOTA - used
)
return (
remaining >= text_len,
used,
remaining
)
def add_used_chars(
chars: int
) -> int:
used = check_and_reset_quota()
new_used = used + chars
save_quota(new_used)
return new_used
# ============================================================
# 4. 断点进度管理
# ============================================================
def load_progress() -> Dict:
if not os.path.exists(PROGRESS_FILE):
return {
"last_finished_page": 0,
"total_pages": None,
"input_pdf": INPUT_PDF
}
try:
with open(
PROGRESS_FILE,
"r",
encoding="utf-8"
) as f:
data = json.load(f)
return {
"last_finished_page": int(
data.get(
"last_finished_page",
0
)
),
"total_pages": data.get(
"total_pages"
),
"input_pdf": data.get(
"input_pdf",
INPUT_PDF
)
}
except (
OSError,
ValueError,
TypeError,
json.JSONDecodeError
):
return {
"last_finished_page": 0,
"total_pages": None,
"input_pdf": INPUT_PDF
}
def save_progress(
last_finished_page: int,
total_pages: int
) -> None:
atomic_write_json(
PROGRESS_FILE,
{
"last_finished_page":
int(last_finished_page),
"total_pages":
int(total_pages),
"input_pdf":
INPUT_PDF,
"updated_at":
datetime.now().isoformat(
timespec="seconds"
)
}
)
def clear_progress() -> None:
try:
if os.path.exists(
PROGRESS_FILE
):
os.remove(
PROGRESS_FILE
)
except OSError:
pass
# ============================================================
# 5. 页面缓存
# ============================================================
def page_cache_path(
page_num: int
) -> str:
return os.path.join(
CACHE_DIR,
f"page_{page_num:04d}.json"
)
def text_hash(
text: str
) -> str:
return hashlib.sha256(
text.encode("utf-8")
).hexdigest()
def load_page_cache(
page_num: int,
source_text: str
) -> Optional[Dict]:
path = page_cache_path(
page_num
)
if not os.path.exists(path):
return None
try:
with open(
path,
"r",
encoding="utf-8"
) as f:
data = json.load(f)
if data.get("status") != "completed":
return None
# 防止换 PDF 后误用旧缓存
if (
data.get("source_hash")
!= text_hash(source_text)
):
return None
if "translated_text" not in data:
return None
return data
except (
OSError,
ValueError,
TypeError,
json.JSONDecodeError
):
return None
def save_page_cache(
page_num: int,
source_text: str,
translated_text: str,
cost_chars: int
) -> None:
data = {
"status": "completed",
"page_num": page_num,
"source_hash":
text_hash(source_text),
"input_chars":
len(source_text),
"cost_chars":
int(cost_chars),
"translated_text":
translated_text,
"usage_month":
current_month(),
"completed_at":
datetime.now().isoformat(
timespec="seconds"
)
}
atomic_write_json(
page_cache_path(page_num),
data
)
# ============================================================
# 6. 文本清洗
# ============================================================
def normalize_text(
text: str
) -> str:
if not text:
return ""
text = text.replace(
"\r\n",
"\n"
)
text = text.replace(
"\r",
"\n"
)
lines = []
for line in text.split("\n"):
line = re.sub(
r"[ \t]+",
" ",
line
).strip()
lines.append(line)
cleaned = []
blank_count = 0
for line in lines:
if line:
cleaned.append(line)
blank_count = 0
else:
blank_count += 1
if blank_count <= 1:
cleaned.append("")
return "\n".join(
cleaned
).strip()
# ============================================================
# 7. 英文文本智能分块
# ============================================================
ABBREVIATIONS = [
"Mr.",
"Mrs.",
"Ms.",
"Dr.",
"Prof.",
"St.",
"Jr.",
"Sr.",
"Inc.",
"Ltd.",
"e.g.",
"i.e.",
"vs.",
"No.",
"Fig."
]
def protect_abbreviations(
text: str
) -> str:
for abbr in ABBREVIATIONS:
protected = abbr.replace(
".",
"<DOT>"
)
text = text.replace(
abbr,
protected
)
return text
def restore_abbreviations(
text: str
) -> str:
return text.replace(
"<DOT>",
"."
)
def split_long_piece(
text: str,
max_len: int
) -> List[str]:
text = text.strip()
if not text:
return []
if len(text) <= max_len:
return [text]
pieces = []
current = ""
tokens = re.split(
r"(\s+)",
text
)
for token in tokens:
if not token:
continue
if (
len(current)
+ len(token)
<= max_len
):
current += token
continue
if current.strip():
pieces.append(
current.strip()
)
current = ""
# 如果 token 本身超过限制
while len(token) > max_len:
pieces.append(
token[:max_len]
)
token = token[max_len:]
current = token
if current.strip():
pieces.append(
current.strip()
)
return pieces
def split_paragraph(
paragraph: str,
max_len: int
) -> List[str]:
protected = protect_abbreviations(
paragraph
)
sentences = re.split(
r'(?<=[.!?]["\')\]”’]?)'
r'\s+'
r'(?=[A-Z0-9“"\'(])',
protected
)
sentences = [
restore_abbreviations(
sentence
).strip()
for sentence in sentences
if sentence.strip()
]
chunks = []
current = ""
for sentence in sentences:
pieces = split_long_piece(
sentence,
max_len
)
for piece in pieces:
if (
len(current)
+ len(piece)
+ 1
<= max_len
):
current = (
f"{current} {piece}"
).strip()
else:
if current:
chunks.append(
current
)
current = piece
if current:
chunks.append(
current
)
return chunks
def split_text(
text: str,
max_len: int = MAX_CHARS_PER_REQUEST
) -> List[str]:
text = normalize_text(text)
if not text:
return []
if len(text) <= max_len:
return [text]
blocks = []
paragraphs = re.split(
r"\n\s*\n",
text
)
for paragraph in paragraphs:
paragraph = paragraph.strip()
if not paragraph:
continue
paragraph_blocks = split_paragraph(
paragraph,
max_len
)
for block in paragraph_blocks:
if len(block) <= max_len:
blocks.append(
block
)
else:
blocks.extend(
split_long_piece(
block,
max_len
)
)
return blocks
# ============================================================
# 8. 百度翻译 API
# ============================================================
def baidu_translate_block(
q: str
) -> Tuple[str, int]:
q = q.strip()
if not q:
return "", 0
salt = str(
random.randint(
1,
10000
)
)
sign = hashlib.md5(
(
APPID
+ q
+ salt
+ SECRET_KEY
).encode("utf-8")
).hexdigest()
last_error = None
for attempt in range(
1,
MAX_RETRIES + 1
):
try:
response = SESSION.post(
BAIDU_URL,
data={
"q": q,
"from": SOURCE_LANG,
"to": TARGET_LANG,
"appid": APPID,
"salt": salt,
"sign": sign
},
timeout=(
10,
30
)
)
response.raise_for_status()
try:
result = response.json()
except ValueError as e:
raise RuntimeError(
"百度 API 返回的不是合法 JSON"
) from e
if "trans_result" in result:
translated_parts = []
for item in result[
"trans_result"
]:
dst = item.get(
"dst"
)
if dst is not None:
translated_parts.append(
dst
)
translated = "\n".join(
translated_parts
).strip()
return (
translated,
len(q)
)
error_code = result.get(
"error_code",
"未知"
)
error_msg = result.get(
"error_msg",
""
)
raise RuntimeError(
f"百度 API 失败："
f"error_code={error_code}, "
f"error_msg={error_msg}"
)
except (
requests.RequestException,
RuntimeError
) as e:
last_error = e
if attempt < MAX_RETRIES:
wait_seconds = (
RETRY_BASE_SECONDS
** attempt
)
print(
f" ⚠️ API 请求失败，"
f"第 {attempt}/{MAX_RETRIES} 次重试"
)
print(
f" {e}"
)
time.sleep(
wait_seconds
)
else:
break
raise RuntimeError(
f"连续 {MAX_RETRIES} 次失败："
f"{last_error}"
)
def baidu_translate(
text: str
) -> Tuple[str, int]:
text = normalize_text(text)
if not text:
return "", 0
enough, used, remaining = (
check_quota(
len(text)
)
)
if not enough:
raise RuntimeError(
f"本月额度不足："
f"已用 {used}/{MONTHLY_FREE_QUOTA}，"
f"剩余 {remaining}，"
f"本页需要约 {len(text)} 字符。"
)
blocks = split_text(text)
if not blocks:
return "", 0
results = []
total_cost = 0
for index, block in enumerate(
blocks,
start=1
):
print(
f" API 请求 "
f"{index}/{len(blocks)}，"
f"本块 {len(block)} 字符"
)
translated, cost = (
baidu_translate_block(
block
)
)
results.append(
translated
)
total_cost += cost
if index < len(blocks):
time.sleep(0.3)
translated_text = "\n\n".join(
x
for x in results
if x.strip()
)
return (
translated_text,
total_cost
)
# ============================================================
# 9. 自动换行
# ============================================================
def wrap_text_to_lines(
text: str,
max_width: float,
font_name: str,
font_size: float
) -> List[str]:
lines = []
for paragraph in text.split(
"\n"
):
paragraph = paragraph.strip()
if not paragraph:
lines.append("")
continue
current = ""
last_space_pos = -1
for ch in paragraph:
test = current + ch
if (
pdfmetrics.stringWidth(
test,
font_name,
font_size
)
<= max_width
):
current = test
if ch.isspace():
last_space_pos = (
len(current) - 1
)
continue
if current.strip():
# 英文优先在空格处换行
if last_space_pos > 0:
line = (
current[
:last_space_pos
].rstrip()
)
remainder = (
current[
last_space_pos + 1:
]
+ ch
)
lines.append(
line
)
current = (
remainder.lstrip()
)
else:
lines.append(
current.rstrip()
)
current = ch
else:
current = ch
last_space_pos = (
len(current) - 1
if current
and current[-1].isspace()
else -1
)
if current.strip():
lines.append(
current.rstrip()
)
return lines
# ============================================================
# 10. 页脚
# ============================================================
def draw_footer(
c,
page_width: float,
source_page_num: int,
continued: bool
):
footer = (
f"原 PDF 第 {source_page_num} 页"
)
if continued:
footer += "（续）"
c.setFont(
FONT_NAME,
FOOTER_SIZE
)
c.drawCentredString(
page_width / 2,
12,
footer
)
# ============================================================
# 11. 根据缓存重建 PDF
# ============================================================
def rebuild_output_pdf(
input_pdf: str
) -> None:
print(
"\n📄 正在从翻译缓存生成 PDF..."
)
with pdfplumber.open(
input_pdf
) as pdf:
c = canvas.Canvas(
OUTPUT_PDF
)
completed_pages = 0
for idx, page in enumerate(
pdf.pages,
start=1
):
source_text = normalize_text(
page.extract_text() or ""
)
cache = load_page_cache(
idx,
source_text
)
# 如果出现缺失页，
# 停止生成后续页面
if cache is None:
print(
f" ⏹ PDF 重建到第 "
f"{idx - 1} 页停止"
)
break
translated_text = (
cache.get(
"translated_text",
""
).strip()
)
# 空白页
if not translated_text:
c.setPageSize(
(
page.width,
page.height
)
)
draw_footer(
c,
page.width,
idx,
False
)
c.showPage()
completed_pages += 1
continue
c.setPageSize(
(
page.width,
page.height
)
)
max_width = (
page.width
- 2 * MARGIN
)
y = (
page.height
- MARGIN
)
lines = wrap_text_to_lines(
translated_text,
max_width,
FONT_NAME,
FONT_SIZE
)
continued = False
for line in lines:
if y < (
MARGIN
+ FOOTER_SIZE
+ 10
):
draw_footer(
c,
page.width,
idx,
continued
)
c.showPage()
c.setPageSize(
(
page.width,
page.height
)
)
c.setFont(
FONT_NAME,
FONT_SIZE
)
y = (
page.height
- MARGIN
)
continued = True
if line == "":
y -= LINE_HEIGHT
continue
c.setFont(
FONT_NAME,
FONT_SIZE
)
c.drawString(
MARGIN,
y,
line
)
y -= LINE_HEIGHT
draw_footer(
c,
page.width,
idx,
continued
)
c.showPage()
completed_pages += 1
c.save()
print(
f"✅ PDF 已保存：{OUTPUT_PDF}"
)
print(
f"📄 已写入 {completed_pages} 个原 PDF 页面"
)
# ============================================================
# 12. 主翻译流程
# ============================================================
def translate_pdf_resumable(
input_pdf: str
) -> None:
if not os.path.exists(
input_pdf
):
raise FileNotFoundError(
f"找不到输入 PDF：{input_pdf}"
)
# 启动时校正额度
current_used = (
sync_quota_from_cache()
)
progress = load_progress()
print("=" * 65)
print("📚 PDF 自动翻译程序")
print("=" * 65)
print(
f"输入文件：{input_pdf}"
)
print(
f"输出文件：{OUTPUT_PDF}"
)
print(
f"缓存目录：{CACHE_DIR}"
)
print(
f"当前额度："
f"{current_used}/"
f"{MONTHLY_FREE_QUOTA}"
)
print(
f"上次完成页："
f"{progress.get('last_finished_page', 0)}"
)
print("=" * 65)
with pdfplumber.open(
input_pdf
) as pdf:
total_pages = len(
pdf.pages
)
print(
f"📖 PDF 总页数："
f"{total_pages}"
)
last_finished_page = (
progress.get(
"last_finished_page",
0
)
)
for idx, page in enumerate(
pdf.pages,
start=1
):
print(
f"\n========== "
f"第 {idx}/{total_pages} 页 "
f"=========="
)
# ------------------------------------------------
# A. 提取文字
# ------------------------------------------------
try:
source_text = normalize_text(
page.extract_text() or ""
)
except Exception as e:
print(
f"❌ 第 {idx} 页文本提取失败：{e}"
)
print(
" 当前页不会被标记为完成。"
)
rebuild_output_pdf(
input_pdf
)
save_progress(
last_finished_page,
total_pages
)
return
# ------------------------------------------------
# B. 检查缓存
# ------------------------------------------------
cached = load_page_cache(
idx,
source_text
)
if cached is not None:
print(
"♻️ 发现有效缓存，"
"跳过 API 翻译。"
)
last_finished_page = idx
save_progress(
last_finished_page,
total_pages
)
continue
# ------------------------------------------------
# C. 空白页
# ------------------------------------------------
if not source_text:
print(
"📄 本页没有可提取文字，"
"记为空白页。"
)
save_page_cache(
page_num=idx,
source_text="",
translated_text="",
cost_chars=0
)
last_finished_page = idx
save_progress(
last_finished_page,
total_pages
)
continue
# ------------------------------------------------
# D. 检查额度
# ------------------------------------------------
enough, used, remaining = (
check_quota(
len(source_text)
)
)
print(
f"本页字符数："
f"{len(source_text)}"
)
print(
f"本月已用："
f"{used}/"
f"{MONTHLY_FREE_QUOTA}"
)
print(
f"本月剩余："
f"{remaining}"
)
if not enough:
print(
"\n⛔ 本月额度不足，"
"停止翻译。"
)
print(
f"✅ 已成功完成到第 "
f"{last_finished_page} 页"
)
rebuild_output_pdf(
input_pdf
)
save_progress(
last_finished_page,
total_pages
)
return
# ------------------------------------------------
# E. 翻译
# ------------------------------------------------
try:
translated_text, cost = (
baidu_translate(
source_text
)
)
except Exception as e:
print(
f"\n❌ 第 {idx} 页翻译失败："
f"{e}"
)
print(
"⚠️ 当前页不会建立完成缓存。"
)
print(
" 下次运行会自动重新翻译这一页。"
)
rebuild_output_pdf(
input_pdf
)
save_progress(
last_finished_page,
total_pages
)
return
# ------------------------------------------------
# F. 保存页面缓存
# ------------------------------------------------
save_page_cache(
page_num=idx,
source_text=source_text,
translated_text=translated_text,
cost_chars=cost
)
print(
f"💾 第 {idx} 页翻译结果已保存到缓存"
)
# ------------------------------------------------
# G. 更新额度
# ------------------------------------------------
if cost > 0:
new_used = add_used_chars(
cost
)
print(
f"📊 当前额度："
f"{new_used}/"
f"{MONTHLY_FREE_QUOTA}"
)
# ------------------------------------------------
# H. 更新进度
# ------------------------------------------------
last_finished_page = idx
save_progress(
last_finished_page,
total_pages
)
print(
f"✅ 第 {idx} 页完成"
)
# ====================================================
# I. 检查是否全部完成
# ====================================================
print(
"\n🔍 正在检查是否所有页面都有有效缓存..."
)
all_completed = True
for idx, page in enumerate(
pdf.pages,
start=1
):
source_text = normalize_text(
page.extract_text() or ""
)
if load_page_cache(
idx,
source_text
) is None:
all_completed = False
print(
f"⚠️ 第 {idx} 页没有有效缓存"
)
break
# ====================================================
# J. 生成 PDF
# ====================================================
rebuild_output_pdf(
input_pdf
)
if all_completed:
clear_progress()
print(
"\n" + "=" * 65
)
print(
"🎉 全书翻译完成！"
)
print(
"=" * 65
)
print(
f"📄 输出：{OUTPUT_PDF}"
)
print(
f"📦 缓存：{CACHE_DIR}"
)
else:
print(
"\n⚠️ 当前还没有全部完成。"
)
print(
" 下次运行时会自动跳过"
"已经完成的页面。"
)
# ============================================================
# 13. 运行
# ============================================================
if __name__ == "__main__":
try:
translate_pdf_resumable(
INPUT_PDF
)
except KeyboardInterrupt:
print(
"\n\n🛑 检测到手动中断。"
)
print(
"正在根据已经完成的缓存生成 PDF..."
)
try:
rebuild_output_pdf(
INPUT_PDF
)
print(
"✅ 已保存当前已完成内容。"
)
except Exception as e:
print(
f"⚠️ PDF 保存失败：{e}"
)
except Exception as e:
print(
f"\n❌ 程序发生未处理异常：{e}"
)
try:
rebuild_output_pdf(
INPUT_PDF
)
print(
"✅ 已根据缓存保存当前已完成内容。"
)
except Exception as pdf_error:
print(
f"⚠️ 无法重建 PDF：{pdf_error}"
)
raise`

直接把你原来的 .py 文件**全部替换成上面这份**即可。

你只需要确保这两个环境变量仍然存在：

纯文本

`BAIDU_FANYI_APPID
BAIDU_FANYI_SECRET`

以及安装：

Bash

```
pip install pdfplumber requests reportlab
```

路径方面**不用改**，仍然是：

纯文本

`D:\小说\哈利波特\Harry Potter.pdf`

输出仍然是：

纯文本

`D:\小说\哈利波特\Harry Potter_translated.pdf`

缓存会自动放到：

纯文本

`D:\小说\哈利波特\translation_cache`

**建议第一次运行前不要删除 translation\_cache、translation\_quota.json 和 translation\_progress.json；如果是全新运行，它们不存在也没关系，程序会自动创建。**

