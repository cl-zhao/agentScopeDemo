"""命令行启动入口。

该文件保留在项目根目录，便于通过 `python main.py` 启动 HTTP 服务。
"""

from app.main import main
import os
from dotenv import load_dotenv

# 显式加载 .env 文件（推荐放在入口文件顶部）
load_dotenv()
ARK_MODEL = os.getenv("MODEL_NAME")
print("读取环境变量成功" if ARK_MODEL is not None else "未找到环境变量")

if __name__ == "__main__":
    main()
