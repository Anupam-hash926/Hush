import os
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
def derive_key(password: bytes, salt: bytes)-> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=600000,
    )
    return kdf.derive(password.encode('utf-8'))
def encrypt_secret(plain_text: str, password:str) -> dict:
    salt = os.urandom(16)
    key = derive_key(password, salt)
    nonce = os.urandom(12)
    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(nonce,plain_text.encode('utf-8'),None)
    return {
        "salt": salt.hex(),
        "nonce": nonce.hex(),
        "ciphertext": ciphertext.hex()
    }
def decrypt_secret(encrypted_data: dict, password: str) -> str:
    salt = bytes.fromhex(encrypted_data["salt"])
    nonce = bytes.fromhex(encrypted_data["nonce"])
    ciphertext = bytes.fromhex(encrypted_data["ciphertext"])
    key = derive_key(password, salt)
    aesgcm = AESGCM(key)
    decrypted_bytes = aesgcm.decrypt(nonce, ciphertext, None)
    return decrypted_bytes.decode('utf-8')
if __name__ == "__main__":
    # Test execution block to verify functionality locally
    test_secret = "Hush Master Key: 0x99812A"
    test_password = "MyVaultPassword!2026"

    print("Running cryptographic sanity check...")
    
    # Encrypt
    encrypted_payload = encrypt_secret(test_secret, test_password)
    print(f"Encrypted Output Payload: {encrypted_payload}")

    # Decrypt
    decrypted_output = decrypt_secret(encrypted_payload, test_password)
    print(f"Decrypted Output String:  {decrypted_output}")

    # Verify matching result
    assert test_secret == decrypted_output
    print("✅ Cipher verification succeeded!")