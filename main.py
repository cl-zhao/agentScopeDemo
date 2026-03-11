"""命令行启动入口。

该文件保留在项目根目录，便于通过 `python main.py` 启动 HTTP 服务。
"""

from app.main import main


if __name__ == "__main__":
    main()
