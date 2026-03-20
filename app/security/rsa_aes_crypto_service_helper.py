import base64
import os
import json
from Crypto.PublicKey import RSA
from Crypto.Cipher import PKCS1_OAEP, AES
from Crypto.Hash import SHA256
from Crypto.Random import get_random_bytes
from dotenv import load_dotenv


def pkcs7_pad(data: bytes, block_size: int) -> bytes:
    """PKCS7 填充"""
    padding_length = block_size - (len(data) % block_size)
    padding = bytes([padding_length] * padding_length)
    return data + padding


def pkcs7_unpad(data: bytes) -> bytes:
    """PKCS7 去除填充"""
    padding_length = data[-1]
    return data[:-padding_length]


def encrypt(plain_text: str, base64_public_key: str) -> str:
    """混合加密：RSA + AES-CBC"""
    # 1. 生成随机 AES-256 密钥（32字节 = 256位）
    aes_key = get_random_bytes(32)

    # 2. 生成随机 IV（16字节）
    iv = get_random_bytes(16)

    # 3. 用 AES-CBC 加密明文
    cipher_aes = AES.new(aes_key, AES.MODE_CBC, iv)
    plain_bytes = plain_text.encode('utf8')
    # PKCS7 填充
    padded_data = pkcs7_pad(plain_bytes, AES.block_size)
    encrypted_data = cipher_aes.encrypt(padded_data)

    # 4. 用 RSA 公钥加密 AES 密钥
    public_key_bytes = base64.b64decode(base64_public_key)
    rsa_public_key = RSA.import_key(public_key_bytes)
    cipher_rsa = PKCS1_OAEP.new(rsa_public_key, hashAlgo=SHA256)
    encrypted_aes_key = cipher_rsa.encrypt(aes_key)

    # 5. 组装成 JSON 格式返回（便于扩展和调试）
    result = {
        "iv": base64.b64encode(iv).decode('utf8'),
        "key": base64.b64encode(encrypted_aes_key).decode('utf8'),
        "data": base64.b64encode(encrypted_data).decode('utf8')
    }
    return base64.b64encode(json.dumps(result).encode('utf8')).decode('utf8')


def decrypt(base64_cipher_text: str, base64_private_key: str) -> str:
    """混合解密：RSA + AES-CBC"""
    # ===================== 注意替换成你C#端原有的密码 =====================
    PASSWORD = os.getenv("RSA_CRYPTO_SERVICE_HELPER_PASSWORD")
    # ===================================================================

    # 1. 解析 JSON 格式的密文
    cipher_json_bytes = base64.b64decode(base64_cipher_text)
    cipher_json_str = cipher_json_bytes.decode('utf8')
    cipher_obj = json.loads(cipher_json_str)

    # 2. 解码各部分
    iv = base64.b64decode(cipher_obj['iv'])
    encrypted_aes_key = base64.b64decode(cipher_obj['key'])
    encrypted_data = base64.b64decode(cipher_obj['data'])

    # 3. 用 RSA 私钥解密得到 AES 密钥
    private_key_bytes = base64.b64decode(base64_private_key)
    rsa_private_key = RSA.import_key(private_key_bytes, passphrase=PASSWORD)
    cipher_rsa = PKCS1_OAEP.new(rsa_private_key, hashAlgo=SHA256)
    aes_key = cipher_rsa.decrypt(encrypted_aes_key)

    # 4. 用 AES 密钥解密数据
    cipher_aes = AES.new(aes_key, AES.MODE_CBC, iv)
    decrypted_padded = cipher_aes.decrypt(encrypted_data)

    # 5. 去除填充并返回字符串
    decrypted_bytes = pkcs7_unpad(decrypted_padded)
    return decrypted_bytes.decode('utf8')


def test():
    """测试用例"""
    load_dotenv()

    rsa_key = {
        "PublicKey": os.getenv("RSA_CRYPTO_SERVICE_HELPER_PUBLIC_KEY"),
        "PrivateKey": os.getenv("RSA_CRYPTO_SERVICE_HELPER_PRIVATE_KEY")
    }

    # 测试短文本
    short_text = "hello world"
    encrypted = encrypt(short_text, rsa_key["PublicKey"])
    decrypted = decrypt(encrypted, rsa_key["PrivateKey"])
    print(f"短文本测试: {short_text} -> {decrypted}")
    assert short_text == decrypted

    # 测试长文本（模拟你的长参数场景）
    long_text = "A" * 5000  # 5KB 的测试数据
    encrypted = encrypt(long_text, rsa_key["PublicKey"])
    decrypted = decrypt(encrypted, rsa_key["PrivateKey"])
    print(f"长文本测试: {len(long_text)} 字符 -> 解密成功: {len(decrypted)} 字符")
    assert long_text == decrypted

    print("✅ 所有测试通过!")


if __name__ == "__main__":
    test()