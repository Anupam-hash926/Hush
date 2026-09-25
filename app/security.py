import bcrypt
def get_password_hash(password:str) -> str:
    pwd_bytes=password.encode('utf-8')
    salt=bcrypt.gensalt()
    hashed_password=bcrypt.hashpw(pwd_bytes,salt)
    return hashed_password.decode('utf-8')

def verify_password(plain_password:str,hashed_password:str) -> str:
    password_byte_enc=plain_password.encode('utf-8')
    hashed_password_bytes=hashed_password.encode('utf-8')
    return bcrypt.checkpw(password_byte_enc,hashed_password_bytes)
