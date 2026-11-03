from fastapi import FastAPI, HTTPException, Depends
from cryptography.exceptions import InvalidTag
from app import security, schemas, crud, crypto
from app.database import redis_client
import secrets

app = FastAPI(title="Hush API")

@app.get("/")
async def root():
    return {"message": "Hush is up and running!"}

@app.post("/register")
def register_user(user: schemas.UserCreate):
    hashed_pw = security.get_password_hash(user.password)
    created_email = crud.create_user_in_db(user.email, hashed_pw)
    
    if not created_email:
        raise HTTPException(status_code=400, detail="User already exists")
        
    return {"message": "User registered successfully", "email": created_email}

@app.post("/login", response_model=schemas.Token)
def login(user: schemas.UserLogin):
    password_hash = crud.get_user_by_email(user.email)
    
    if not password_hash or not security.verify_password(user.password, password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
        
    token = security.create_access_token({"sub": user.email})
    return {"access_token": token, "token_type": "bearer"}

@app.get("/me")
async def read_current_user(current_user: str = Depends(security.get_current_user)):
    return {"message": "You are authenticated!", "user": current_user}

@app.post("/projects")
def create_project(project: schemas.ProjectCreate, current_user: str = Depends(security.get_current_user)):
    new_project = crud.create_project_in_db(current_user, project.name, project.description)
    if not new_project:
        raise HTTPException(status_code=404, detail="Owner user not found")
    return {"message": "Project created", "project": new_project}

@app.post("/projects/{project_id}/share")
def share_project(project_id: str, member: schemas.ProjectMember, current_user: str = Depends(security.get_current_user)):
    shared_result = crud.share_project_in_db(current_user, project_id, member.target_email, member.role)
    if not shared_result:
        raise HTTPException(status_code=400, detail="Invalid project or target user")
    return {"message": "Access granted", "details": shared_result}

@app.get("/projects")
def get_projects(current_user: str = Depends(security.get_current_user)):
    user_projects = crud.get_user_projects_from_db(current_user)
    if not user_projects:
        raise HTTPException(status_code=404, detail="No projects found!")
    return {"projects": user_projects}

@app.post("/projects/{project_id}/secrets", response_model=schemas.SecretResponse)
def add_secret(project_id: str, secret: schemas.SecretCreate, current_user: str = Depends(security.get_current_user)):
    encrypted_data = crypto.encrypt_secret(secret.secret_value)
    saved_secret = crud.create_secret_in_db(current_user, project_id, secret.key_name, encrypted_data, secret.quorum_size, secret.access_window_hours, secret.max_views)
    if not saved_secret:
        raise HTTPException(status_code=403, detail="User lacks access or project doesn't exist")
    return saved_secret

@app.post("/projects/{project_id}/secrets/reveal")
def reveal_secrets(project_id: str, current_user: str = Depends(security.get_current_user)):
    encrypted_secrets = crud.get_project_secrets_from_db(current_user, project_id)
    
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
            
            plain_text = crypto.decrypt_secret(crypto_dict)
            
            decrypted_results.append({
                "id": sec["id"],
                "key_name": sec["key_name"],
                "secret_value": plain_text
            })
    except InvalidTag:
        raise HTTPException(status_code=401, detail="Invalid vault password or corrupted data")
        
    return {"secrets": decrypted_results}

@app.post("/projects/{project_id}/secrets/{secret_id}/request")
def request_secret_access(project_id: str, secret_id: str, current_user: str = Depends(security.get_current_user)):
    access_record = crud.create_access_request_in_neo4j(current_user, project_id, secret_id)
    if not access_record:
        raise HTTPException(status_code=403, detail="Unauthorized or secret not found") 
    ttl_in_seconds = access_record["access_window_hours"] * 3600  
    redis_key = f"request:{secret_id}:{current_user}:approvals"  
    redis_client.set(name=redis_key, value=0, ex=ttl_in_seconds, nx=True)  
    return {"message": "Access request initiated", "status": "pending"}

@app.post("/projects/{project_id}/secrets/{secret_id}/reject")
def reject_secret_request(project_id: str, secret_id: str, approval: schemas.ApprovalRequest, current_user: str = Depends(security.get_current_user)):
    success = crud.reject_secret_request_in_db(current_user, approval.target_email, project_id, secret_id)    
    if not success:
        raise HTTPException(status_code=403, detail="Unauthorized, or no pending request found")
    
    redis_key = f"request:{secret_id}:{approval.target_email}:approvals"
    redis_client.delete(redis_key)    
    return {
        "status": "rejected",
        "message": f"Access request from {approval.target_email} denied."
    }

@app.post("/projects/{project_id}/secrets/{secret_id}/approve")
def approve_secret_request(project_id: str, secret_id: str, approval: schemas.ApprovalRequest, current_user: str = Depends(security.get_current_user)):
    secret_data = crud.get_secret_for_approval(current_user, approval.target_email, project_id, secret_id)
    if not secret_data:
        raise HTTPException(status_code=403, detail="Unauthorized, or no pending request found")
    
    redis_key = f"request:{secret_id}:{approval.target_email}:approvals"
    if not redis_client.exists(redis_key):
        raise HTTPException(status_code=400, detail="Access request has expired or does not exist.")
        
    current_approvals = redis_client.incr(redis_key)
    
    if current_approvals >= secret_data["quorum_size"]:
        crud.mark_request_approved_in_db(approval.target_email, secret_id)
        access_token = secrets.token_urlsafe(32)
        token_key = f"vault_token:{access_token}"
        redis_client.set(name=token_key, value=secret_id, ex=3600)    
        return {
            "status": "approved",
            "message": "Quorum reached. Access token generated.",
            "access_token": access_token
        }       
    return {
        "status": "pending",
        "message": f"Approval logged. {current_approvals}/{secret_data['quorum_size']} approvals reached."
    }

@app.post("/secrets/access/{access_token}")
def access_approved_secret(access_token: str, current_user: str = Depends(security.get_current_user)):
    """
    Consumes a TTL access token from Redis to decrypt and reveal the secret.
    """
    token_key = f"vault_token:{access_token}"
    secret_id_bytes = redis_client.get(token_key)
    if not secret_id_bytes:
        raise HTTPException(status_code=403, detail="Invalid or expired access token")
    secret_id = secret_id_bytes.decode("utf-8")
    crypto_data = crud.get_secret_for_decryption(secret_id)
    if not crypto_data:
        raise HTTPException(status_code=404, detail="Secret no longer exists in database")
    crypto_dict = {
        "salt": crypto_data["salt"],
        "nonce": crypto_data["nonce"],
        "ciphertext": crypto_data["ciphertext"]
    }
    
    plaintext = crypto.decrypt_secret(crypto_dict)
    
    return {
        "message": "Access granted.",
        "secret_value": plaintext
    }