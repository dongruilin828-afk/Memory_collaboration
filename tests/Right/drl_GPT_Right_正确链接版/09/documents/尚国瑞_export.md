# AI 对话记忆导出


<hr style="border: 0; border-top: 5px solid #2563EB; margin: 48px 0 24px 0;">

## 🔵 👤 用户提问

![已上传的图片](./%E5%B0%9A%E5%9B%BD%E7%91%9E_images/img_1_43875697.png)

这个是真的完全不用花一点钱吗


<hr style="border: 0; border-top: 5px solid #9333EA; margin: 48px 0 24px 0;">

## 🟣 🤖 AI 回答

基本可以说：**模型本身可以一分钱不付给 DeepReinforce 就使用，但“免费商用”≠“运行完全零成本”。**

你截图里最关键的是 **MIT License**。目前公开资料确认 Ornith 系列权重以 MIT 许可证发布，可以免费下载、修改、部署，也允许商业使用。[![](https://www.google.com/s2/favicons?domain=https://github.com&sz=128)GitHub+1](https://github.com/deepreinforce-ai/Ornith-1/blob/main/README.md?utm_source=chatgpt.com)

具体分两种情况：

* **你自己电脑本地跑 9B 量化版**：不需要购买 API、不需要订阅，软件如 Ollama 也免费。此时真正的成本基本只有你已有电脑的**电费、硬件折旧、硬盘空间**。所以如果你所谓“不花钱”是指“不额外给 AI 厂商付钱”，那确实可以做到。
* **跑 397B 那个最强版本**：模型权重仍然免费，但这么大的模型需要非常强的 GPU/服务器。普通个人电脑基本不现实；如果租云 GPU，就要付大量算力费。因此截图里“性能逼平 Claude Opus 4.8 + 免费商用”容易让人误解成“可以免费获得 Opus 级在线服务”，实际上并不是这个意思。397B 的高 benchmark 成绩对应的是巨型模型本身。[![](https://www.google.com/s2/favicons?domain=https://www.testingcatalog.com&sz=128)TestingCatalog AI News](https://www.testingcatalog.com/ornith-1-5-open-models-launch-in-397b-35b-and-9-b-sizes/?utm_source=chatgpt.com)

还有一个很值得注意的地方：**截图说 9B 量化后约 1.5GB、手机直接跑，这不代表手机跑起来就一定非常好用。** 1.5GB 通常意味着相当激进的低比特量化；除了模型文件，还要 RAM/KV cache，而且速度、上下文长度和量化后的实际能力都要考虑。公开资料确认 9B 本身确实是可本地运行的版本。[![](https://www.google.com/s2/favicons?domain=https://atomic.chat&sz=128)atomic.chat](https://atomic.chat/blog/guides/how-to-run-ornith-1-5-locally?utm_source=chatgpt.com)

所以最准确的总结是：

**Ornith：模型免费 + 商用授权免费；本地运行无需 API 费；但算力不是免费的。**

如果你只是想在你现在这台电脑上体验它，**9B 才是最值得考虑的**；截图里拿来和 Claude Opus 4.8 对标的主要是 **397B**，不要把两者混为一谈。[![](https://www.google.com/s2/favicons?domain=https://www.testingcatalog.com&sz=128)TestingCatalog AI News](https://www.testingcatalog.com/ornith-1-5-open-models-launch-in-397b-35b-and-9-b-sizes/?utm_source=chatgpt.com)


<hr style="border: 0; border-top: 5px solid #2563EB; margin: 48px 0 24px 0;">

## 🔵 👤 用户提问

9B 你觉得我那个用了四年多的轻薄本能跑起来吗


<hr style="border: 0; border-top: 5px solid #9333EA; margin: 48px 0 24px 0;">

## 🟣 🤖 AI 回答

大概率**能跑起来，但“能跑”和“跑得舒服”是两回事**。

按你之前说的那台用了四年多的轻薄本来看，关键条件是你有 **16 GB 内存**。如果 Ornith-1.5 9B 真有截图里说的那种约 **1.5 GB 的极低比特量化版**，那么从“能不能加载进内存”来说，基本没问题。即使考虑 Ollama/llama.cpp 本身、KV Cache、系统占用等，16 GB 通常也足够。

真正的问题会是**生成速度**。如果你的轻薄本没有 NVIDIA 独显，主要靠 CPU 推理，我大致会这样预期：

* 1.5 GB 左右的极低比特量化：可能 **5～15 tokens/s**
* 常见 Q4 量化，9B 通常约 5～6 GB：可能 **3～8 tokens/s**
* 如果 CPU 比较老、功耗限制严格：可能只有 **1～4 tokens/s**
* 长上下文时还会继续变慢，而且内存占用明显上升

其中 **5 tokens/s** 大概就是每秒生成 3～4 个汉字左右，聊天能用，但明显不像在线 ChatGPT 那么丝滑。10 tokens/s 左右就已经比较能接受了。

你这台机器还有一个特殊问题：你之前说 **16 GB 物理内存经常接近满载，而且还额外划了 16 GB 虚拟内存**。所以如果你一边开浏览器、VS Code、微信等，一边跑 9B，本来理论上够用的 RAM 也可能不够，Windows 开始大量换页到硬盘后，LLM 推理速度会突然恶化。**虚拟内存可以防止程序直接爆掉，但不能把 SSD 当作真正的模型推理内存使用。**

所以我对你这台电脑的判断是：

> **Ornith 9B：能跑的概率很高。**
>
> **1.5 GB 极限量化：很可能可以正常聊天。**
>
> **Q4 量化：也大概率能跑，但最好关闭一些后台程序。**
>
> **想跑 FP16：不推荐，光权重就接近 18 GB，已经超过你的物理内存。**
>
> **397B：完全不用考虑。**

而且这种东西试错成本非常低。如果它已经进 Ollama，直接下载 9B 量化版跑一次就知道了，既不会伤电脑，也不需要购买任何东西。轻薄本最多就是**CPU 满载、风扇狂转、温度和功耗升高**。

如果你把你电脑的 **CPU 型号和有没有独显**告诉我，比如 `i5-1135G7 / 16GB / Iris Xe` 这种格式，我可以进一步给你估一个比较靠谱的 **tokens/s、内存占用和适合下载哪个量化版本**。


<hr style="border: 0; border-top: 5px solid #2563EB; margin: 48px 0 24px 0;">

## 🔵 👤 用户提问

这个东西在ollama上部署了吗


<hr style="border: 0; border-top: 5px solid #9333EA; margin: 48px 0 24px 0;">

## 🟣 🤖 AI 回答

有，而且已经在 **Ollama 官方模型库**里了。

你要的 9B 版可以直接运行：

```
ollama run ornith:9b
```

Ollama 官方页面目前显示，`ornith:9b` 是 **8.95B 参数、Q4\_K\_M 量化、模型文件约 5.6 GB、256K 上下文窗口**。所以我上一条根据截图提到的“1.5 GB 量化版”并不是 Ollama 默认这个版本；**Ollama 官方默认 9B 是 5.6 GB**。[![](https://www.google.com/s2/favicons?domain=https://ollama.com&sz=128)Ollama+1](https://ollama.com/library/ornith?utm_source=chatgpt.com)

另外还有一个未量化的 BF16 版本：

```
ollama run ornith:9b-bf16
```

但这个足足 **18 GB**，你的 16 GB 轻薄本就完全不建议碰了。[![](https://www.google.com/s2/favicons?domain=https://ollama.com&sz=128)Ollama](https://ollama.com/library/ornith%3A9b-bf16?utm_source=chatgpt.com)

因此对你那台机器，我会建议直接试：

```
ollama run ornith:9b
```

首次执行会自动下载约 **5.6 GB**。下载完以后就是本地推理，**不需要 API Key，也没有按 token 收费**。[![](https://www.google.com/s2/favicons?domain=https://ollama.com&sz=128)Ollama](https://ollama.com/library/ornith%3A9b?utm_source=chatgpt.com)

顺便提醒你一点：虽然它写着 **256K context**，你这台 16 GB 机器千万别真开到 256K。模型本身 5.6 GB，再加 KV Cache 和 Windows/其他软件的内存，占用会迅速上去。对你的机器而言，先从 **4K～8K 上下文**开始会合理得多。


<hr style="border: 0; border-top: 5px solid #2563EB; margin: 48px 0 24px 0;">

## 🔵 👤 用户提问

这个开源模型是只能在本地运行吗？在云端运行是要花钱的吗


<hr style="border: 0; border-top: 5px solid #9333EA; margin: 48px 0 24px 0;">

## 🟣 🤖 AI 回答

不是，**开源模型并不等于只能本地运行**。它可以跑在你自己的电脑上，也可以跑在云端服务器上，甚至可以被别人部署成一个网页/API 服务给你用。

区别主要在“谁来提供算力”：

* **本地运行**：模型权重通常可以免费拿，但你用的是自己的 CPU/GPU，所以没有云服务账单，成本主要是电费和硬件。
* **自己租云服务器运行**：通常要花钱。你是在给 AWS、Google Cloud、阿里云、RunPod、Vast.ai 之类的平台付 GPU 租赁费，而不是给模型作者付模型费。
* **第三方已经部署好的在线服务**：可能收费，也可能免费送一部分额度。比如某个平台把 Ornith 部署好了，你直接调用它的 API，那么平台可以按 token、按小时或者按套餐收费。
* **有人免费提供云端 Demo**：也可能做到你完全不付钱，例如 Hugging Face Spaces、研究机构 Demo 等，但通常有排队、限速、每日额度或者随时关闭等限制。

所以对于这个 Ornith，可以把它理解成：

> **模型许可证允许你免费拿来用，但云 GPU 本身不是免费的。**

比如你要跑 **9B**，本地那台 16 GB 轻薄本虽然慢一些，但几乎没有额外现金成本；如果租一张云端 GPU 来跑，就会快很多，但一般按小时收费。

而 **397B** 就更典型了：权重即便完全免费，普通电脑也根本带不动，想实际使用通常需要多张高端 GPU。这样真正贵的不是“买模型”，而是**算力**。

还有一种挺适合你的方案：**不用自己部署，找提供 Ornith 免费额度的云平台/API**。这样既不折腾你那台轻薄本，也可能暂时一分钱不用花。

如果你愿意，我可以直接帮你查一下**现在有哪些网站可以在线免费试 Ornith-1.5 9B / 397B，以及各自免费额度是多少**。


<hr style="border: 0; border-top: 5px solid #2563EB; margin: 48px 0 24px 0;">

## 🔵 👤 用户提问

查一下，越多越好


<hr style="border: 0; border-top: 5px solid #9333EA; margin: 48px 0 24px 0;">

## 🟣 🤖 AI 回答

我刚按 **2026 年 8 月 21 日**的状态查了一轮。Ornith-1.5 才发布约两天，所以现在的情况很有意思：**模型权重已经到处都能拿到，但真正把 397B 做成“点开网页直接免费聊天”的服务还非常少。**

先给结论：**目前最值得你试的是 Hugging Face + Unsloth Studio；9B 有不少办法做到云端零付费体验，而 397B 想长期免费在线跑，目前基本不现实。**

| 方式/平台 | Ornith-1.5 9B | 35B-A3B | 397B | 目前能否零付费 | 备注 |
| --- | --- | --- | --- | --- | --- |
| **Hugging Face 官方模型库** | ✅ | ✅ | ✅ | ✅ 权重免费 | 三个模型均已发布 |
| **Unsloth Studio · HF Space** | ✅ | ✅ | ✅ 有入口 | 🟢 可尝试免费 | **我最建议先试** |
| **Google Colab** | ✅ | ⚠️ | ❌基本不行 | 🟢 有免费层 | 适合 9B 量化 |
| **Kaggle Notebooks** | ✅ | ⚠️ | ❌基本不行 | 🟢 有免费 GPU | 适合 9B |
| **Ollama** | ✅ | ✅ | ✅技术上 | ✅软件免费 | 算你自己的硬件，不是云端 |
| **llama.cpp** | ✅ | ✅ | ✅ | ✅软件免费 | 同上 |
| **LM Studio** | ✅ | ✅ | ⚠️ | ✅软件免费 | 本地 |
| **Docker Model Runner** | ✅ | ✅ | ✅ | ✅软件免费 | 算力自己承担 |
| **vLLM** | ✅ | ✅ | ✅ | ✅软件免费 | 自己提供服务器 |
| **SGLang** | ✅ | ✅ | ✅ | ✅软件免费 | 自己提供服务器 |
| **OpenRouter** | ❌目前没查到 1.5 | ❌ | ❌ | — | 很多人也在等 |
| **Together AI** | ❌目前没查到 | ❌ | ❌ | — | 可能后续上线 |
| **Fireworks AI** | ❌目前没查到 | ❌ | ❌ | — | 同上 |
| **DeepInfra** | ❌目前没查到 | ❌ | ❌ | — | 同上 |
| **Groq** | ❌目前没查到 | ❌ | ❌ | — | 目前没有证据 |
| **Cerebras** | ❌目前没查到 | ❌ | ❌ | — | 目前没有证据 |
| **Novita AI** | ❌目前没查到 | ❌ | ❌ | — | 目前没有证据 |
| **Replicate** | ❌目前没查到 | ❌ | ❌ | — | 可能很快有人部署 |
| **Featherless AI** | ⚠️已有 Ornith-1.0 | ⚠️ | ⚠️ | 有套餐/额度 | **1.5 暂未确认** |
| **SiliconFlow** | ❌目前没查到 | ❌ | ❌ | — | 目前没有证据 |
| **Baseten** | ❌目前没查到 | ❌ | ❌ | — | 可自己部署，但不是免费推理 |

这里的 ❌ 是\*\*“我目前没有查到 Ornith-1.5 已经作为现成托管模型上线”\*\*，而不是说这些平台技术上不能部署它。因为模型才刚发布，未来几天名单很可能迅速变化。Ornith-1.5 的 9B、35B、397B 以及 GGUF 版本目前都已经公开。[![](https://www.google.com/s2/favicons?domain=https://www.reddit.com&sz=128)Reddit+1](https://www.reddit.com/r/LocalLLaMA/comments/1vsn2xw/we_have_q38_35b_at_home_3x_new_ornith_15_released/?utm_source=chatgpt.com)

### ① 现在最值得你点开的：Unsloth Studio

这个是目前我找到的最接近你所说：

> **“我不要下载模型，也不要用自己的电脑算，打开网页直接试。”**

Ornith-1.5-397B 的 Hugging Face 页面已经明确给出了 **Hugging Face Spaces 上的 Unsloth Studio** 使用方式，而且写的是 **“No setup required”**：进入 Space 后搜索

`ornith-ai/Ornith-1.5-397B-GGUF`

即可尝试加载。[![](https://www.google.com/s2/favicons?domain=https://praworodziny.info&sz=128)Pravorodziny](https://praworodziny.info/ornith-ai/Ornith-1.5-397B-GGUF)

[打开 Unsloth Studio 网页版](https://huggingface.co/spaces/unsloth/studio?utm_source=chatgpt.com)

对于 9B，你搜索：

```
ornith-ai/Ornith-1.5-9B-GGUF
```

对于 35B：

```
ornith-ai/Ornith-1.5-35B-A3B-GGUF
```

397B：

```
ornith-ai/Ornith-1.5-397B-GGUF
```

不过这里我要特别区分：

**“Space 提供了这个模型的入口” ≠ “Hugging Face 会免费给你几百 GB GPU 跑完整 397B”。**

397B 模型即使量化以后仍然巨大。所以如果 Space 最终提示资源不足、排队或需要升级 GPU，并不奇怪。Hugging Face 的模型页面确实已经明确列出了这一使用方法，但我不会据此保证 397B 一定能永久免费跑。[![](https://www.google.com/s2/favicons?domain=https://praworodziny.info&sz=128)Pravorodziny](https://praworodziny.info/ornith-ai/Ornith-1.5-397B-GGUF)

---

## ② Hugging Face：模型本身全部免费

官方的 1.5 系列已经包括：

```
Ornith-1.5-9B
Ornith-1.5-35B-A3B
Ornith-1.5-397B
```

以及：

```
Ornith-1.5-9B-GGUF
Ornith-1.5-35B-A3B-GGUF
Ornith-1.5-397B-GGUF
```

而且许可证为 **MIT**。[![](https://www.google.com/s2/favicons?domain=https://www.reddit.com&sz=128)Reddit+1](https://www.reddit.com/r/LocalLLaMA/comments/1vsn2xw/we_have_q38_35b_at_home_3x_new_ornith_15_released/?utm_source=chatgpt.com)

Ornith-1.5-397B 官方 Hugging Face 页面

[Ornith-1.5-9B 官方 Hugging Face 页面](https://huggingface.co/ornith-ai/Ornith-1.5-9B?utm_source=chatgpt.com)

也就是说：

**下载权重：0 元。  
商业使用授权：0 元。  
Hugging Face 存模型：0 元。  
真正执行推理所需 GPU：不一定 0 元。**

这几个一定不要混在一起。

---

## ③ Google Colab：9B 很适合薅免费 GPU

Hugging Face 的 Ornith-1.5 页面已经直接提供了 **Google Colab** Notebook 入口。397B GGUF 页面也明确列出了 Colab。[![](https://www.google.com/s2/favicons?domain=https://praworodziny.info&sz=128)Pravorodziny](https://praworodziny.info/ornith-ai/Ornith-1.5-397B-GGUF)

但现实上：

**9B Q4：非常适合。**

大约 5～6 GB 权重，免费的 T4 一类 GPU 如果分得到，完全有机会跑。

**35B-A3B：有可能折腾出来，但是比较紧。**

虽然它每 token 只激活约 3B 参数，但**35B 权重仍然要装进内存**。低比特量化后大概也是十几到二十 GB 级别，并不因为只激活 3B 就只需要 3B 的显存。

**397B：Colab Free 基本可以直接排除。**

397B 的原始 BF16 权重是数百 GB 级别。上一代 397B 的 BF16 Hugging Face 仓库就达到约 **794 GB**，官方标准部署甚至给出了 **8×80GB GPU** 的服务器配置示例。[![](https://www.google.com/s2/favicons?domain=https://huggingface.co&sz=128)Hugging Face+1](https://huggingface.co/unsloth/Ornith-1.0-397B/tree/main?utm_source=chatgpt.com)

所以免费 Colab 根本不是这个量级。

---

## ④ Kaggle：也是很不错的免费方案

Hugging Face 的 Ornith-1.5-397B-GGUF 页面也已经直接提供了 **Kaggle Notebook** 集成入口。[![](https://www.google.com/s2/favicons?domain=https://praworodziny.info&sz=128)Pravorodziny](https://praworodziny.info/ornith-ai/Ornith-1.5-397B-GGUF)

Kaggle 最大优势也是：

> 你不需要烧自己轻薄本的 CPU。

对于你而言，我甚至会把：

**Kaggle / Colab 免费 GPU + Ornith-1.5-9B Q4**

放在本地轻薄本运行之前。

同一个 9B 模型，你本地 CPU 可能只有几 token/s；云端免费 T4/P100 一类 GPU 的体验可能舒服很多。

不过 Kaggle 免费 GPU 有**每周额度和资源供应限制**，并不能视为永远在线的免费 API。

---

# ⑤ OpenRouter：现在反而还没有

这个我特意查了，因为它其实是**最理想的形式**：

```
你 → OpenRouter API → Ornith-1.5-397B
```

这样你什么硬件都不用管。

但截至现在，我**没有查到 Ornith-1.5 已经正式出现在 OpenRouter 模型列表中的可靠证据**。

而且 Ornith 发布后的 LocalLLaMA 讨论里已经有人直接说：

> “I'll try it if it comes out on openrouter”

也就是说发布当天社区用户同样还在等 OpenRouter 上线。[![](https://www.google.com/s2/favicons?domain=https://www.reddit.com&sz=128)Reddit](https://www.reddit.com/r/LocalLLaMA/comments/1vsnllv/ornith_15_9b_dense_and_35b397b_moes/?utm_source=chatgpt.com)

这其实很正常——**Ornith-1.5 才发布两天。**

我认为 OpenRouter 是接下来非常值得盯的一个。

---

# ⑥ Featherless：非常值得关注

这个平台有点特殊。

我查到了 Featherless 已经托管过：

**Ornith-1.0-9B**

而且它的模型目录里还有各种 Ornith-1.0 衍生版。[![](https://www.google.com/s2/favicons?domain=https://featherless.ai&sz=128)Featherless+1](https://featherless.ai/model-releases/2026-06-21?utm_source=chatgpt.com)

也就是说 Featherless 的基础设施**明确支持 Ornith/Qwen 这一架构**。

但是：

> **目前我没有找到可信页面证明 Ornith-1.5 已正式上线 Featherless。**

因为 1.5 才刚出来，我会把 Featherless 归为**很可能比较快跟进的候选平台**，而不是现在就告诉你“已经有了”。

---

# ⑦ 其他大模型 API 平台：现在基本都在等

我还专门检索了：

**Together AI、Fireworks AI、DeepInfra、Groq、Cerebras、Novita AI、Replicate、SiliconFlow、Baseten、Chutes**

目前没有找到足够可靠的 **Ornith-1.5 已上线**证据。

这里面尤其值得以后看的几个是：

**OpenRouter → 第一优先级**

因为它能聚合很多供应商。一旦有人愿意托管 397B，很容易从 OpenRouter 暴露出来。

**DeepInfra / Together / Fireworks → 第二梯队**

它们本来就是专门托管开放权重模型的。

**Replicate → 很可能出现社区部署**

即使官方不部署，别人也可以包装成 endpoint。

**Featherless → 很值得盯**

因为它已经有 Ornith-1.0。

---

# ⑧ 有一个容易被忽略的选择：自己用“免费云主机”

还有一类严格来说不是“在线模型网站”，但确实可以做到**你一分钱不交**：

```
免费 Colab/Kaggle GPU
        ↓
下载 Ornith-1.5-9B GGUF
        ↓
llama.cpp / Ollama / Transformers
        ↓
开 Gradio / OpenAI-compatible API
        ↓
浏览器聊天
```

对你来说，这其实可能是**现阶段最实用的免费云端 Ornith-1.5 方案**。

模型没有占你电脑内存，推理不烧你 CPU，而且不需要买 API credits。

---

# 为什么我现在不太看好“免费 397B”

看一下数量级就明白了。

397B：

**3970 亿参数。**

即便按非常激进的：

**2 bit ≈ 100 GB 纯权重**

再考虑量化元数据、KV Cache、运行时开销，依然是服务器级别。

Q4 则粗略已经：

**≈ 200+ GB**

所以某家公司要是让你：

> 注册账号，不绑卡，无限制跑 Ornith-1.5-397B

那么每次你聊天，实际上都是**他们在替你付昂贵的服务器 GPU/CPU 成本**。

偶尔搞推广免费额度完全可能，但**长期永久免费无限量**基本不符合经济规律。

反过来，9B 就完全不同：

```
9B Q4
≈ 5～6 GB
```

一张便宜 GPU 可以同时服务很多用户，所以各种免费 Demo 非常现实。社区做出的 9B Q4 类量化目前就在大约 **5.6 GB** 左右。[![](https://www.google.com/s2/favicons?domain=https://www.reddit.com&sz=128)Reddit](https://www.reddit.com/r/LocalLLaMA/comments/1vsx94f/we_quantized_the_new_ornith_15_9b_and_35ba3b/?utm_source=chatgpt.com)

---

## 所以如果你的核心目标是“我现在一分钱都不想付”

我会按这个顺序：

**① 先试 Unsloth Studio 的 Hugging Face Space**

最快，甚至不用安装。

**② 不行就用 Google Colab 跑 9B Q4**

不烧你自己的轻薄本。

**③ Kaggle 免费 GPU 跑 9B**

也很适合。

**④ Ollama 本地 `ornith:9b`**

完全不依赖第三方免费额度，只是用你的 CPU。

**⑤ 等 OpenRouter / Featherless / DeepInfra 上 Ornith-1.5**

尤其是 **397B**。如果你真正想体验截图里那个“对标 Claude Opus 4.8”的版本，**你要等的是 397B 的廉价/免费托管 API，而不是 9B**。公开讨论中也明确纠正过这一点：对标 Opus 的说法指向 397B，而非 9B。[![](https://www.google.com/s2/favicons?domain=https://www.reddit.com&sz=128)Reddit](https://www.reddit.com/r/accelerate/comments/1vst1q5/ornith_15_reports_a_significant_step_towards_full/?utm_source=chatgpt.com)

而且值得注意：现在网上对 Ornith-1.5 benchmark 的实际泛化能力已经有一些质疑和实测分歧，所以即使找到 397B 免费入口，我也建议你把它当成“亲自实测”的机会，不要仅凭那张 benchmark 图就认为它实际体验一定等同 Opus。[![](https://www.google.com/s2/favicons?domain=https://www.reddit.com&sz=128)Reddit+1](https://www.reddit.com/r/Qwen_AI/comments/1vtlvys/ornith_15_35b_first_impression/?utm_source=chatgpt.com)

这个模型刚发布，**接下来几天各 API 平台上线情况很可能变化很快**。我可以帮你持续盯着 **OpenRouter、DeepInfra、Together、Fireworks、Featherless 等平台，只要 Ornith-1.5 397B 出现免费/低价在线入口就提醒你。**

盯 Ornith 397B 免费入口


<hr style="border: 0; border-top: 5px solid #2563EB; margin: 48px 0 24px 0;">

## 🔵 👤 用户提问

![已上传的图片](./%E5%B0%9A%E5%9B%BD%E7%91%9E_images/img_2_dd42473a.png)

我该在哪里开始试用？


<hr style="border: 0; border-top: 5px solid #9333EA; margin: 48px 0 24px 0;">

## 🟣 🤖 AI 回答

你现在这个页面本身**不是直接聊天界面**，所以不是往下找输入框。

最快的试用方法是：

1. 点你截图里黑色的 **`Use this model ▼`**
2. 看里面有没有 **Hugging Face Spaces / Unsloth Studio** 一类入口。
3. 如果没有，直接打开 **Unsloth Studio 的 Hugging Face Space**，然后搜索：  
   `ornith-ai/Ornith-1.5-9B-GGUF`
4. 找到后就可以尝试加载并聊天。Ornith 官方 GGUF 页面目前明确写了这种方式是 **“No setup required”**。[![](https://www.google.com/s2/favicons?domain=https://huggingface.co&sz=128)Hugging Face](https://huggingface.co/ornith-ai/Ornith-1.5-9B-GGUF/tree/main?utm_source=chatgpt.com)

你也可以直接进这里：

打开 Unsloth Studio

注意要搜的是 **`Ornith-1.5-9B-GGUF`**，不是你截图里这个 BF16 的 `Ornith-1.5-9B`。你截图这个原版是 **BF16**，仅权重就大约 18GB，更适合服务器；GGUF 才有 Q4 等量化版本，更适合试用和本地部署。[![](https://www.google.com/s2/favicons?domain=https://huggingface.co&sz=128)Hugging Face+1](https://huggingface.co/ornith-ai/Ornith-1.5-9B?utm_source=chatgpt.com)

如果你愿意，你下一步点开 **`Use this model`** 后再截个图给我，我可以直接告诉你**具体点哪一项**。


<hr style="border: 0; border-top: 5px solid #2563EB; margin: 48px 0 24px 0;">

## 🔵 👤 用户提问

![已上传的图片](./%E5%B0%9A%E5%9B%BD%E7%91%9E_images/img_3_4b13f8e5.png)

直接点你那个链接是404


<hr style="border: 0; border-top: 5px solid #9333EA; margin: 48px 0 24px 0;">

## 🟣 🤖 AI 回答

对，你这个截图已经把情况说明得很清楚了：**我刚才给你的 Unsloth Studio 链接目前确实已经失效/不可直接用了，是我前面那条信息不够新。**

你截图最下面这一句才是关键：

> **This model isn't deployed by any Inference Provider.**

也就是说，**Hugging Face 目前没有任何云端推理提供商替 Ornith-1.5-9B 托管好现成接口**。所以你在这个页面上没法像 ChatGPT 一样直接点进去聊天。

你现在实际可用的免费路线主要有两个：

1. **Google Colab**  
   你截图里 `Use this model` → `Google Colab` 可以直接点。它会给你一个 Notebook，然后用 Google 提供的免费算力运行模型。对 9B 来说，这是目前比较现实的“云端、尽量不花钱”方案。
2. **Kaggle**  
   同一个菜单里的 `Kaggle` 也可以。思路一样：用 Kaggle 的免费 GPU 配额，而不是你自己电脑跑。

至于我之前提到的 **Unsloth Studio Hugging Face Space**，搜索结果里一些模型卡仍然写着 `huggingface.co/spaces/unsloth/studio`，但 Unsloth 当前的 Spaces 页面实际上只显示一个正在运行的 Space，而且原来的 `studio` 地址已经不能正常作为网页版 Studio 使用。[![](https://www.google.com/s2/favicons?domain=https://huggingface.co&sz=128)Hugging Face+1](https://huggingface.co/unsloth/spaces?utm_source=chatgpt.com)

Unsloth 现在更明确支持的是**安装到本机**：

```
irm https://unsloth.ai/install.ps1 | iex
```

然后：

```
unsloth studio -H 0.0.0.0 -p 8888
```

再在浏览器访问 `localhost:8888`。但这就又变成本地运行了，不符合你刚才想找的“别人提供云算力免费试”的目标。Unsloth 当前模型卡也是这样介绍本地 Studio 的。[![](https://www.google.com/s2/favicons?domain=https://huggingface.co&sz=128)Hugging Face](https://huggingface.co/unsloth/Qwen3-1.7B?utm_source=chatgpt.com)

所以你现在这张截图里，**我建议你直接点 `Google Colab`**。这条最合适。

如果你点进去后把 Colab 页面截给我，我可以继续一步一步带你把 **Ornith-1.5-9B 在免费 GPU 上真正跑起来**，包括该选哪个量化版本、怎么避免 16GB 显存/内存爆掉。


<hr style="border: 0; border-top: 5px solid #2563EB; margin: 48px 0 24px 0;">

## 🔵 👤 用户提问

![已上传的图片](./%E5%B0%9A%E5%9B%BD%E7%91%9E_images/img_4_20f0c74b.png)


<hr style="border: 0; border-top: 5px solid #9333EA; margin: 48px 0 24px 0;">

## 🟣 🤖 AI 回答

你已经进到正确的 Colab Notebook 了，而且右上角显示 **T4**，说明你现在分到的是 NVIDIA T4 GPU，这对 9B 模型是能尝试的。

你现在先按这个顺序做：

1. 点最上面第一格代码左侧的 **▶**，先执行 `pip install -U transformers ...`
2. 等它跑完，出现绿色勾/不再转圈。
3. 再往下执行模型加载那一格。
4. 如果它直接加载 BF16 原版，很可能会因为显存不够而 OOM，因为 T4 通常只有 16GB 显存，而 9B BF16 权重本身就接近 18GB。
5. 所以如果加载时报 `CUDA out of memory`，不要反复重试，直接换 **4-bit 量化**方案更合适。

从你这个 Notebook 看，它是 Hugging Face 自动生成的，默认很可能是类似：

```
from transformers import pipeline

pipe = pipeline(
    "text-generation",
    model="ornith-ai/Ornith-1.5-9B",
    device_map="auto",
)
```

这种默认写法对 T4 不一定稳，因为会优先加载原始权重。

更适合你这个 T4 的方向是 **bitsandbytes 4-bit**，这样显存占用通常能压到大约 5～7GB 量级，再加 KV cache 和运行时开销，16GB T4 就舒服得多。

你可以先执行第一格安装。**然后把下一格完整代码截给我**，我可以直接告诉你这一格要不要改，以及改成什么才能让 T4 稳定跑起来。


<hr style="border: 0; border-top: 5px solid #2563EB; margin: 48px 0 24px 0;">

## 🔵 👤 用户提问

这会不会占用我的设备空间，性能？


<hr style="border: 0; border-top: 5px solid #9333EA; margin: 48px 0 24px 0;">

## 🟣 🤖 AI 回答

基本不会占你手机/电脑的性能，因为你现在是在 **Google Colab 云端**跑。

你这张图右上角的 **T4** 是 Google 分给你的云端 NVIDIA T4，不是你自己设备的 GPU。所以模型下载、显存占用、推理计算，主要都发生在 Google 的服务器上。

对你本地设备来说，影响主要只有这几个：

* 浏览器本身会占一点内存和 CPU，和普通开几个网页差不多。
* 会消耗网络流量，因为你要传提示词、接收模型输出，Notebook 也会加载页面内容。
* 模型文件一般下载到 Colab 临时运行环境里，**不会直接占你手机或电脑硬盘的 5～20GB**。
* 如果你主动把模型保存到 Google Drive，那会占你的 **Google Drive 云端空间**，仍然不是本机硬盘。

所以你现在可以把它理解成：

> 你的手机只是“遥控器 + 显示器”，真正干重活的是 Google 的 T4 服务器。

甚至模型推理时，你手机的温度和耗电通常也只会是浏览网页级别，不会像本地跑 9B 那样 CPU 满载、发热、风扇狂转。

不过 Colab 有一个特点：**运行环境是临时的**。会话断开或者运行时被回收后，你下载进去的模型通常也会消失，下次可能需要重新下载。这也是为什么它不占你本机空间。

