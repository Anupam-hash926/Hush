from fastapi import FastAPI, HTTPException, Depends
from app.security import get_password_hash, verify_password, create_access_token, get_current_user
from app.schemas import UserCreate, UserLogin, Token, ProjectCreate, ProjectMember,SecretCreate, SecretDecrypt, SecretResponse
from app.crud import create_user_in_db, get_user_by_email, create_project_in_db, share_project_in_db,get_user_projects_from_db,create_secret_in_db,get_project_secrets_from_db
from app.crypto import encrypt_secret, decrypt_secret
from cryptography.exceptions import InvalidTag

app = FastAPI(title="Hush API")

@app.get("/")
async def root():
    return {"message": "Hush is up and running!"}

@app.post("/register")
async def register_user(user: UserCreate):
    hashed_pw = get_password_hash(user.password)
    created_email = create_user_in_db(user.email, hashed_pw)
    
    if not created_email:
        raise HTTPException(status_code=400, detail="User already exists")
        
    return {"message": "User registered successfully", "email": created_email}

@app.post("/login", response_model=Token)
async def login(user: UserLogin):
    password_hash = get_user_by_email(user.email)
    
    if not password_hash or not verify_password(user.password, password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
        
    token = create_access_token({"sub": user.email})
    return {"access_token": token, "token_type": "bearer"}

@app.get("/me")
async def read_current_user(current_user: str = Depends(get_current_user)):
    return {"message": "You are authenticated!", "user": current_user}

@app.post("/projects")
async def create_project(project:ProjectCreate,current_user:str = Depends(get_current_user)):
    new_project=create_project_in_db(current_user,project.name,project.description)
    if not new_project :
        raise HTTPException(status_code=404,detail="Owner user not found")
    return {"message":"Project created","project":new_project}

@app.post("/projects/{project_id}/share")
async def share_project(project_id: str,member:ProjectMember,current_user: str = Depends(get_current_user)):
    shared_result=share_project_in_db(current_user,project_id,member.target_email,member.role)
    if not shared_result:
        raise HTTPException(status_code=400,detail="Invalid project or target user")
    return{"message":"Access granted","details":shared_result}

@app.get("/projects")
async def get_projects(current_user: str = Depends(get_current_user)):
    user_projects = get_user_projects_from_db(current_user)
    if not user_projects:
        raise HTTPException(status_code=404,detail="No projects found!")
    return{"projects":user_projects}

@app.post("/projects/{project_id}/secrets", response_model=SecretResponse)
async def add_secret(project_id: str, secret: SecretCreate, current_user: str = Depends(get_current_user)):
    encrypted_data = encrypt_secret(secret.secret_value,secret.vault_password)
    saved_secret = create_secret_in_db(current_user,project_id,secret.key_name,encrypted_data)
    if not saved_secret:
        raise HTTPException(status_code=403,detail="User lacks access or project doesn't exist")
    return saved_secret

@app.post("/projects/{project_id}/secrets/reveal")
async def reveal_secrets(project_id: str, payload: SecretDecrypt, current_user: str = Depends(get_current_user)):
    encrypted_secrets = get_project_secrets_from_db(current_user, project_id)
    
    if not encrypted_secrets:
        raise HTTPException(status_code=404, detail="No secrets found for this project")
    
    decrypted_results = []
    
    try:
        for sec in encrypted_secrets:
            crypto_dict = {
                "salt": sec["salt"],
                "nonce": sec["nonce"],
                "ciphertext": sec["ciphertext"]
            }
            
            plain_text = decrypt_secret(crypto_dict, payload.vault_password)
            
            decrypted_results.append({
                "id": sec["id"],
                "key_name": sec["key_name"],
                "secret_value": plain_text
            })
    except InvalidTag:
        raise HTTPException(status_code=401, detail="Invalid vault password or corrupted data")
        
    return {"secrets": decrypted_results}