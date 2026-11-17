from fastapi import FastAPI, HTTPException, Depends
from cryptography.exceptions import InvalidTag
from app import security, schemas, crud, crypto
from app.database import redis_client
import secrets
import json
from time import time

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
    
    # Audit log for secret creation
    crud.log_event(current_user, "SECRET_CREATED", saved_secret["id"], project_id)
    return saved_secret

@app.get("/projects/{project_id}/secrets")
def list_project_secrets(project_id: str, current_user: str = Depends(security.get_current_user)):
    """
    Returns only safe metadata for a project's secrets.
    """
    secrets_list = crud.get_project_secrets_metadata_from_db(current_user, project_id)
    if not secrets_list:
        raise HTTPException(status_code=404, detail="No secrets found for this project")
    return {"secrets": secrets_list}

@app.post("/projects/{project_id}/secrets/{secret_id}/request")
def request_secret_access(project_id: str, secret_id: str, current_user: str = Depends(security.get_current_user)):
    request_id = crud.create_access_request_in_neo4j(current_user, project_id, secret_id)
    if not request_id:
        raise HTTPException(status_code=404, detail="Secret not found or access denied")
        
    pending_key = f"request:{secret_id}:{current_user}:pending"
    redis_client.set(name=pending_key, value="1", ex=86400)
    
    # Step 7: Log the event
    crud.log_event(current_user, "ACCESS_REQUESTED", secret_id, project_id, target_email=current_user)
    return {"status": "pending", "request_id": request_id, "message": "Access request submitted and logged."}

@app.post("/projects/{project_id}/secrets/{secret_id}/reject")
def reject_secret_request(project_id: str, secret_id: str, approval: schemas.ApprovalRequest, current_user: str = Depends(security.get_current_user)):
    success = crud.reject_secret_request_in_db(current_user, approval.target_email, project_id, secret_id)    
    if not success:
        raise HTTPException(status_code=403, detail="Unauthorized, or no pending request found")
    
    pending_key = f"request:{secret_id}:{approval.target_email}:pending"
    approvers_key = f"request:{secret_id}:{approval.target_email}:approvers"
    redis_client.delete(pending_key, approvers_key)    
    
    # Step 7: Log the event with outcome="failure"
    crud.log_event(current_user, "REJECTED", secret_id, project_id, target_email=approval.target_email, outcome="failure", reason="editor_rejected")
    return {
        "status": "rejected",
        "message": f"Access request from {approval.target_email} denied."
    }

@app.post("/projects/{project_id}/secrets/{secret_id}/approve")
def approve_secret_request(project_id: str, secret_id: str, approval: schemas.ApprovalRequest, current_user: str = Depends(security.get_current_user)):
    target_email = approval.target_email
    if current_user == target_email:
        crud.log_event(current_user, "REJECTED", secret_id, project_id, target_email, outcome="failure", reason="self_approval_attempt")
        raise HTTPException(status_code=400, detail="Cannot approve your own request")

    secret_data = crud.get_secret_for_approval(current_user, target_email, project_id, secret_id)
    if not secret_data:
        raise HTTPException(status_code=403, detail="Unauthorized, or no pending request found")
    
    pending_key = f"request:{secret_id}:{target_email}:pending"
    # Note the key name change to 'approvals' to match the sorted set convention
    approvals_key = f"approvals:{secret_id}:{target_email}"
    
    if not redis_client.exists(pending_key):
        raise HTTPException(status_code=400, detail="Access request has expired or does not exist.")
    
    # --- STEP 9: APPROVER-DEFINED EXPIRY (Sorted Sets) ---
    expiry_score = time() + approval.approval_validity_seconds
    
    # SADD is replaced with ZADD
    redis_client.zadd(approvals_key, {current_user: expiry_score})
    
    remaining_ttl = redis_client.ttl(pending_key)
    if remaining_ttl > 0:
        redis_client.expire(approvals_key, remaining_ttl)
        
    # SCARD is replaced with your new live-counting helper
    live_count, quorum_reached = crud.evaluate_sorted_set_quorum(
        redis_client, secret_id, target_email, secret_data["quorum_size"]
    )
    
    crud.log_event(current_user, "APPROVED", secret_id, project_id, target_email)
    
    if quorum_reached:
        crud.mark_request_approved_in_db(target_email, secret_id)
        redis_client.delete(pending_key, approvals_key)
        
        crud.log_event(current_user, "QUORUM_REACHED", secret_id, project_id, target_email)
        return {
            "status": "approved",
            "message": "Quorum reached. Request approved for claiming."
        }       
    return {
        "status": "pending",
        "message": f"Approval logged. {live_count}/{secret_data['quorum_size']} live valid approvals."
    }

