import re
import subprocess
import time
from pathlib import Path


# ============================================================
# 路径配置
# ============================================================

BASE_DIR = Path(r"D:\大学\复旦大学\课程\大二上\强国之路")

TESTS_FILE = BASE_DIR / "tests.txt"

RESULTS_DIR = BASE_DIR / "results"

EXPORT_FILE = BASE_DIR / "AI_memory_export.md"


# ============================================================
# 读取 tests.txt
# ============================================================

def read_tests():

    content = TESTS_FILE.read_text(
        encoding="utf-8-sig"
    )

    tests = []

    current_platform = None

    pending_title = None

    # 按行读取
    for line in content.splitlines():

        line = line.strip()

        if not line:
            continue


        # =========================
        # 识别平台
        # =========================

        if line.startswith("ChatGPT"):

            current_platform = "ChatGPT"

            pending_title = None

            continue


        if line.startswith("豆包"):

            current_platform = "豆包"

            pending_title = None

            continue


        if line.lower().startswith("deepseek"):

            current_platform = "DeepSeek"

            pending_title = None

            continue


        # =========================
        # 提取链接
        # =========================

        match = re.search(
            r'(https?://\S+)',
            line
        )

        if match:

            link = match.group(1)

            # 去掉链接后的可能标点
            link = link.rstrip("，。；;,.")

            # 链接前面的部分就是标题
            title = line[:match.start()].strip()

            # 去掉标题末尾的冒号
            title = title.rstrip("：:")

            if not title:

                title = pending_title or ""

            pending_title = None


            if current_platform and title:

                full_title = (
                    f"{current_platform}_{title}"
                )

                tests.append(
                    (full_title, link)
                )

        elif current_platform and line.endswith(("：", ":")):

            candidate = line.rstrip("：:").strip()

            if candidate not in {"分享链接", "网页对话链接"}:

                pending_title = candidate


    return tests


# ============================================================
# 清理 Windows 文件名
# ============================================================

def clean_filename(filename):

    # Windows 不允许的文件名字符
    filename = re.sub(
        r'[\\/:*?"<>|]',
        "_",
        filename
    )

    # Windows 文件名不能以空格或点结尾
    filename = filename.rstrip(" .")

    return filename


# ============================================================
# 等待 Markdown 文件生成
# ============================================================

def wait_for_export(timeout=10):

    """
    等待 parser.py 生成 AI_memory_export.md

    timeout:
        最长等待时间，单位：秒
    """

    start_time = time.time()

    while True:

        if EXPORT_FILE.exists():

            # 确保文件已经写入完成
            try:

                size_1 = EXPORT_FILE.stat().st_size

                time.sleep(2)

                size_2 = EXPORT_FILE.stat().st_size

                if size_1 == size_2:

                    return True

            except FileNotFoundError:

                pass

        # 超时
        if time.time() - start_time > timeout:

            return False

        time.sleep(1)


# ============================================================
# 执行单个链接
# ============================================================

def process_one(index, total, title, link):

    print()
    print("=" * 70)

    print(
        f"[{index}/{total}] 开始处理：{title}"
    )

    print(
        f"链接：{link}"
    )

    print("=" * 70)


    # 删除上一次生成的文件
    if EXPORT_FILE.exists():

        EXPORT_FILE.unlink()


    # 启动 parser.py
    #
    # 输入：
    #
    # 1
    # 链接
    #
    process = subprocess.Popen(
        [
            "uv",
            "run",
            "parser.py"
        ],

        cwd=BASE_DIR,

        stdin=subprocess.PIPE,

        text=True,

        encoding="utf-8",

        # 让 parser.py 的输出实时显示
        stdout=None,

        stderr=None
    )


    try:

        # 自动输入：
        #
        # 1 + 回车
        # 链接 + 回车
        #
        process.stdin.write(
            f"1\n{link}\n"
        )

        process.stdin.flush()

        # 关闭输入
        process.stdin.close()

        print(
            "已自动输入模式 1 和链接，等待处理..."
        )


        # 等待 parser.py 完成
        return_code = process.wait()


        if return_code != 0:

            print(
                f"❌ parser.py 执行失败，返回码：{return_code}"
            )

            return False


        # 等待生成导出文件
        if not wait_for_export():

            print(
                "❌ 等待 AI_memory_export.md 超时"
            )

            return False


        # 目标文件名
        filename = clean_filename(title)

        target_file = RESULTS_DIR / f"{filename}.md"


        # 如果目标文件已经存在
        if target_file.exists():

            print(
                f"⚠️ 目标文件已存在，将覆盖：{target_file.name}"
            )

            target_file.unlink()


        # parser.py 的人工导出位于项目根目录，图片路径使用 ./images/。
        # 测试结果将被移入 results/，因此在移动前换算相对路径。
        export_content = EXPORT_FILE.read_text(encoding="utf-8")
        export_content = export_content.replace(
            "](./images/",
            "](../images/"
        )
        EXPORT_FILE.write_text(export_content, encoding="utf-8")

        # 移动并重命名
        EXPORT_FILE.rename(target_file)


        print(
            f"✅ 成功保存：{target_file}"
        )


        return True


    except Exception as e:

        print(
            f"❌ 处理过程中发生错误：{e}"
        )

        # 如果进程还在运行，终止它
        if process.poll() is None:

            process.kill()


        return False


# ============================================================
# 主程序
# ============================================================

def main():

    # 创建 results 文件夹
    RESULTS_DIR.mkdir(
        exist_ok=True
    )


    # 读取标题和链接
    tests = read_tests()


    if not tests:

        print(
            "❌ 没有读取到任何标题和链接"
        )

        return


    print(
        f"共读取到 {len(tests)} 个任务"
    )


    success_count = 0


    for index, (title, link) in enumerate(
        tests,
        start=1
    ):

        success = process_one(
            index,
            len(tests),
            title,
            link
        )


        if success:

            success_count += 1


        # 任务之间稍微等待
        time.sleep(2)


    print()
    print("=" * 70)

    print(
        f"全部任务完成！"
    )

    print(
        f"成功：{success_count}/{len(tests)}"
    )

    print("=" * 70)


if __name__ == "__main__":

    main()