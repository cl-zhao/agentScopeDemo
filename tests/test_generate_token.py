import os

from dotenv import load_dotenv

from app.security.security_manager import get_encrypted_token

# 显式加载 .env 文件（推荐放在入口文件顶部）
load_dotenv()
ARK_MODEL = os.getenv("MODEL_NAME")
print("读取环境变量成功" if ARK_MODEL is not None else "未找到环境变量")


def test_generate_token():
    """测试生成 加密后的token。"""

    # 替换这里为原始的访问飞龙版的token
    raw_token = "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCIsImtpZCI6IjEifQ.eyJzdWIiOiJhZG1pbiIsImlhdCI6MTY4MjE5NjQwOSwiZXhwIjoxNjgyMjAwMDA5LCJhdWQiOiJodHRwczovL2FwaS5maWxlbmVyLmNvbS9hcGkvYXBpL2F1dGgvYXV0"
    session_id = "sk-1234567890"
    token = get_encrypted_token({"token": raw_token, "session_id": session_id})
    print("\n")
    print(token)
    return
