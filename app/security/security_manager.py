import os
from datetime import datetime, timezone, timedelta

from dotenv import load_dotenv

from app.security.rsa_crypto_service_helper import encrypt, decrypt
from app.security.secure_jwt_handler import generate_token, validate_token


# a端（ai服务） 先加密再签名
# b端（python agentscope服务） 先验证签名再解密

def get_encrypted_token(plain_text: str | dict[str, str]):
    """获取加密后的token"""
    # 1. 生成密钥对
    rsa_key = {
        "PrivateKey": os.getenv("SECURE_JWT_HANDLER_PRIVATE_KEY")
    }

    aud = "ThirdClient"

    password = os.getenv("SECURE_JWT_HANDLER_PASSWORD")

    # issuedUtc 现在
    issuedUtc = datetime.now(timezone.utc)
    expiresUtc = issuedUtc + timedelta(hours=1)
    plain_text_dict: dict
    if plain_text is str:
        plain_text_dict = {
            "data": plain_text
        }
    else:
        plain_text_dict = plain_text

    # 需要传递的数据
    claims: dict = {}
    # 变量 plain_text_dict 的所有元素
    for k, v in plain_text_dict.items():
        encrypt_data = _get_encrypted_data(v)
        claims["encrypted_" + k] = encrypt_data


    token = generate_token("3", "1", aud, rsa_key["PrivateKey"], password, data=claims, issued_utc=issuedUtc,
                           expires_utc=expiresUtc)
    return token


def get_decrypted_principal(token: str):
    """获取解密后的principal"""
    # 1. 生成密钥对
    rsa_key = {
        "PublicKey": os.getenv("SECURE_JWT_HANDLER_PUBLIC_KEY"),
    }

    aud = "ThirdClient"

    decrypted_principal = validate_token(token, rsa_key["PublicKey"], aud)
    new_data = {}
    need_remove_keys = []
    for k, v in decrypted_principal.items():
        if k.startswith("encrypted_"):
            need_remove_keys.append(k)
            decrypted_data = _get_decrypted_data(v)
            new_data[k.replace("encrypted_", "")] = decrypted_data

    for need_remove_key in need_remove_keys:
        decrypted_principal.pop(need_remove_key)

    decrypted_principal.update(new_data)

    return decrypted_principal


def _get_encrypted_data(plain_text: str):
    # 1. 生成密钥对
    rsa_key = {
        "PublicKey": os.getenv("RSA_CRYPTO_SERVICE_HELPER_PUBLIC_KEY"),
    }
    encrypted = encrypt(plain_text, rsa_key["PublicKey"])
    return encrypted


def _get_decrypted_data(encrypted_text: str):
    # 1. 生成密钥对
    rsa_key = {
        "PrivateKey": os.getenv("RSA_CRYPTO_SERVICE_HELPER_PRIVATE_KEY")
    }
    decrypted = decrypt(encrypted_text, rsa_key["PrivateKey"])
    return decrypted


