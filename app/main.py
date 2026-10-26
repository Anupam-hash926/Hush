from fastapi import FastAPI, HTTPException, Depends
from app.security import get_password_hash, verify_password, create_access_token, get_current_user
from app.schemas import UserCreate, UserLogin, Token, ProjectCreate, ProjectMember,SecretCreate,SecretResponse
from app.crud import create_user_in_db, get_user_by_email, create_project_in_db, share_project_in_db,get_user_projects_from_db,create_secret_in_db,get_project_secrets_from_db,create_access_request_in_neo4j
from app.crypto import encrypt_secret, decrypt_secret
from app.database import redis_client
from cryptography.exceptions import InvalidTag

app = FastAPI(title="Hush API")

@app.get("/")
async def root():
    return {"message": "Hush is up and running!"}

@app.post("/register")
def register_user(user: UserCreate):
    hashed_pw = get_password_hash(user.password)
    created_email = create_user_in_db(user.email, hashed_pw)
    
    if not created_email:
        raise HTTPException(status_code=400, detail="User already exists")
        
    return {"message": "User registered successfully", "email": created_email}

@app.post("/login", response_model=Token)
def login(user: UserLogin):
    password_hash = get_user_by_email(user.email)
    
    if not password_hash or not verify_password(user.password, password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
        
    token = create_access_token({"sub": user.email})
    return {"access_token": token, "token_type": "bearer"}

@app.get("/me")
async def read_current_user(current_user: str = Depends(get_current_user)):
    return {"message": "You are authenticated!", "user": current_user}

@app.post("/projects")
def create_project(project:ProjectCreate,current_user:str = Depends(get_current_user)):
    new_project=create_project_in_db(current_user,project.name,project.description)
    if not new_project :
        raise HTTPException(status_code=404,detail="Owner user not found")
    return {"message":"Project created","project":new_project}

@app.post("/projects/{project_id}/share")
def share_project(project_id: str,member:ProjectMember,current_user: str = Depends(get_current_user)):
    shared_result=share_project_in_db(current_user,project_id,member.target_email,member.role)
    if not shared_result:
        raise HTTPException(status_code=400,detail="Invalid project or target user")
    return{"message":"Access granted","details":shared_result}

@app.get("/projects")
def get_projects(current_user: str = Depends(get_current_user)):
    user_projects = get_user_projects_from_db(current_user)
    if not user_projects:
        raise HTTPException(status_code=404,detail="No projects found!")
    return{"projects":user_projects}

@app.post("/projects/{project_id}/secrets", response_model=SecretResponse)
def add_secret(project_id: str, secret: SecretCreate, current_user: str = Depends(get_current_user)):
    encrypted_data = encrypt_secret(secret.secret_value)
    saved_secret = create_secret_in_db(current_user,project_id,secret.key_name,encrypted_data,secret.quorum_size,secret.access_window_hours,secret.max_views)
    if not saved_secret:
        raise HTTPException(status_code=403,detail="User lacks access or project doesn't exist")
    return saved_secret

@app.post("/projects/{project_id}/secrets/reveal")
def reveal_secrets(project_id: str, current_user: str = Depends(get_current_user)):
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
            
            plain_text = decrypt_secret(crypto_dict)
            
            decrypted_results.append({
                "id": sec["id"],
                "key_name": sec["key_name"],
                "secret_value": plain_text
            })
    except InvalidTag:
        raise HTTPException(status_code=401, detail="Invalid vault password or corrupted data")
        
    return {"secrets": decrypted_results}

@app.post("/projects/{project_id}/secrets/{secret_id}/request")
def request_secret_access(project_id: str, secret_id: str, current_user: str = Depends(get_current_user)):
    """
    Logs the access request in Neo4j and initializes the approval counter in Redis.
    """
    access_record = create_access_request_in_neo4j(current_user, project_id, secret_id)
    if not access_record:
        raise HTTPException(status_code=403, detail="Unauthorized or secret not found") 
    ttl_in_seconds = access_record["access_window_hours"] * 3600  
    redis_key = f"request:{secret_id}:{current_user}:approvals"  
    redis_client.set(name=redis_key, value=0, ex=ttl_in_seconds, nx=True)  
    return {"message": "Access request initiated", "status": "pending"}
    