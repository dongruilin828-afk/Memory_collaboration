import tkinter as tk
from tkinter import ttk, filedialog

from hash_utils import calculate_hash, calculate_file_hash


# =========================
# 哈希计算
# =========================

def generate_hash():
    # 获取用户输入的多行字符串
    text = input_text.get("1.0", "end-1c")

    # 获取当前算法
    selected_algorithm = algorithm_var.get()

    # GUI 名称 → 后端名称
    algorithm_map = {
        "MD5": "md5",
        "SHA-1": "sha1",
        "SHA-256": "sha256",
        "SHA-512": "sha512",
    }

    algorithm = algorithm_map[selected_algorithm]

    # 计算哈希值
    result = calculate_hash(text, algorithm)

    # 临时解除输出框只读
    output_text.config(state="normal")

    # 清除旧结果
    output_text.delete("1.0", tk.END)

    # 写入新结果
    output_text.insert("1.0", result)

    # 恢复只读
    output_text.config(state="disabled")

    # 修改结果标题
    output_label.config(
        text=f"{selected_algorithm} 哈希值："
    )

    # 更新状态栏
    update_status()


# =========================
# 复制结果
# =========================

def copy_result():
    result = output_text.get("1.0", "end-1c")

    if not result:
        return

    root.clipboard_clear()

    root.clipboard_append(result)

    root.update()


# =========================
# 清空
# =========================

def clear_all():
    # 清空输入
    input_text.delete("1.0", tk.END)

    # 清空输出
    output_text.config(state="normal")

    output_text.delete("1.0", tk.END)

    output_text.config(state="disabled")

    # 恢复默认算法
    algorithm_var.set("SHA-256")

    expected_hash_var.set("")

    verify_result_var.set(
        "校验结果：尚未校验"
    )

    # 恢复默认结果标题
    output_label.config(
        text="SHA-256 哈希值："
    )

    # 焦点回到输入框
    input_text.focus_set()

    # 更新状态栏
    update_status()


# =========================
# 更新状态栏
# =========================

def update_status():
    # 当前输入内容
    text = input_text.get("1.0", "end-1c")

    # 字符数
    char_count = len(text)

    # UTF-8 字节数
    byte_count = len(text.encode("utf-8"))

    # 当前算法
    selected_algorithm = algorithm_var.get()

    # 当前输出内容
    result = output_text.get("1.0", "end-1c")

    # 输出长度
    output_length = len(result)

    # 更新状态文字
    status_var.set(
        f"输入：{char_count} 字符 / {byte_count} 字节"
        f"   |   算法：{selected_algorithm}"
        f"   |   输出：{output_length} 字符"
    )


# =========================
# 输入框修改事件
# =========================

def on_input_modified(event=None):
    if input_text.edit_modified():

        update_status()

        # 必须把修改标志重新设回 False
        input_text.edit_modified(False)

def select_file():
    file_path = filedialog.askopenfilename(
        title="选择要计算哈希的文件"
    )

    # 用户可能打开窗口以后又点了“取消”
    if not file_path:
        return

    # 保存选择的文件路径
    selected_file_path.set(file_path)


def generate_file_hash():
    # 获取文件路径
    file_path = selected_file_path.get()

    # 如果还没有选择文件
    if file_path == "尚未选择文件":
        return

    # 当前选择的算法
    selected_algorithm = algorithm_var.get()

    algorithm_map = {
        "MD5": "md5",
        "SHA-1": "sha1",
        "SHA-256": "sha256",
        "SHA-512": "sha512",
    }

    algorithm = algorithm_map[selected_algorithm]

    # 计算文件哈希
    result = calculate_file_hash(
        file_path,
        algorithm
    )

    # 临时解除输出框只读
    output_text.config(state="normal")

    # 清空旧结果
    output_text.delete("1.0", tk.END)

    # 写入文件哈希
    output_text.insert("1.0", result)

    # 恢复只读
    output_text.config(state="disabled")

    # 更新标题
    output_label.config(
        text=f"{selected_algorithm} 文件哈希值："
    )

    # 更新状态栏
    update_status()


def verify_file_hash():
    # 获取当前选择的文件路径
    file_path = selected_file_path.get()

    # 如果还没有选择文件
    if file_path == "尚未选择文件":
        verify_result_var.set("请先选择一个文件")
        return

    # 获取用户输入的预期哈希值
    expected_hash = expected_hash_var.get().strip()

    # 如果没有输入预期哈希
    if not expected_hash:
        verify_result_var.set("请输入预期哈希值")
        return

    # 获取当前选择的算法
    selected_algorithm = algorithm_var.get()

    algorithm_map = {
        "MD5": "md5",
        "SHA-1": "sha1",
        "SHA-256": "sha256",
        "SHA-512": "sha512",
    }

    algorithm = algorithm_map[selected_algorithm]

    # 计算文件真实哈希值
    actual_hash = calculate_file_hash(
        file_path,
        algorithm
    )

    # 同时把真实哈希显示到输出框
    output_text.config(state="normal")

    output_text.delete("1.0", tk.END)

    output_text.insert("1.0", actual_hash)

    output_text.config(state="disabled")

    output_label.config(
        text=f"{selected_algorithm} 文件哈希值："
    )

    # 比较两个哈希值
    if actual_hash.lower() == expected_hash.lower():
        verify_result_var.set(
            "✓ 校验通过：哈希值一致"
        )
    else:
        verify_result_var.set(
            "✗ 校验失败：哈希值不一致"
        )

    update_status()


