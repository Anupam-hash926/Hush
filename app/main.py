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
    saved_secret = crud.create_secret_in_db(
        current_user,
        project_id,
        secret.key_name,
        encrypted_data,
        secret.quorum_size,
        secret.access_window_hours,
        secret.max_views,
    )
    if not saved_secret:
        raise HTTPException(status_code=403, detail="User lacks access or project doesn't exist")

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
    req_data = crud.create_access_request_in_neo4j(current_user, project_id, secret_id)
    if not req_data:
        raise HTTPException(status_code=404, detail="Secret not found or access denied")

    request_id = req_data["request_id"]
    if not req_data["created"]:
        return {
            "status": req_data["status"],
            "request_id": request_id,
            "message": "An active access request already exists.",
        }

    pending_key = f"request:{request_id}:pending"
    redis_client.set(name=pending_key, value="1", ex=86400)

    crud.log_event(current_user, "ACCESS_REQUESTED", secret_id, project_id, target_email=current_user)
    return {"status": "pending", "request_id": request_id, "message": "Access request submitted and logged."}


@app.post("/projects/{project_id}/secrets/{secret_id}/reject")
def reject_secret_request(project_id: str, secret_id: str, approval: schemas.ApprovalRequest, current_user: str = Depends(security.get_current_user)):
    request_id = crud.reject_secret_request_in_db(
        current_user, approval.target_email, project_id, secret_id, approval.request_id
    )
    if not request_id:
        raise HTTPException(status_code=403, detail="Unauthorized, or no pending request found")

    pending_key = f"request:{request_id}:pending"
    approvals_key = f"approvals:{request_id}"
    redis_client.delete(pending_key, approvals_key)

    crud.log_event(current_user, "REJECTED", secret_id, project_id, target_email=approval.target_email, outcome="failure", reason="editor_rejected")
    return {
        "status": "rejected",
        "request_id": request_id,
        "message": f"Access request from {approval.target_email} denied.",
    }


@app.post("/projects/{project_id}/secrets/{secret_id}/approve")
def approve_secret_request(project_id: str, secret_id: str, approval: schemas.ApprovalRequest, current_user: str = Depends(security.get_current_user)):
    target_email = approval.target_email
    if current_user == target_email:
        crud.log_event(current_user, "APPROVAL_DENIED", secret_id, project_id, target_email, outcome="failure", reason="self_approval_attempt")
        raise HTTPException(status_code=400, detail="Cannot approve your own request")

    secret_data = crud.get_secret_for_approval(
        current_user, target_email, project_id, secret_id, approval.request_id
    )
    if not secret_data:
        crud.log_event(current_user, "APPROVAL_DENIED", secret_id, project_id, target_email, outcome="failure", reason="not_authorized_or_no_request")
        raise HTTPException(status_code=403, detail="Unauthorized, or no pending request found")

    request_id = secret_data["request_id"]
    pending_key = f"request:{request_id}:pending"
    approvals_key = f"approvals:{request_id}"

    if not redis_client.exists(pending_key):
        raise HTTPException(status_code=400, detail="Access request has expired or does not exist.")

    expiry_score = time() + approval.approval_validity_seconds
    redis_client.zadd(approvals_key, {current_user: expiry_score})

    remaining_ttl = redis_client.ttl(pending_key)
    if remaining_ttl > 0:
        redis_client.expire(approvals_key, remaining_ttl)

    live_count, quorum_reached = crud.evaluate_sorted_set_quorum(
        redis_client, request_id, secret_data["quorum_size"]
    )

    crud.log_event(current_user, "APPROVED", secret_id, project_id, target_email)

    if quorum_reached:
        now = time()
        live_members = redis_client.zrangebyscore(approvals_key, now, "+inf", withscores=True)
        min_expiry = min(score for _, score in live_members)
        claim_window_seconds = max(1, int(min_expiry - now))

        crud.mark_request_approved_in_db(request_id)
        redis_client.set(name=f"approved_window:{request_id}", value="1", ex=claim_window_seconds)
        redis_client.delete(pending_key, approvals_key)

        crud.log_event(current_user, "QUORUM_REACHED", secret_id, project_id, target_email)
        return {
            "status": "approved",
            "request_id": request_id,
            "claim_window_seconds": claim_window_seconds,
            "message": "Quorum reached. Request approved for claiming.",
        }
    return {
        "status": "pending",
        "request_id": request_id,
        "message": f"Approval logged. {live_count}/{secret_data['quorum_size']} live valid approvals.",
    }


@app.post("/projects/{project_id}/secrets/{secret_id}/claim")
def claim_approved_secret(project_id: str, secret_id: str, request_id: str | None = None, current_user: str = Depends(security.get_current_user)):
    approved_req = crud.get_approved_request_for_claim(current_user, secret_id, request_id)
    if not approved_req:
        crud.log_event(current_user, "CLAIM_DENIED", secret_id, project_id, target_email=current_user, outcome="failure", reason="quorum_not_met_or_already_claimed")
        raise HTTPException(status_code=409, detail="Request is not approved or has already been claimed.")

    req_id = approved_req["request_id"]
    window_key = f"approved_window:{req_id}"
    if not redis_client.exists(window_key):
        crud.mark_request_expired_in_db(req_id)
        crud.log_event(current_user, "CLAIM_WINDOW_EXPIRED", secret_id, project_id, target_email=current_user, outcome="failure", reason="approval_window_expired")
        raise HTTPException(
            status_code=410,
            detail="The approval window has expired — ask approvers to re-approve, or submit a new request."
        )

    claim_data = crud.mark_request_claimed_in_db(current_user, secret_id, req_id)
    if not claim_data:
        raise HTTPException(status_code=409, detail="Request could not be claimed.")

    redis_client.delete(window_key)

    access_token = secrets.token_urlsafe(32)
    payload_dict = {"secret_id": secret_id, "requester": current_user}
    token_payload = json.dumps(payload_dict)

    token_key = f"vault_token:{access_token}"
    ttl_seconds = claim_data["access_window_hours"] * 3600
    redis_client.set(name=token_key, value=token_payload, ex=ttl_seconds)

    reverse_index_key = f"active_token:{secret_id}:{current_user}"
    redis_client.set(name=reverse_index_key, value=access_token, ex=ttl_seconds)

    crud.log_event(current_user, "TOKEN_CLAIMED", secret_id, project_id, target_email=current_user)
    return {
        "message": "Access token claimed successfully.",
        "request_id": req_id,
        "access_token": access_token,
    }


