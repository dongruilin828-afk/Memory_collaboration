"""AI 平台适配器注册表。

新增平台时，在本目录创建模块并加入 PROVIDERS 即可。
"""

from . import chatgpt, deepseek, doubao


PROVIDERS = (chatgpt, deepseek, doubao)
WAIT_SELECTOR = ", ".join(provider.WAIT_SELECTOR for provider in PROVIDERS)


async def collect_virtualized_html(page):
    """按注册顺序调用需要虚拟列表采集的平台。"""
    for provider in PROVIDERS:
        collector = getattr(provider, "collect_html", None)
        if collector is None:
            continue
        html = await collector(page)
        if html is not None:
            return html
    return None


def parse_messages(soup, image_map):
    """返回 (provider, messages)；未识别平台时返回 (None, None)。"""
    for provider in PROVIDERS:
        messages = provider.parse_messages(soup, image_map)
        if messages is not None:
            return provider, messages
    return None, None