# =========================
# 算法选择事件
# =========================

def on_algorithm_changed(event=None):
    update_status()


# =========================
# 创建主窗口
# =========================

root = tk.Tk()
selected_file_path = tk.StringVar(
    value="尚未选择文件"
)
expected_hash_var = tk.StringVar()

verify_result_var = tk.StringVar(
    value="校验结果：尚未校验"
)

root.title("Hash Tool")

root.geometry("800x820")


# =========================
# 输入区域
# =========================

input_label = ttk.Label(
    root,
    text="请输入字符串："
)

input_label.pack(
    pady=(25, 5)
)


input_frame = ttk.Frame(root)

input_frame.pack(
    padx=40,
    pady=5,
    fill="both"
)


input_text = tk.Text(
    input_frame,
    height=8,
    wrap="word"
)

input_text.pack(
    side=tk.LEFT,
    fill="both",
    expand=True
)


input_scrollbar = ttk.Scrollbar(
    input_frame,
    orient="vertical",
    command=input_text.yview
)

input_scrollbar.pack(
    side=tk.RIGHT,
    fill="y"
)


input_text.config(
    yscrollcommand=input_scrollbar.set
)


# =========================
# 文件选择区域
# =========================

file_label = ttk.Label(
    root,
    text="或选择一个文件："
)

file_label.pack(
    pady=(15, 5)
)


file_frame = ttk.Frame(root)

file_frame.pack(
    padx=40,
    pady=5,
    fill="x"
)


file_path_label = ttk.Label(
    file_frame,
    textvariable=selected_file_path,
    anchor="w"
)

file_path_label.pack(
    side=tk.LEFT,
    fill="x",
    expand=True
)


select_file_button = ttk.Button(
    file_frame,
    text="选择文件",
    command=select_file
)

select_file_button.pack(
    side=tk.RIGHT,
    padx=(10, 0)
)


# =========================
# 算法选择区域
# =========================

algorithm_label = ttk.Label(
    root,
    text="请选择哈希算法："
)

algorithm_label.pack(
    pady=(20, 5)
)


# 保存当前算法
algorithm_var = tk.StringVar(
    value="SHA-256"
)


algorithm_box = ttk.Combobox(
    root,
    textvariable=algorithm_var,
    values=[
        "MD5",
        "SHA-1",
        "SHA-256",
        "SHA-512",
    ],
    state="readonly",
    width=20,
)

algorithm_box.pack(
    pady=5
)


# =========================
# 计算按钮
# =========================

generate_button = ttk.Button(
    root,
    text="计算文本哈希",
    command=generate_hash,
)

generate_file_button = ttk.Button(
    root,
    text="计算文件哈希",
    command=generate_file_hash,
)

generate_file_button.pack(
    pady=(0, 20)
)

generate_button.pack(
    pady=(20, 10)
)


# =========================
# 输出区域
# =========================

output_label = ttk.Label(
    root,
    text="SHA-256 哈希值："
)

output_label.pack(
    pady=5
)


output_frame = ttk.Frame(root)

output_frame.pack(
    padx=40,
    pady=5,
    fill="both"
)


output_text = tk.Text(
    output_frame,
    height=4,
    wrap="char",
    state="disabled"
)

output_text.pack(
    side=tk.LEFT,
    fill="both",
    expand=True
)


output_scrollbar = ttk.Scrollbar(
    output_frame,
    orient="vertical",
    command=output_text.yview
)

output_scrollbar.pack(
    side=tk.RIGHT,
    fill="y"
)


output_text.config(
    yscrollcommand=output_scrollbar.set
)

# =========================
# 哈希校验区域
# =========================

verify_label = ttk.Label(
    root,
    text="官方 / 预期哈希值："
)

verify_label.pack(
    pady=(15, 5)
)


expected_hash_entry = ttk.Entry(
    root,
    textvariable=expected_hash_var,
    width=90
)

expected_hash_entry.pack(
    padx=40,
    pady=5,
    fill="x"
)


verify_button = ttk.Button(
    root,
    text="校验文件",
    command=verify_file_hash
)

verify_button.pack(
    pady=10
)


verify_result_label = ttk.Label(
    root,
    textvariable=verify_result_var
)

verify_result_label.pack(
    pady=(0, 10)
)


# =========================
# 操作按钮区域
# =========================

button_frame = ttk.Frame(root)

button_frame.pack(
    pady=20
)


copy_button = ttk.Button(
    button_frame,
    text="复制结果",
    command=copy_result,
)

copy_button.pack(
    side=tk.LEFT,
    padx=10
)


clear_button = ttk.Button(
    button_frame,
    text="清空",
    command=clear_all,
)

clear_button.pack(
    side=tk.LEFT,
    padx=10
)


# =========================
# 状态栏
# =========================

status_var = tk.StringVar()


status_label = ttk.Label(
    root,
    textvariable=status_var,
    anchor="w"
)

status_label.pack(
    fill="x",
    padx=40,
    pady=(5, 15)
)


# =========================
# 绑定事件
# =========================

input_text.bind(
    "<<Modified>>",
    on_input_modified
)

algorithm_box.bind(
    "<<ComboboxSelected>>",
    on_algorithm_changed
)


# 清除 Text 创建时可能存在的修改标记
input_text.edit_modified(False)


# 初始化状态栏
update_status()


# =========================
# 启动程序
# =========================

root.mainloop()