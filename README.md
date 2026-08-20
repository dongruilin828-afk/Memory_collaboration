# AI 记忆协同管理工具

本项目从 ChatGPT、DeepSeek 和豆包分享页提取完整对话，并可选择调用
Gemini API 或 SiliconFlow 兼容接口，对文字、图片和可用文档进行多模态
分层总结。

## 安装

    uv pip install -r requirements.txt
    playwright install chromium

Gemini 密钥只从当前进程的 GEMINI_API_KEY 读取；SiliconFlow 密钥只从
Silicon_API_KEY（兼容 SILICONFLOW_API_KEY）读取。不要把密钥写进源码、
配置文件、命令参数、日志或提交记录。

## 使用

保持原有行为、只抓取对话：

    uv run python -m scripts.parser

抓取完成后继续调用已配置的总结后端：

    uv run python -m scripts.parser --summarize

临时覆盖集成流程使用的模型：

    uv run python -m scripts.parser --summarize --model gemini-3.6-flash

对已经导出的结果单独总结，不重新打开浏览器：

    uv run python -m scripts.summarize_memory "results/export/ChatGPT_含图片.md"

临时选择其他模型：

    uv run python -m scripts.summarize_memory "results/export/ChatGPT_含图片.md" --model gemini-3.6-flash

也可以通过环境变量长期调整，而不改代码：

    $env:SUMMARY_PROVIDER = "gemini"
    $env:SUMMARY_MODEL = "gemini-3.5-flash"
    $env:GEMINI_CHUNK_CHARS = "24000"
    $env:GEMINI_SHORT_CONVERSATION_CHARS = "18000"
    $env:GEMINI_MAX_OUTPUT_TOKENS = "16384"
    $env:GEMINI_THINKING_LEVEL = "medium"
    $env:GEMINI_API_RETRIES = "3"
    $env:GEMINI_RATE_LIMIT_WAIT_SECONDS = "65"
    $env:GEMINI_MAX_MEDIA_BYTES = "12582912"
    $env:GEMINI_MEDIA_BATCH_SIZE = "6"
    $env:GEMINI_BATCH_INTERVAL_SECONDS = "15"

SUMMARY_MODEL 未设置时默认使用稳定版 gemini-3.5-flash；仍兼容旧变量
GEMINI_MODEL。模型名只在统一配置入口设置，业务调用点不会写死；以后换模型
只需修改环境变量或 --model 参数。

2026-08-16 实测：gemini-3.5-flash 与 gemini-3.6-flash 均可返回结构化
JSON。本轮批量总结优先使用 3.5 Flash；其额度在超长对话中耗尽后，仅对该份
结果显式改用 3.6 Flash。模型可用性和额度会变化，运行时仍应以真实探测为准。

代码不会静默切换模型，以免费用、能力和输出变化在用户不知情时发生。

显式使用 SiliconFlow 的 Qwen 备用模型：

    uv run python -m scripts.summarize_memory "results/export/DeepSeek_超长对话.md" --provider siliconflow --model Qwen/Qwen3.5-397B-A17B

## 总结流水线

1. 程序解析统一消息结构，定位本地图片、PDF、文本附件及失效附件。
2. 总结模型先理解可访问媒体；程序记录附件所属消息、可否重新验证及随后 AI 结论。
3. 程序优先按完整消息边界分块；超长对话分块提取后再综合当前断点和历史主题。
4. 每条记忆显式记录 topic、source、status、message_ids 和 message_range。
5. 编程、语言学习、计算、决策等任务使用不同结构；短消息与上下文指代单独绑定。
6. 程序确定性保留全部用户原始查询和最近 20 条消息（最多最近 10 轮）。
7. 短对话不机械拆主题；长对话只在存在真实独立主题时生成主题摘要。
8. 只有明显影响理解、判断或执行的原文问题才单列；简单笔误直接忽略。
9. 程序二次校验来源、断点、问答配对、编程/自然语言分类与失效媒体表述。

媒体与附件说明当前仍会写入 Markdown，但明确标记为开发检查信息，方便验证多模态识别；后续面向普通用户时可隐藏。

输出统一保存在 `results/summary` 文件夹，并使用源对话文件名区分：

- results/summary/ChatGPT_含图片_result.json：结构化结果，适合后续程序读取。
- results/summary/ChatGPT_含图片_summary.md：适合直接阅读和人工检查。

总结不同对话时会生成各自的文件，不再互相覆盖。仍可通过 --json-output 和
--markdown-output 显式指定其他保存路径。

