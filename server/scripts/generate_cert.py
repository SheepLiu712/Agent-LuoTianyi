"""
生成自签名 SSL 证书用于 HTTPS 服务

使用方法：
python scripts/generate_cert.py
"""
import os
import subprocess
import sys

def generate_self_signed_cert():
    """使用 OpenSSL 生成自签名证书"""
    
    # 确保 certs 目录存在
    certs_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "certs")
    os.makedirs(certs_dir, exist_ok=True)
    
    cert_file = os.path.join(certs_dir, "cert.pem")
    key_file = os.path.join(certs_dir, "key.pem")
    
    # 检查是否已存在证书
    if os.path.exists(cert_file) and os.path.exists(key_file):
        print(f"证书已存在：")
        print(f"  证书文件: {cert_file}")
        print(f"  密钥文件: {key_file}")
        response = input("是否重新生成？(y/n): ")
        if response.lower() != 'y':
            print("跳过生成")
            return cert_file, key_file
    
    print("正在生成自签名 SSL 证书...")
    
    # OpenSSL 命令
    cmd = [
        "openssl", "req", "-x509", "-newkey", "rsa:4096",
        "-keyout", key_file,
        "-out", cert_file,
        "-days", "365",
        "-nodes",
        "-subj", "/C=CN/ST=Beijing/L=Beijing/O=LuoTianyi/CN=localhost"
    ]
    return generate_cert_with_python()
    try:
        subprocess.run(cmd, check=True, capture_output=True)
        print(f"✅ 证书生成成功！")
        print(f"  证书文件: {cert_file}")
        print(f"  密钥文件: {key_file}")
        print(f"  有效期: 365 天")
        return cert_file, key_file
    except subprocess.CalledProcessError as e:
        print(f"❌ 生成证书失败: {e}")
        print(f"错误输出: {e.stderr.decode()}")
        print("\n如果没有安装 OpenSSL，请：")
        print("1. 下载 Git for Windows (包含 OpenSSL)")
        print("2. 或使用下面的 Python 替代方案")
        # sys.exit(1)
        return generate_cert_with_python()
    except FileNotFoundError:
        print("❌ 未找到 OpenSSL 命令")
        print("\n尝试使用 Python 生成证书...")
        return generate_cert_with_python()

def generate_cert_with_python():
    """使用 Python cryptography 库生成证书"""
    try:
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.primitives import serialization
        import datetime
    except ImportError:
        print("❌ 需要安装 cryptography 库")
        print("运行: pip install cryptography")
        sys.exit(1)
    
    certs_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "certs")
    os.makedirs(certs_dir, exist_ok=True)
    
    cert_file = os.path.join(certs_dir, "cert.pem")
    key_file = os.path.join(certs_dir, "key.pem")
    
    print("使用 Python 生成自签名证书...")
    
    # 生成私钥
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=4096,
    )
    
    # 生成证书
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "CN"),
        x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, "Beijing"),
        x509.NameAttribute(NameOID.LOCALITY_NAME, "Beijing"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "LuoTianyi"),
        x509.NameAttribute(NameOID.COMMON_NAME, "localhost"),
    ])
    import ipaddress
    cert = x509.CertificateBuilder().subject_name(
        subject
    ).issuer_name(
        issuer
    ).public_key(
        private_key.public_key()
    ).serial_number(
        x509.random_serial_number()
    ).not_valid_before(
        datetime.datetime.utcnow()
    ).not_valid_after(
        datetime.datetime.utcnow() + datetime.timedelta(days=365)
    ).add_extension(
        x509.SubjectAlternativeName([
            x509.DNSName("localhost"),
            x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
        ]),
        critical=False,
    ).sign(private_key, hashes.SHA256())
    
    # 保存私钥
    with open(key_file, "wb") as f:
        f.write(private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption()
        ))
    
    # 保存证书
    with open(cert_file, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))
    
    print(f"✅ 证书生成成功！")
    print(f"  证书文件: {cert_file}")
    print(f"  密钥文件: {key_file}")
    print(f"  有效期: 365 天")
    
    return cert_file, key_file

if __name__ == "__main__":
    print("=" * 60)
    print("洛天依服务 - SSL 证书生成工具")
    print("=" * 60)
    print()
    
    try:
        cert_file, key_file = generate_self_signed_cert()
        print()
        print("=" * 60)
        print("📝 下一步操作：")
        print("1. 运行服务: python server_main.py")
        print("2. 访问时使用 HTTPS: https://your-domain:port")
        print("3. 浏览器会提示不安全，点击「继续访问」即可")
        print("=" * 60)
    except KeyboardInterrupt:
        print("\n\n操作已取消")
        sys.exit(0)
