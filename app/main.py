from fastapi import FastAPI, HTTPException, Depends
from cryptography.exceptions import InvalidTag
from app import security, schemas, crud, crypto
from app.database import redis_client
import secrets
import json

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

@app.get("/projects/{project_id}/secrets")
def list_project_secrets(project_id: str, current_user: str = Depends(security.get_current_user)):
    """
    Returns only safe metadata for a project's secrets. (Replaces /reveal)
    """
    secrets_list = crud.get_project_secrets_metadata_from_db(current_user, project_id)
    if not secrets_list:
        raise HTTPException(status_code=404, detail="No secrets found for this project")
    return {"secrets": secrets_list}

@app.post("/projects/{project_id}/secrets/{secret_id}/request")
def request_secret_access(project_id: str, secret_id: str, current_user: str = Depends(security.get_current_user)):
    access_record = crud.create_access_request_in_neo4j(current_user, project_id, secret_id)
    if not access_record:
        raise HTTPException(status_code=403, detail="Unauthorized or secret not found") 
    
    ttl_in_seconds = access_record["access_window_hours"] * 3600  
    pending_key = f"request:{secret_id}:{current_user}:pending"
    
    redis_client.set(name=pending_key, value="1", ex=ttl_in_seconds, nx=True)  
    
    return {"message": "Access request initiated", "status": "pending"}

@app.post("/projects/{project_id}/secrets/{secret_id}/reject")
def reject_secret_request(project_id: str, secret_id: str, approval: schemas.ApprovalRequest, current_user: str = Depends(security.get_current_user)):
    success = crud.reject_secret_request_in_db(current_user, approval.target_email, project_id, secret_id)    
    if not success:
        raise HTTPException(status_code=403, detail="Unauthorized, or no pending request found")
    
    pending_key = f"request:{secret_id}:{approval.target_email}:pending"
    approvers_key = f"request:{secret_id}:{approval.target_email}:approvers"
    redis_client.delete(pending_key, approvers_key)    
    
    return {
        "status": "rejected",
        "message": f"Access request from {approval.target_email} denied."
    }

@app.post("/projects/{project_id}/secrets/{secret_id}/approve")
def approve_secret_request(project_id: str, secret_id: str, approval: schemas.ApprovalRequest, current_user: str = Depends(security.get_current_user)):
    if current_user == approval.target_email:
        raise HTTPException(status_code=400, detail="Cannot approve your own request")

    secret_data = crud.get_secret_for_approval(current_user, approval.target_email, project_id, secret_id)
    if not secret_data:
        raise HTTPException(status_code=403, detail="Unauthorized, or no pending request found")
    
    pending_key = f"request:{secret_id}:{approval.target_email}:pending"
    approvers_key = f"request:{secret_id}:{approval.target_email}:approvers"
    
    if not redis_client.exists(pending_key):
        raise HTTPException(status_code=400, detail="Access request has expired or does not exist.")
        
    redis_client.sadd(approvers_key, current_user)
    
    remaining_ttl = redis_client.ttl(pending_key)
    if remaining_ttl > 0:
        redis_client.expire(approvers_key, remaining_ttl)
        
    current_approvals = redis_client.scard(approvers_key)
    
    if current_approvals >= secret_data["quorum_size"]:
        crud.mark_request_approved_in_db(approval.target_email, secret_id)
        redis_client.delete(pending_key, approvers_key)    
        return {
            "status": "approved",
            "message": "Quorum reached. Request approved for claiming."
        }       
    return {
        "status": "pending",
        "message": f"Approval logged. {current_approvals}/{secret_data['quorum_size']} unique approvals reached."
    }

@app.post("/projects/{project_id}/secrets/{secret_id}/claim")
def claim_approved_secret(project_id: str, secret_id: str, current_user: str = Depends(security.get_current_user)):
    claim_data = crud.mark_request_claimed_in_db(current_user, secret_id)
    if not claim_data:
        raise HTTPException(status_code=409, detail="Request is not approved or has already been claimed.")
    
    access_token = secrets.token_urlsafe(32)
    payload_dict = {"secret_id": secret_id, "requester": current_user}
    token_payload = json.dumps(payload_dict)
    
    token_key = f"vault_token:{access_token}"
    ttl_seconds = claim_data["access_window_hours"] * 3600
    redis_client.set(name=token_key, value=token_payload, ex=ttl_seconds)
    
    return {
        "message": "Access token claimed successfully.",
        "access_token": access_token
    }

@app.get("/projects/{project_id}/secrets/{secret_id}/request-status")
def get_request_status(project_id: str, secret_id: str, current_user: str = Depends(security.get_current_user)):
    status_data = crud.get_request_status_from_db(current_user, secret_id)
    if not status_data:
        return {"status": "none"}
        
    response = {
        "status": status_data["status"],
        "quorum_size": status_data["quorum_size"]
    }
    
    if status_data["status"] == "pending":
        approvers_key = f"request:{secret_id}:{current_user}:approvers"
        response["current_approvals"] = redis_client.scard(approvers_key)
        
    return response

@app.post("/secrets/access/{access_token}")
def access_approved_secret(access_token: str, current_user: str = Depends(security.get_current_user)):
    token_key = f"vault_token:{access_token}"
    raw_token_data = redis_client.get(token_key)
    
    if not raw_token_data:
        raise HTTPException(status_code=403, detail="Invalid, expired, or burned access token")
        
    decoded_data = raw_token_data.decode("utf-8")
    payload_dict = json.loads(decoded_data)
    
    secret_id = payload_dict.get("secret_id")
    requester_email = payload_dict.get("requester")
    
    if current_user != requester_email:
        raise HTTPException(status_code=403, detail="This access token does not belong to you")
        
    crypto_data = crud.get_secret_for_decryption(secret_id)
    if not crypto_data:
        raise HTTPException(status_code=404, detail="Secret no longer exists in database")
    
    # --- STEP 5: ATOMIC VIEW COUNTER ---
    views_key = f"views:{access_token}"
    
    # Atomically increment BEFORE decrypting so a crash doesn't give a free view
    current_views = redis_client.incr(views_key)
    
    # Sync the view counter's TTL with the token's TTL on the first view
    if current_views == 1:
        token_ttl = redis_client.ttl(token_key)
        if token_ttl > 0:
            redis_client.expire(views_key, token_ttl)
            
    max_views = crypto_data["max_views"]
    
    if current_views > max_views:
        # Burn the token and counter if they exceed the limit
        redis_client.delete(token_key, views_key)
        raise HTTPException(status_code=403, detail="Maximum view limit exceeded. Token burned.")
        
    views_remaining = max_views - current_views
    
    # If this is the last allowed view, burn the token now so it can never be used again
    if views_remaining == 0:
        redis_client.delete(token_key, views_key)
        
    # --- DECRYPTION ---
    crypto_dict = {
        "salt": crypto_data["salt"],
        "nonce": crypto_data["nonce"],
        "ciphertext": crypto_data["ciphertext"]
    }
    
    plaintext = crypto.decrypt_secret(crypto_dict)
    
    return {
        "message": "Access granted.",
        "views_remaining": views_remaining,
        "secret_value": plaintext
    }