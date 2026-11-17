from app.database import neo4j_driver
import uuid
import time

def create_user_in_db(email: str, hashed_password: str):  
    with neo4j_driver.session() as session:
        check_query = "MATCH (u:User {email: $email}) RETURN u.email AS email"
        existing = session.run(check_query, email=email).single()
        if existing:
            return None
        query = """
            MERGE (u:User {email: $email})
            ON CREATE SET u.password_hash = $password_hash
            RETURN u.email AS email
            """
        
        result = session.run(query, email=email, password_hash=hashed_password)
        record = result.single()
        return record["email"] if record else None

def get_user_by_email(email:str):
    query = """
    MATCH (u:User {email: $email})
    RETURN u.password_hash AS password_hash
    """
    with neo4j_driver.session() as session:
        result = session.run(query, email=email)
        record = result.single()
        return record["password_hash"] if record else None

def create_project_in_db(owner_email: str,name:str,description:str|None = None):
    project_id=str(uuid.uuid4())
    with neo4j_driver.session() as session:
        query = """
        MATCH (u:User {email: $owner_email})
        CREATE (p:Project {id: $project_id, name: $name, description: $description})
        CREATE (u)-[:OWNS]->(p)
        RETURN p.id AS id, p.name AS name, p.description AS description
        """
        result=session.run(query,owner_email=owner_email,project_id=project_id,name=name,description=description)
        record=result.single()
        if record:
            return{"id":record["id"],"name":record["name"],"description":record["description"],"owner":owner_email}
        else:
            return None

def share_project_in_db(owner_email:str,project_id:str,target_email:str,role:str):
    with neo4j_driver.session() as session:
        query="""
            MATCH (owner:User {email: $owner_email})-[:OWNS]->(p:Project {id:$project_id})
            MATCH (target:User {email: $target_email})
            MERGE (target)-[r:HAS_ACCESS]->(p)
            SET r.role=$role
            RETURN target.email AS shared_with, r.role AS role
            """

        result=session.run(query,owner_email=owner_email,project_id=project_id,target_email=target_email,role=role)
        record=result.single()
        if record:
            return{"shared_with":record["shared_with"],"role":record["role"]}
        else:
            return None

def get_user_projects_from_db(email:str):
    with neo4j_driver.session() as session:
        query="""
        MATCH (u:User {email:$email})-[r:OWNS|HAS_ACCESS]->(p:Project)
        RETURN p.id AS id, p.name AS name, p.description AS description, type(r) AS access_type
        """
        result=session.run(query,email=email)
        projects=result.data()
        return projects

def create_secret_in_db(email: str, project_id: str, key_name: str, encrypted_data: dict,quorum_size:int,access_window_hours:int,max_views:int):
    with neo4j_driver.session() as session:
        query = """
        MATCH (u:User {email: $email})-[r:OWNS|HAS_ACCESS]->(p:Project {id: $project_id})
        WHERE type(r) = 'OWNS' OR r.role = 'editor'
        CREATE (s:Secret {
            id: randomUUID(),
            key_name: $key_name,
            salt: $salt,
            nonce: $nonce,
            ciphertext: $ciphertext,
            quorum_size:$quorum_size,
            access_window_hours: $access_window_hours,
            max_views: $max_views
        })
        CREATE (p)-[:CONTAINS]->(s)
        RETURN s.id AS id, s.key_name AS key_name
        """    
        result = session.run(query,email=email,project_id=project_id,key_name=key_name,salt=encrypted_data["salt"],nonce=encrypted_data["nonce"],ciphertext=encrypted_data["ciphertext"],
                             quorum_size=quorum_size,access_window_hours=access_window_hours,max_views=max_views)
        record = result.single()
        if not record:
            return None
        return {"id":record["id"],"key_name":record["key_name"]}

def get_project_secrets_metadata_from_db(email: str, project_id: str):
    with neo4j_driver.session() as session:
        query = """
        MATCH (u:User {email: $email})-[r:OWNS|HAS_ACCESS]->(p:Project {id: $project_id})-[:CONTAINS]->(s:Secret)
        RETURN s.id AS id, s.key_name AS key_name, s.quorum_size AS quorum_size, 
               s.access_window_hours AS access_window_hours, s.max_views AS max_views
        """
        result = session.run(query, email=email, project_id=project_id)
        return result.data()