Markdown 默认只输出精简总结，适合直接交给下一个 AI。需要提高历史细节
覆盖率时，可添加 --include-details，在同一文件末尾附加“细节记忆”。
该板块会合并原细粒度记忆与用户查询、聚合同类内容并过滤过程性信息，
最多保留 8 条关键细节；超长语言学习记录在 Markdown 中也最多展示 8 条
代表项并优先保留明确纠错。带细节模式的 Markdown、JSON 和批量报告统一
保存到 `results/summary_detailed`，普通版继续保存在 `results/summary`。JSON 始终保留
完整结构化数据。

分块结果会写入同目录的 *_progress.tmp 恢复缓存；API 中断后重跑会复用已经
完成的媒体说明和分块。成功生成最终结果后缓存自动删除。遇到 429 时程序
至少等待一个限额窗口，批处理也会在任务之间留出间隔。

对 `results/export` 中 `tests/tests.txt` 对应的全部现有结果直接批量总结，不重新抓取网页：

    uv run python -m tests.summarize_tests

批量生成带细节的版本：

    uv run python -m tests.summarize_tests --include-details

批量生成只含一个“总览”段落的极简版：

    uv run python -m tests.summarize_tests_simple

极简版复用 `results/summary` 中同 schema、同原文指纹的普通版 JSON，不重新抓取网页，
结果统一保存到 `results/summary_simple/源文件名_simple.md`。可通过 `--model` 临时指定
首选模型；批处理会先尝试该首选模型，再以 Gemini 3.6 Flash、3.5 Flash、
3.5 Flash Lite 补足回退链，配置了 SiliconFlow 密钥时再使用 Qwen 备用模型。只检查并确定性规范化现有
极简文件、不调用 API 时使用：

    uv run python -m tests.summarize_tests_simple --repair-existing

批量任务因限额或网络中断后续跑，并跳过已有同模型完整结果：

    uv run python -m tests.summarize_tests --include-details --model gemini-3.6-flash --resume

重新抓取 `tests/tests.txt` 中的全部链接，并在抓取完成后批量总结：

    uv run python -m tests.run_tests --summarize

只有显式使用 `scripts.parser --summarize`、`tests.run_tests --summarize`、
`scripts.summarize_memory`、`tests.summarize_tests` 或
`tests.summarize_tests_simple` 才会把对话和可用媒体发送给所选模型服务。
普通 `tests.run_tests` 仍只做网页抓取，不调用模型 API；
`tests.summarize_tests_simple --repair-existing` 也不调用 API。

## 目录结构

- `scripts/`：抓取、平台适配与三种总结的核心实现。
- `tests/`：单元测试、测试链接和三种批量验证入口。
- `results/export/`：当前抓取结果。
- `results/export_right/`：人工确认过的抓取黄金基线。
- `results/summary/`：普通版总结。
- `results/summary_detailed/`：详细版总结。
- `results/summary_simple/`：极简版总结。
- `工作文档/`：经验总结、非正式项目计划与临时指令。

## 当前媒体支持

- 本地图片：交给 Gemini 视觉理解。
- 本地 PDF：交给 Gemini 文档理解。
- 本地 TXT、CSV、Markdown、JSON、HTML：程序先提取文本。
- 只有文件名、下载失败或已失效的附件：明确写成“未能成功提取内容”。
- DOCX、XLSX、PPTX 当前若未被抓取到本地，不会猜测其内容。

## 测试

离线单元测试使用模拟网关，不读取任何 API 密钥，也不调用外部模型：

    python -m unittest discover -s tests -v

网页抓取完整回归（不调用模型 API）：

    uv run python -m tests.run_tests

批量总结现有测试结果（调用已配置模型）：

    uv run python -m tests.summarize_tests

批量生成详细版总结（调用已配置模型）：

    uv run python -m tests.summarize_tests --include-details

批量生成极简版总结（调用已配置模型）：

    uv run python -m tests.summarize_tests_simple

重新抓取并批量总结（调用已配置模型）：

    uv run python -m tests.run_tests --summarize

Gemini 官方资料：

- https://ai.google.dev/gemini-api/docs?hl=zh-cn
- https://ai.google.dev/gemini-api/docs/image-understanding?hl=zh-cn
- https://ai.google.dev/gemini-api/docs/document-processing?hl=zh-cn
- https://ai.google.dev/gemini-api/docs/structured-output?hl=zh-cn

SiliconFlow Chat Completions 资料：

- https://api-docs.siliconflow.cn/docs/api/chat-completions-post
