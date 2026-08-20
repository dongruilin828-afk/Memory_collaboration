"""对话的终端展示与 Markdown 导出。"""

from rich.panel import Panel


def display_and_export(
    parsed_messages,
    image_map,
    export_filename,
    console
):
    """展示并导出统一消息结构，成功时返回 True。"""
    console.print(
        f"[dim]共提取到 {len(parsed_messages)} 条对话交互：[/dim]\n"
    )

    for item in parsed_messages:
        if item['role'] == 'User':
            console.print(Panel(
                item['content'],
                title="[bold blue]👤 用户 / 提问[/bold blue]",
                border_style="blue",
                title_align="right"
            ))
        else:
            console.print(Panel(
                item['content'],
                title="[bold magenta]🤖 AI / 回答[/bold magenta]",
                border_style="magenta",
                title_align="left"
            ))

    try:
        with open(export_filename, "w", encoding="utf-8") as file:
            file.write("# AI 对话记忆导出\n\n")
            for item in parsed_messages:
                if item['role'] == 'User':
                    file.write(
                        '\n<hr style="border: 0; border-top: 5px solid #2563EB; '
                        'margin: 48px 0 24px 0;">\n\n'
                        f"## 🔵 👤 用户提问\n\n{item['content']}\n\n"
                    )
                else:
                    file.write(
                        '\n<hr style="border: 0; border-top: 5px solid #9333EA; '
                        'margin: 48px 0 24px 0;">\n\n'
                        f"## 🟣 🤖 AI 回答\n\n{item['content']}\n\n"
                    )
        console.print(
            f"\n[bold green]🎉 对话记录已成功导出为 Markdown 文件: "
            f"{export_filename}[/bold green]"
        )
        if image_map:
            console.print(
                f"[dim]已成功下载并关联 {len(image_map)} 张图片到 "
                f"./images/ 目录。[/dim]"
            )
        return True
    except Exception as e:
        console.print(
            f"\n[bold red]保存 Markdown 文件时出错:[/bold red] {e}"
        )
        return False