def create_access_request_in_neo4j(email: str, project_id: str, secret_id: str) -> str | None:
    """
    Creates a dedicated AccessRequest node to maintain a permanent history.
    """
    request_id = str(uuid.uuid4())
    with neo4j_driver.session() as session:
        query = """
        MATCH (u:User {email: $email})-[r:HAS_ACCESS|OWNS]->(p:Project {id: $project_id})-[:CONTAINS]->(s:Secret {id: $secret_id})
        CREATE (u)-[:MADE]->(req:AccessRequest {
            id: $request_id, 
            status: 'pending', 
            created_at: datetime()
        })-[:FOR]->(s)
        RETURN req.id AS request_id
        """
        result = session.run(
            query, 
            email=email, 
            project_id=project_id, 
            secret_id=secret_id, 
            request_id=request_id
        ).single()
        
        return result["request_id"] if result else None

def get_secret_for_approval(editor_email: str, target_email: str, project_id: str, secret_id: str) -> dict | None:
    with neo4j_driver.session() as session:
        query = """
        MATCH (editor:User {email: $editor_email})-[r1:OWNS|HAS_ACCESS|REVIEWER_OF]->(p:Project {id: $project_id})-[:CONTAINS]->(s:Secret {id: $secret_id})
        WHERE type(r1) IN ['OWNS', 'REVIEWER_OF'] OR r1.role = 'editor'
        MATCH (target:User {email: $target_email})-[:MADE]->(req:AccessRequest)-[:FOR]->(s)
        WHERE req.status = 'pending'
        RETURN s.quorum_size AS quorum_size, s.salt AS salt, s.nonce AS nonce, s.ciphertext AS ciphertext
        """
        result = session.run(query, editor_email=editor_email, target_email=target_email, project_id=project_id, secret_id=secret_id).single()
        return result.data() if result else None

def reject_secret_request_in_db(editor_email: str, target_email: str, project_id: str, secret_id: str) -> bool:
    with neo4j_driver.session() as session:
        query = """
        MATCH (editor:User {email: $editor_email})-[r1:OWNS|HAS_ACCESS|REVIEWER_OF]->(p:Project {id: $project_id})-[:CONTAINS]->(s:Secret {id: $secret_id})
        WHERE type(r1) IN ['OWNS', 'REVIEWER_OF'] OR r1.role = 'editor'
        MATCH (target:User {email: $target_email})-[:MADE]->(req:AccessRequest)-[:FOR]->(s)
        WHERE req.status = 'pending'
        SET req.status = 'rejected'
        RETURN req
        """
        result = session.run(query, editor_email=editor_email, target_email=target_email, project_id=project_id, secret_id=secret_id).single()
        return bool(result)

def mark_request_approved_in_db(target_email: str, secret_id: str) -> bool:
    with neo4j_driver.session() as session:
        query = """
        MATCH (target:User {email: $target_email})-[:MADE]->(req:AccessRequest)-[:FOR]->(s:Secret {id: $secret_id})
        WHERE req.status = 'pending'
        SET req.status = 'approved'
        RETURN req
        """
        result = session.run(query, target_email=target_email, secret_id=secret_id).single()
        return bool(result)

def mark_request_claimed_in_db(requester_email: str, secret_id: str) -> dict | None:
    with neo4j_driver.session() as session:
        query = """
        MATCH (target:User {email: $requester_email})-[:MADE]->(req:AccessRequest)-[:FOR]->(s:Secret {id: $secret_id})
        WHERE req.status = 'approved'
        SET req.status = 'claimed'
        RETURN s.access_window_hours AS access_window_hours
        """
        result = session.run(query, requester_email=requester_email, secret_id=secret_id).single()
        return result.data() if result else None

def get_request_status_from_db(requester_email: str, secret_id: str) -> dict | None:
    with neo4j_driver.session() as session:
        query = """
         MATCH (target:User {email: $requester_email})-[:MADE]->(req:AccessRequest)-[:FOR]->(s:Secret {id: $secret_id})
         RETURN req.status AS status, s.quorum_size AS quorum_size
        """
        result = session.run(query, requester_email=requester_email, secret_id=secret_id).single()
        return result.data() if result else None   

def get_secret_for_decryption(secret_id: str) -> dict | None:
    """Fetches the raw cryptography data and view limits for a secret."""
    with neo4j_driver.session() as session:
        query = """
        MATCH (s:Secret {id: $secret_id})
        RETURN s.salt AS salt, s.nonce AS nonce, s.ciphertext AS ciphertext, s.max_views AS max_views
        """
        result = session.run(query, secret_id=secret_id).single()
        return result.data() if result else None

