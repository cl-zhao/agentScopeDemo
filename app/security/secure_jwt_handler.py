import os
from typing import Any

import jwt
from datetime import datetime, timezone, timedelta
from Crypto.PublicKey import RSA
import base64
import sys

from dotenv import load_dotenv

# =============================================================================
# 全局配置 (对应 C# 中的 _issuer)
# 建议从环境变量读取: ISSUER = os.getenv("JWT_ISSUER")
# 如果没有设置环境变量，这里给个默认值防止报错，实际使用请替换
# =============================================================================
ISSUER = os.getenv("JWT_ISSUER", "gdtykj")


def generate_token(user_id: str, tenant_id: str, audience: str,
                   private_key_base64: str, rsa_password: str,
                   data: dict = None,
                   issued_utc: datetime = None,
                   expires_utc: datetime = None) -> str:
    """
    生成 JWT Token
    对应 C# 方法: GenerateToken
    """
    # 1. 解析并导入私钥 (对应 C#: rsa.ImportEncryptedPkcs8PrivateKey)
    private_key_bytes = base64.b64decode(private_key_base64)
    try:
        rsa_private_key = RSA.import_key(private_key_bytes, passphrase=rsa_password)
    except ValueError as e:
        raise ValueError(f"私钥导入失败，请检查 RSA 密码是否正确: {e}")

    # 2. 处理时间 (对应 C#: issued = issuedUtc ?? DateTime.UtcNow)
    # 注意：C# 使用 DateTime.UtcNow，Python 应使用 aware datetime (带时区)
    now = datetime.now(timezone.utc)
    issued = issued_utc if issued_utc else now
    # C# 默认加 1 小时: expires = expiresUtc ?? issued.AddHours(1)
    expires = expires_utc if expires_utc else (issued + timedelta(hours=1))

    # 3. 构建 Claims (对应 C# List<Claim>)
    # C# ClaimTypes.NameIdentifier 通常对应 JWT 标准中的 "sub"
    # tenantId 使用了完整的 URL 声明，与 C# 保持一致
    name_identifier = "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/nameidentifier";
    payload = {
        name_identifier: user_id,
        "http://www.aspnetboilerplate.com/identity/claims/tenantId": tenant_id,
        "iat": issued,
        "exp": expires,
        "iss": ISSUER,
        "aud": audience
    }

    # 合并额外的自定义数据 (data 为字典)
    if data:
        payload.update(data)

    # 4. 生成 Token (对应 C#: SecurityAlgorithms.RsaSha256Signature)
    # PyJWT 需要 PEM 格式的密钥
    private_pem = rsa_private_key.export_key().decode('utf-8')

    # 编码生成 JWT
    # leeway=300 对应 C# 的 ClockSkew = TimeSpan.FromMinutes(5)，允许验证时多容忍5分钟
    token = jwt.encode(payload, private_pem, algorithm="RS256")

    return token


def validate_token(token: str, public_key_base64: str, expected_audience: str) -> dict[str, Any]:
    """
    验证并解析 JWT Token
    对应 C# 方法: ValidateToken
    """
    # 1. 解析并导入公钥 (对应 C#: rsa.ImportSubjectPublicKeyInfo)
    public_key_bytes = base64.b64decode(public_key_base64)
    rsa_public_key = RSA.import_key(public_key_bytes)
    public_pem = rsa_public_key.export_key().decode('utf-8')
    name_identifier = "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/nameidentifier";

    # 2. 验证 Token
    # 注意：ISSUER 必须是字符串，不能为 None，否则验证会失败
    try:
        # PyJWT 会自动验证 exp, iat, aud, iss
        payload = jwt.decode(
            token,
            public_pem,
            algorithms=["RS256"],
            audience=expected_audience,
            issuer=ISSUER,
            options={
                "verify_aud": True,
                "verify_iss": True,
                "verify_exp": True,
                "verify_iat": True,
                "require": ["exp", "iat", name_identifier, "aud", "iss"]  # 强制要求这些字段
            },
            leeway=300  # 对应 C# 的 ClockSkew = TimeSpan.FromMinutes(5)
        )
        return payload
    except jwt.ExpiredSignatureError:
        raise Exception("Token 已过期")
    except jwt.InvalidAudienceError:
        raise Exception("Audience 验证失败")
    except jwt.InvalidIssuerError:
        raise Exception("Issuer 验证失败")
    except jwt.DecodeError:
        raise Exception("Token 解析失败 (签名可能不正确)")
    except Exception as e:
        raise Exception(f"Token 验证失败: {str(e)}")


def test():
    """运行 JWT 生成与校验的本地冒烟测试。"""
    # 测试用例
    # 显式加载 .env 文件（推荐放在入口文件顶部）
    load_dotenv()
    ARK_MODEL = os.getenv("MODEL_NAME")
    print("读取环境变量成功" if ARK_MODEL is not None else "未找到环境变量")

    # 1. 生成密钥对
    rsa_key = {
        "PublicKey": os.getenv("SECURE_JWT_HANDLER_PUBLIC_KEY"),
        "PrivateKey": os.getenv("SECURE_JWT_HANDLER_PRIVATE_KEY")
    }
    print(rsa_key)

    aud = "ThirdClient";

    password = os.getenv("SECURE_JWT_HANDLER_PASSWORD")
    raw_test = "hello world"
    # issuedUtc 现在
    issuedUtc = datetime.now(timezone.utc)
    expiresUtc = issuedUtc + timedelta(hours=1)
    data = {
        # 需要传递的数据
        "access_token": "bearer 1234567890"
    }

    token = generate_token("3", "1", aud, rsa_key["PrivateKey"], password, data=data, issued_utc=issuedUtc,
                           expires_utc=expiresUtc)
    print(token)
    princ = validate_token(token, rsa_key["PublicKey"], aud)
    print(princ)

    # 4. 测试加密解密


if __name__ == "__main__":
    test()
