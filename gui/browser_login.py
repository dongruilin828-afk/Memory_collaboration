"""Platform identity and explicit fresh login in the app-owned browser only."""
from urllib.parse import urlparse

from scripts.providers import provider_for_url


_DOMAINS = {
    'chatgpt': ('chatgpt.com', 'openai.com', 'auth0.com'),
    'deepseek': ('deepseek.com',),
    'doubao': ('doubao.com', 'douyin.com', 'bytedance.com', 'bytedance.net'),
    'gemini': ('google.com', 'google.cn', 'google.com.hk', 'googleusercontent.com', 'gemini.google'),
    'kimi': ('kimi.com', 'moonshot.cn', 'moonshot.ai'),
    'qianwen': ('qianwen.com', 'qianwen.my.cn', 'aliyun.com', 'alibaba.com', 'taobao.com'),
    'grok': ('grok.com', 'x.ai', 'x.com', 'twitter.com'),
}


def platform_login_key(url):
    provider = provider_for_url(url)
    if provider is None:
        return urlparse(url).netloc.lower()
    key = provider.__name__.rsplit('.', 1)[-1]
    return 'chatgpt' if key == 'codex' else key


async def reset_platform_login(context, page, url):
    """Clear target/SSO cookies and origin storage, preserving other AI sessions."""
    key = platform_login_key(url)
    if key not in _DOMAINS:
        raise ValueError('不支持的登录平台。')
    domains = _DOMAINS[key]

    def belongs(host):
        host = (host or '').lower().lstrip('.')
        return any(host == domain or host.endswith('.' + domain) for domain in domains)

    state = await context.storage_state(indexed_db=True)
    origins = {row['origin'] for row in state.get('origins', [])
               if belongs(urlparse(row['origin']).hostname)}
    origins.add('https://' + urlparse(url).netloc)
    for tab in context.pages:
        current = urlparse(tab.url)
        if belongs(current.hostname):
            origins.add(f'{current.scheme}://{current.netloc}')
            # Old loaded pages must not restore tokens after storage is cleared.
            await tab.goto('about:blank', wait_until='commit', timeout=10000)
    session = await context.new_cdp_session(page)
    try:
        for origin in origins:
            await session.send('Storage.clearDataForOrigin', {'origin': origin, 'storageTypes': 'all'})
        for domain in {cookie['domain'] for cookie in state.get('cookies', []) if belongs(cookie['domain'])}:
            await context.clear_cookies(domain=domain)
    finally:
        await session.detach()
