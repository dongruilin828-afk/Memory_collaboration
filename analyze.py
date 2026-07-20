from bs4 import BeautifulSoup

with open('dump.html', 'r', encoding='utf-8') as f:
    html = f.read()

soup = BeautifulSoup(html, 'html.parser')
message_items = soup.find_all('div', class_='message-item')

parsed_messages = []
for msg in message_items:
    classes = msg.get('class', [])
    text = msg.get_text(separator='\n', strip=True)
    clean_lines = []
    for line in text.split('\n'):
        line = line.strip()
        if line not in ["复制", "重新生成", "点赞", "踩", "分享", "已采纳", "查看更多"] and len(line) > 0:
            clean_lines.append(line)
    
    clean_text = '\n'.join(clean_lines)
    if not clean_text:
        continue
    
    is_user = 'justify-end' in classes
    parsed_messages.append({'role': 'User' if is_user else 'AI', 'content': clean_text})

for item in parsed_messages:
    print(f"[{item['role']}] {item['content'][:50]}")