def test():
    # 显式加载 .env 文件（推荐放在入口文件顶部）
    load_dotenv()
    ARK_MODEL = os.getenv("MODEL_NAME")
    print("读取环境变量成功" if ARK_MODEL is not None else "未找到环境变量")

    token = get_encrypted_token(
        "RSA_CRYPTO_SERVICE_HELPER_PRIVATE_KEYRSA_CRYPTO_SERVICE_HELPER_PRIVATEeyJodHRwOi8vc2NoZW1hcy54bWxzb2FwLm9yZy93cy8yMDA1LzA1L2lkZW50aXR5L2NsYWltcy9uYW1laWRlbnRpZmllciI6IjMiLCJodHRwOi8vd3d3LmFzcG5ldGJvaWxlcnBsYXRlLmNvbS9pZGVudGl0eS9jbGFpbXMvdGVuYW50SWQiOiIxIiwiaWF0IjoxNzczMzAzNDk3LCJleHAiOjE3NzMzMDcwOTcsImlzcyI6ImdkdHlraiIsImF1ZCI6IlRoaXJkQ2xpZW50IiwiZW5jcnlwdGVkX2RhdGEiOiJwYlFFM2kyUG1vWHhjSE1WYm55T3ViTUQycWllN2Eza0l5VC9GSG1FOE84RUFBZXdLMk5vOFZmVU1PUmRPN2V5Q0NZLzU4dFJGWGFwdWtES1lmbHRNb0doeThoQ08veUp3OEtCeVFJQ1hhT2djMU9lTHVBUXRsWGpCZThvVG1ZY2Q5VkhBMTZIZnc3OU1USWVEZG5mSTl0VEUwbmNqbzJqckZCeVZCOG5EY1BQMG1nb1lDVHdBV1hUNXRpSDVOS0tETnA0MEh0TEhDQnZqbFkxRWtrSVExYmVJSDBVVHB1dnBUYUVyeE5BQjFSREV1NWRROTVXRDRzaVNCYVBMN2ZMa0J5OUprRytjY2dmbDNVZWhpUHFKYllzV1ZwdDUzT2Y5U05PYXJxUU9QWDVsa1UzZEtYVDV2aThJT1VPV2NNc25NRUswcUFuSW9tSTNxMGtaMzFSbUE9PSJ9eyJodHRwOi8vc2NoZW1hcy54bWxzb2FwLm9yZy93cy8yMDA1LzA1L2lkZW50aXR5L2NsYWltcy9uYW1laWRlbnRpZmllciI6IjMiLCJodHRwOi8vd3d3LmFzcG5ldGJvaWxlcnBsYXRlLmNvbS9pZGVudGl0eS9jbGFpbXMvdGVuYW50SWQiOiIxIiwiaWF0IjoxNzczMzAzNDk3LCJleHAiOjE3NzMzMDcwOTcsImlzcyI6ImdkdHlraiIsImF1ZCI6IlRoaXJkQ2xpZW50IiwiZW5jcnlwdGVkX2RhdGEiOiJwYlFFM2kyUG1vWHhjSE1WYm55T3ViTUQycWllN2Eza0l5VC9GSG1FOE84RUFBZXdLMk5vOFZmVU1PUmRPN2V5Q0NZLzU4dFJGWGFwdWtES1lmbHRNb0doeThoQ08veUp3OEtCeVFJQ1hhT2djMU9lTHVBUXRsWGpCZThvVG1ZY2Q5VkhBMTZIZnc3OU1USWVEZG5mSTl0VEUwbmNqbzJqckZCeVZCOG5EY1BQMG1nb1lDVHdBV1hUNXRpSDVOS0tETnA0MEh0TEhDQnZqbFkxRWtrSVExYmVJSDBVVHB1dnBUYUVyeE5BQjFSREV1NWRROTVXRDRzaVNCYVBMN2ZMa0J5OUprRytjY2dmbDNVZWhpUHFKYllzV1ZwdDUzT2Y5U05PYXJxUU9QWDVsa1UzZEtYVDV2aThJT1VPV2NNc25NRUswcUFuSW9tSTNxMGtaMzFSbUE9PSJ9eyJodHRwOi8vc2NoZW1hcy54bWxzb2FwLm9yZy93cy8yMDA1LzA1L2lkZW50aXR5L2NsYWltcy9uYW1laWRlbnRpZmllciI6IjMiLCJodHRwOi8vd3d3LmFzcG5ldGJvaWxlcnBsYXRlLmNvbS9pZGVudGl0eS9jbGFpbXMvdGVuYW50SWQiOiIxIiwiaWF0IjoxNzczMzAzNDk3LCJleHAiOjE3NzMzMDcwOTcsImlzcyI6ImdkdHlraiIsImF1ZCI6IlRoaXJkQ2xpZW50IiwiZW5jcnlwdGVkX2RhdGEiOiJwYlFFM2kyUG1vWHhjSE1WYm55T3ViTUQycWllN2Eza0l5VC9GSG1FOE84RUFBZXdLMk5vOFZmVU1PUmRPN2V5Q0NZLzU4dFJGWGFwdWtES1lmbHRNb0doeThoQ08veUp3OEtCeVFJQ1hhT2djMU9lTHVBUXRsWGpCZThvVG1ZY2Q5VkhBMTZIZnc3OU1USWVEZG5mSTl0VEUwbmNqbzJqckZCeVZCOG5EY1BQMG1nb1lDVHdBV1hUNXRpSDVOS0tETnA0MEh0TEhDQnZqbFkxRWtrSVExYmVJSDBVVHB1dnBUYUVyeE5BQjFSREV1NWRROTVXRDRzaVNCYVBMN2ZMa0J5OUprRytjY2dmbDNVZWhpUHFKYllzV1ZwdDUzT2Y5U05PYXJxUU9QWDVsa1UzZEtYVDV2aThJT1VPV2NNc25NRUswcUFuSW9tSTNxMGtaMzFSbUE9PSJ9_KEYRSA_CRYPTO_SERVICE_HELPER_PRIVATE_KEYRSA_CRYPTO_SERVICE_HELPER_PRIVATE_KEYRSA_CRYPTO_SERVICE_HELPER_PRIVATE_KEY")
    print(token)
    decrypted_principal = get_decrypted_principal(token)
    print(decrypted_principal)


if __name__ == "__main__":
    test()
