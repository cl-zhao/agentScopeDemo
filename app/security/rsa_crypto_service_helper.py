import base64
import os

from Crypto.PublicKey import RSA
from Crypto.Cipher import PKCS1_OAEP
from Crypto.Hash import SHA256
from dotenv import load_dotenv


def decrypt(base64_cipher_text: str, base64_private_key: str) -> str:
    """解密经过 Base64 编码的 RSA OAEP 密文。"""
    # ===================== 注意替换成你C#端原有的密码 =====================
    # 密码编码要和C#端对齐，PKCS8标准默认用UTF8编码，直接把你C#的Password字符串转utf8字节即可
    # 比如C#里Password是"abc123"，这里就写 PASSWORD = "abc123".encode("utf8")
    PASSWORD = os.getenv("RSA_CRYPTO_SERVICE_HELPER_PASSWORD")
    # ===================================================================

    # 1. 解码base64格式的加密私钥
    private_key_bytes = base64.b64decode(base64_private_key)
    # 2. 导入带密码的PKCS8格式私钥，和C#的ImportEncryptedPkcs8PrivateKey完全对齐
    rsa_private_key = RSA.import_key(private_key_bytes, passphrase=PASSWORD)
    # 3. 构造OAEP解密器，和C#的RSAEncryptionPadding.OaepSHA256规则一致：
    #    哈希算法用SHA256，MGF1掩码生成算法也用SHA256
    cipher = PKCS1_OAEP.new(
        rsa_private_key,
        hashAlgo=SHA256,
    )
    # 4. 解码base64格式的密文
    cipher_bytes = base64.b64decode(base64_cipher_text)
    # 5. 解密后转UTF8字符串返回
    decrypted_bytes = cipher.decrypt(cipher_bytes)
    return decrypted_bytes.decode("utf8")

def encrypt(plain_text: str, base64_public_key: str) -> str:
    """使用 RSA 公钥加密明文，并返回 Base64 密文。"""
    # 1. 解码base64格式公钥 → 对应C# Convert.FromBase64String(publicKeyBytes)
    public_key_bytes = base64.b64decode(base64_public_key)
    # 2. 导入X.509格式(SubjectPublicKeyInfo)公钥 → 对应C# ImportSubjectPublicKeyInfo
    rsa_public_key = RSA.import_key(public_key_bytes)
    # 3. 构造OAEP加密器，和C#的RSAEncryptionPadding.OaepSHA256规则完全对齐
    # 哈希算法、MGF1掩码算法都用SHA256，和C#默认规则一致
    cipher = PKCS1_OAEP.new(
        rsa_public_key,
        hashAlgo=SHA256,
    )
    # 4. 明文转UTF8字节 → 对应C# Encoding.UTF8.GetBytes(plainText)
    plain_bytes = plain_text.encode("utf8")
    # 5. 加密后转base64字符串返回 → 对应C# Convert.ToBase64String(encryptedBytes)
    encrypted_bytes = cipher.encrypt(plain_bytes)
    return base64.b64encode(encrypted_bytes).decode("utf8")

def test():
    """使用环境变量中的密钥运行 RSA 辅助工具本地冒烟测试。"""
    # 测试用例
    # 显式加载 .env 文件（推荐放在入口文件顶部）
    load_dotenv()
    ARK_MODEL = os.getenv("MODEL_NAME")
    print("读取环境变量成功" if ARK_MODEL is not None else "未找到环境变量")

    # 1. 生成密钥对
    rsa_key = {
        "PublicKey": os.getenv("RSA_CRYPTO_SERVICE_HELPER_PUBLIC_KEY"),
        "PrivateKey": os.getenv("RSA_CRYPTO_SERVICE_HELPER_PRIVATE_KEY")
    }
    print(rsa_key)


    raw_test = "hello world"
    test = encrypt(raw_test, rsa_key["PublicKey"])
    print(decrypt(test, rsa_key["PrivateKey"]))

    # 4. 测试加密解密

if __name__ == "__main__":
    test()