def revoke_request_in_db(owner_email: str, target_email: str, project_id: str, secret_id: str) -> bool:
    """
    Targets the AccessRequest node instead of the old relationship edge.
    """
    with neo4j_driver.session() as session:
        query = """
        MATCH (owner:User {email: $owner_email})-[r1:OWNS]->(p:Project {id: $project_id})-[:CONTAINS]->(s:Secret {id: $secret_id})
        MATCH (target:User {email: $target_email})-[:MADE]->(req:AccessRequest)-[:FOR]->(s)
        SET req.status = 'revoked'
        RETURN req
        """
        result = session.run(query, owner_email=owner_email, target_email=target_email, project_id=project_id, secret_id=secret_id).single()
        return bool(result)

def log_event(actor_email: str, event_type: str, secret_id: str, project_id: str = None, target_email: str = None, outcome: str = "success", reason: str = None):
    """
    Creates an immutable AuditEvent node linked to the Actor and the Secret.
    """
    event_id = str(uuid.uuid4())
    with neo4j_driver.session() as session:
        query = """
        MATCH (actor:User {email: $actor_email})
        MATCH (s:Secret {id: $secret_id})
        """
        # Optionally link the project if provided
        if project_id:
            query += "<-[:CONTAINS]-(p:Project {id: $project_id}) "
            
        query += """
        CREATE (actor)-[:PERFORMED]->(e:AuditEvent {
            id: $event_id, 
            type: $event_type, 
            target: $target_email,
            timestamp: datetime(), 
            outcome: $outcome, 
            reason: $reason
        })-[:ABOUT]->(s)
        """
        # FIX: project_id added to session.run parameters
        session.run(
            query, 
            actor_email=actor_email, 
            event_type=event_type, 
            secret_id=secret_id, 
            project_id=project_id, 
            target_email=target_email, 
            event_id=event_id, 
            outcome=outcome, 
            reason=reason
        )

def get_audit_log(owner_email: str, project_id: str, secret_id: str, limit: int = 50, skip: int = 0):
    with neo4j_driver.session() as session:
        query = """
        MATCH (owner:User {email: $owner_email})-[r1:OWNS]->(p:Project {id: $project_id})-[:CONTAINS]->(s:Secret {id: $secret_id})
        MATCH (actor:User)-[:PERFORMED]->(e:AuditEvent)-[:ABOUT]->(s)
        RETURN e.id AS id, actor.email AS actor, e.type AS type, e.target AS target, 
               toString(e.timestamp) AS timestamp, e.outcome AS outcome, e.reason AS reason
        ORDER BY e.timestamp DESC
        SKIP $skip LIMIT $limit
        """
        return session.run(query, owner_email=owner_email, project_id=project_id, secret_id=secret_id, limit=limit, skip=skip).data()

def assign_reviewer_in_db(owner_email: str, project_id: str, target_email: str) -> bool:
    """Creates a dedicated REVIEWER_OF relationship for a user."""
    with neo4j_driver.session() as session:
        query = """
        MATCH (owner:User {email: $owner_email})-[:OWNS]->(p:Project {id: $project_id})
        MATCH (target:User {email: $target_email})
        MERGE (target)-[r:REVIEWER_OF]->(p)
        RETURN target
        """
        result = session.run(query, owner_email=owner_email, project_id=project_id, target_email=target_email).single()
        return bool(result)

def get_eligible_approvers_from_db(project_id: str) -> list[str]:
    """Graph traversal to discover all users dynamically authorized to approve requests."""
    with neo4j_driver.session() as session:
        query = """
        MATCH (u:User)-[r:OWNS|HAS_ACCESS|REVIEWER_OF]->(p:Project {id: $project_id})
        WHERE type(r) IN ['OWNS', 'REVIEWER_OF'] OR r.role = 'editor'
        RETURN collect(DISTINCT u.email) as approvers
        """
        result = session.run(query, project_id=project_id).single()
        return result["approvers"] if result else []

def evaluate_sorted_set_quorum(redis_client, secret_id: str, requester_email: str, quorum_size: int) -> tuple[int, bool]:
    """
    Cleans expired approvals using Redis ZREMRANGEBYSCORE and counts live ones using ZCOUNT.
    Returns (current_live_approvals, quorum_reached_boolean).
    """
    approvals_key = f"approvals:{secret_id}:{requester_email}"
    now = time.time()
    
    # 1. Remove expired approvals from the sorted set
    redis_client.zremrangebyscore(approvals_key, 0, now)
    
    # 2. Count remaining valid approvals (scores from 'now' to infinity)
    live_count = redis_client.zcount(approvals_key, now, "+inf")
    
    return live_count, live_count >= quorum_size