@app.post("/projects/{project_id}/secrets/{secret_id}/claim")
def claim_approved_secret(project_id: str, secret_id: str, current_user: str = Depends(security.get_current_user)):
    claim_data = crud.mark_request_claimed_in_db(current_user, secret_id)
    if not claim_data:
        crud.log_event(current_user, "REJECTED", secret_id, project_id, target_email=current_user, outcome="failure", reason="quorum_not_met_or_already_claimed")
        raise HTTPException(status_code=409, detail="Request is not approved or has already been claimed.")
    
    access_token = secrets.token_urlsafe(32)
    payload_dict = {"secret_id": secret_id, "requester": current_user}
    token_payload = json.dumps(payload_dict)
    
    token_key = f"vault_token:{access_token}"
    ttl_seconds = claim_data["access_window_hours"] * 3600
    redis_client.set(name=token_key, value=token_payload, ex=ttl_seconds)

    reverse_index_key = f"active_token:{secret_id}:{current_user}"
    redis_client.set(name=reverse_index_key, value=access_token, ex=ttl_seconds)
    
    # Step 7: Log the claim
    crud.log_event(current_user, "TOKEN_CLAIMED", secret_id, project_id, target_email=current_user)
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
        # STEP 9: Read from the new Sorted Set
        approvals_key = f"approvals:{secret_id}:{current_user}"
        now = time()
        
        # Clean expired ones dynamically on read
        redis_client.zremrangebyscore(approvals_key, 0, now)
        
        # Fetch remaining valid members
        live_approvers = redis_client.zrange(approvals_key, 0, -1)
        
        # Decode bytes to strings if necessary
        decoded_approvers = [a.decode("utf-8") if isinstance(a, bytes) else a for a in live_approvers]
        
        response["current_live_approvals"] = len(decoded_approvers)
        response["live_approvers"] = decoded_approvers
        
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
        crud.log_event(current_user, "VIEW_DENIED", secret_id, outcome="failure", reason="wrong_user")
        raise HTTPException(status_code=403, detail="This access token does not belong to you")
        
    crypto_data = crud.get_secret_for_decryption(secret_id)
    if not crypto_data:
        crud.log_event(current_user, "VIEW_DENIED", secret_id, outcome="failure", reason="secret_not_found_in_db")
        raise HTTPException(status_code=404, detail="Secret no longer exists in database")
    
    # ATOMIC VIEW COUNTER
    views_key = f"views:{access_token}"
    current_views = redis_client.incr(views_key)
    
    if current_views == 1:
        token_ttl = redis_client.ttl(token_key)
        if token_ttl > 0:
            redis_client.expire(views_key, token_ttl)
            
    max_views = crypto_data["max_views"]
    
    if current_views > max_views:
        redis_client.delete(token_key, views_key)
        crud.log_event(current_user, "VIEW_DENIED", secret_id, outcome="failure", reason="limit_reached")
        raise HTTPException(status_code=403, detail="Maximum view limit exceeded. Token burned.")
        
    views_remaining = max_views - current_views
    
    if views_remaining == 0:
        redis_client.delete(token_key, views_key)
        
    crypto_dict = {
        "salt": crypto_data["salt"],
        "nonce": crypto_data["nonce"],
        "ciphertext": crypto_data["ciphertext"]
    }
    
    plaintext = crypto.decrypt_secret(crypto_dict)
    
    # Step 7: Log successful view
    crud.log_event(current_user, "SECRET_VIEWED", secret_id, target_email=current_user)
    return {
        "message": "Access granted.",
        "views_remaining": views_remaining,
        "secret_value": plaintext
    }

@app.post("/projects/{project_id}/secrets/{secret_id}/revoke")
def revoke_secret_access(project_id: str, secret_id: str, payload: schemas.ApprovalRequest, current_user: str = Depends(security.get_current_user)):
    target_email = payload.target_email
    
    success = crud.revoke_request_in_db(current_user, target_email, project_id, secret_id)
    if not success:
        raise HTTPException(status_code=403, detail="Unauthorized (must be project owner) or request not found")
        
    pending_key = f"request:{secret_id}:{target_email}:pending"
    approvers_key = f"request:{secret_id}:{target_email}:approvers"
    reverse_index_key = f"active_token:{secret_id}:{target_email}"
    
    raw_access_token = redis_client.get(reverse_index_key)
    if raw_access_token:
        access_token = raw_access_token.decode("utf-8")
        redis_client.delete(f"vault_token:{access_token}", f"views:{access_token}")
        
    redis_client.delete(pending_key, approvers_key, reverse_index_key)
    
    # Step 7: Log immediate revocation
    crud.log_event(current_user, "REVOKED", secret_id, project_id, target_email)
    return {
        "status": "revoked",
        "message": f"All access and pending requests for {target_email} have been immediately terminated."
    }

@app.post("/projects/{project_id}/reviewers")
def assign_reviewer(project_id: str, payload: schemas.ReviewerAssign, current_user: str = Depends(security.get_current_user)):
    success = crud.assign_reviewer_in_db(current_user, project_id, payload.target_email)
    if not success:
        raise HTTPException(status_code=403, detail="Unauthorized (must be owner) or target user not found.")
    
    crud.log_event(current_user, "REVIEWER_ASSIGNED", secret_id="N/A", project_id=project_id, target_email=payload.target_email)
    return {"message": f"{payload.target_email} is now a reviewer for this project."}

@app.get("/projects/{project_id}/secrets/{secret_id}/approvers")
def discover_eligible_approvers(project_id: str, secret_id: str, current_user: str = Depends(security.get_current_user)):
    """
    Dynamic graph discovery endpoint. 
    The frontend calls this so a requester knows exactly who is allowed to approve their request.
    """
    approvers = crud.get_eligible_approvers_from_db(project_id)
    if not approvers:
        raise HTTPException(status_code=404, detail="Project not found or no approvers available.")
        
    return {
        "project_id": project_id,
        "eligible_approvers": approvers
    }

# --- STEP 7: AUDIT LOG ENDPOINT ---
@app.get("/projects/{project_id}/secrets/{secret_id}/audit")
def get_secret_audit_log(project_id: str, secret_id: str, skip: int = 0, limit: int = 50, current_user: str = Depends(security.get_current_user)):
    logs = crud.get_audit_log(current_user, project_id, secret_id, limit, skip)
    if logs is None:
         raise HTTPException(status_code=403, detail="Unauthorized (must be owner) or secret not found")
    return {"audit_log": logs}