@app.get("/projects/{project_id}/secrets/{secret_id}/request-status")
def get_request_status(project_id: str, secret_id: str, request_id: str | None = None, current_user: str = Depends(security.get_current_user)):
    status_data = crud.get_request_status_from_db(current_user, secret_id, request_id)
    if not status_data:
        return {"status": "none"}

    req_id = status_data["request_id"]
    response = {
        "request_id": req_id,
        "status": status_data["status"],
        "quorum_size": status_data["quorum_size"],
    }

    if status_data["status"] == "pending":
        approvals_key = f"approvals:{req_id}"
        now = time()

        redis_client.zremrangebyscore(approvals_key, 0, now)
        live_approvers = redis_client.zrange(approvals_key, 0, -1)
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
        "ciphertext": crypto_data["ciphertext"],
    }

    plaintext = crypto.decrypt_secret(crypto_dict)

    crud.log_event(current_user, "SECRET_VIEWED", secret_id, target_email=current_user)
    return {
        "message": "Access granted.",
        "views_remaining": views_remaining,
        "secret_value": plaintext,
    }


@app.post("/projects/{project_id}/secrets/{secret_id}/revoke")
def revoke_secret_access(project_id: str, secret_id: str, payload: schemas.ApprovalRequest, current_user: str = Depends(security.get_current_user)):
    target_email = payload.target_email

    revoke_result = crud.revoke_request_in_db(
        current_user, target_email, project_id, secret_id, payload.request_id
    )
    if not revoke_result:
        raise HTTPException(status_code=403, detail="Unauthorized (must be project owner) or secret not found")

    req_id = revoke_result["request_id"]
    reverse_index_key = f"active_token:{secret_id}:{target_email}"

    raw_access_token = redis_client.get(reverse_index_key)
    if raw_access_token:
        access_token = raw_access_token.decode("utf-8")
        redis_client.delete(f"vault_token:{access_token}", f"views:{access_token}")

    keys_to_delete = [reverse_index_key]
    if req_id:
        keys_to_delete.extend([
            f"request:{req_id}:pending",
            f"approvals:{req_id}",
            f"approved_window:{req_id}",
        ])
    redis_client.delete(*keys_to_delete)

    crud.log_event(current_user, "REVOKED", secret_id, project_id, target_email)
    return {
        "status": "revoked",
        "request_id": req_id,
        "message": f"All access and pending requests for {target_email} have been immediately terminated.",
    }


@app.post("/projects/{project_id}/reviewers")
def assign_reviewer(project_id: str, payload: schemas.ReviewerAssign, current_user: str = Depends(security.get_current_user)):
    success = crud.assign_reviewer_in_db(current_user, project_id, payload.target_email)
    if not success:
        raise HTTPException(status_code=403, detail="Unauthorized (must be owner) or target user not found.")

    crud.log_event(current_user, "REVIEWER_ASSIGNED", secret_id=None, project_id=project_id, target_email=payload.target_email)
    return {"message": f"{payload.target_email} is now a reviewer for this project."}


@app.get("/projects/{project_id}/secrets/{secret_id}/approvers")
def discover_eligible_approvers(project_id: str, secret_id: str, current_user: str = Depends(security.get_current_user)):
    """
    Dynamic graph discovery endpoint.
    The frontend calls this so a requester knows exactly who is allowed to approve their request.
    """
    approvers = crud.get_eligible_approvers_from_db(current_user, project_id, secret_id)
    if approvers is None:
        raise HTTPException(status_code=403, detail="Unauthorized or secret/project not found.")

    return {
        "project_id": project_id,
        "secret_id": secret_id,
        "eligible_approvers": approvers,
    }
@app.get("/approvals/inbox")
def get_approvals_inbox(current_user: str = Depends(security.get_current_user)):
    pending_requests = crud.get_approver_inbox_from_db(current_user)
    inbox = []
    for req in pending_requests:
        live_count, _ = crud.evaluate_sorted_set_quorum(
            redis_client, req["request_id"], req["quorum_size"]
        )
        req["live_approvals"] = live_count
        inbox.append(req)
    return {"inbox": inbox}

# --- STEP 7: AUDIT LOG ENDPOINT ---
@app.get("/projects/{project_id}/secrets/{secret_id}/audit")
def get_secret_audit_log(project_id: str, secret_id: str, skip: int = 0, limit: int = 50, current_user: str = Depends(security.get_current_user)):
    logs = crud.get_audit_log(current_user, project_id, secret_id, limit, skip)
    if logs is None:
        raise HTTPException(status_code=403, detail="Unauthorized (must be owner) or secret not found")
    return {"audit_log": logs}