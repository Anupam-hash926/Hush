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


def get_user_by_email(email: str):
    query = """
    MATCH (u:User {email: $email})
    RETURN u.password_hash AS password_hash
    """
    with neo4j_driver.session() as session:
        result = session.run(query, email=email)
        record = result.single()
        return record["password_hash"] if record else None


def create_project_in_db(owner_email: str, name: str, description: str | None = None):
    project_id = str(uuid.uuid4())
    with neo4j_driver.session() as session:
        query = """
        MATCH (u:User {email: $owner_email})
        CREATE (p:Project {id: $project_id, name: $name, description: $description})
        CREATE (u)-[:OWNS]->(p)
        RETURN p.id AS id, p.name AS name, p.description AS description
        """
        result = session.run(
            query,
            owner_email=owner_email,
            project_id=project_id,
            name=name,
            description=description,
        )
        record = result.single()
        if record:
            return {
                "id": record["id"],
                "name": record["name"],
                "description": record["description"],
                "owner": owner_email,
            }
        else:
            return None


def share_project_in_db(owner_email: str, project_id: str, target_email: str, role: str):
    with neo4j_driver.session() as session:
        query = """
            MATCH (owner:User {email: $owner_email})-[:OWNS]->(p:Project {id:$project_id})
            MATCH (target:User {email: $target_email})
            MERGE (target)-[r:HAS_ACCESS]->(p)
            SET r.role=$role
            RETURN target.email AS shared_with, r.role AS role
            """

        result = session.run(
            query,
            owner_email=owner_email,
            project_id=project_id,
            target_email=target_email,
            role=role,
        )
        record = result.single()
        if record:
            return {"shared_with": record["shared_with"], "role": record["role"]}
        else:
            return None


def get_user_projects_from_db(email: str):
    with neo4j_driver.session() as session:
        query = """
        MATCH (u:User {email:$email})-[r:OWNS|HAS_ACCESS]->(p:Project)
        RETURN p.id AS id, p.name AS name, p.description AS description, type(r) AS access_type, r.role AS role
        """
        result = session.run(query, email=email)
        projects = result.data()
        return projects


def create_secret_in_db(
    email: str,
    project_id: str,
    key_name: str,
    encrypted_data: dict,
    quorum_size: int,
    access_window_hours: int,
    max_views: int,
):
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
            quorum_size: $quorum_size,
            access_window_hours: $access_window_hours,
            max_views: $max_views
        })
        CREATE (p)-[:CONTAINS]->(s)
        RETURN s.id AS id, s.key_name AS key_name
        """
        result = session.run(
            query,
            email=email,
            project_id=project_id,
            key_name=key_name,
            salt=encrypted_data["salt"],
            nonce=encrypted_data["nonce"],
            ciphertext=encrypted_data["ciphertext"],
            quorum_size=quorum_size,
            access_window_hours=access_window_hours,
            max_views=max_views,
        )
        record = result.single()
        if not record:
            return None
        return {"id": record["id"], "key_name": record["key_name"]}


def get_project_secrets_metadata_from_db(email: str, project_id: str):
    with neo4j_driver.session() as session:
        query = """
        MATCH (u:User {email: $email})-[r:OWNS|HAS_ACCESS]->(p:Project {id: $project_id})-[:CONTAINS]->(s:Secret)
        RETURN s.id AS id, s.key_name AS key_name, s.quorum_size AS quorum_size, 
               s.access_window_hours AS access_window_hours, s.max_views AS max_views
        """
        result = session.run(query, email=email, project_id=project_id)
        return result.data()


def create_access_request_in_neo4j(email: str, project_id: str, secret_id: str) -> dict | None:
    """
    Returns an existing pending/approved request if one exists (preventing duplicates),
    otherwise creates a new AccessRequest node.
    """
    with neo4j_driver.session() as session:
        existing_query = """
        MATCH (u:User {email: $email})-[:HAS_ACCESS|OWNS]->(p:Project {id: $project_id})-[:CONTAINS]->(s:Secret {id: $secret_id})
        MATCH (u)-[:MADE]->(req:AccessRequest)-[:FOR]->(s)
        WHERE req.status IN ['pending', 'approved']
        RETURN req.id AS request_id, req.status AS status
        ORDER BY req.created_at DESC
        LIMIT 1
        """
        existing = session.run(
            existing_query, email=email, project_id=project_id, secret_id=secret_id
        ).single()
        if existing:
            return {
                "request_id": existing["request_id"],
                "status": existing["status"],
                "created": False,
            }

        request_id = str(uuid.uuid4())
        create_query = """
        MATCH (u:User {email: $email})-[r:HAS_ACCESS|OWNS]->(p:Project {id: $project_id})-[:CONTAINS]->(s:Secret {id: $secret_id})
        CREATE (u)-[:MADE]->(req:AccessRequest {
            id: $request_id, 
            status: 'pending', 
            created_at: datetime()
        })-[:FOR]->(s)
        RETURN req.id AS request_id, req.status AS status
        """
        result = session.run(
            create_query,
            email=email,
            project_id=project_id,
            secret_id=secret_id,
            request_id=request_id,
        ).single()

        if not result:
            return None
        return {
            "request_id": result["request_id"],
            "status": result["status"],
            "created": True,
        }


def get_secret_for_approval(
    editor_email: str,
    target_email: str,
    project_id: str,
    secret_id: str,
    request_id: str | None = None,
) -> dict | None:
    with neo4j_driver.session() as session:
        query = """
        MATCH (editor:User {email: $editor_email})-[r1:OWNS|HAS_ACCESS|REVIEWER_OF]->(p:Project {id: $project_id})-[:CONTAINS]->(s:Secret {id: $secret_id})
        WHERE type(r1) IN ['OWNS', 'REVIEWER_OF'] OR r1.role = 'editor'
        MATCH (target:User {email: $target_email})-[:MADE]->(req:AccessRequest)-[:FOR]->(s)
        WHERE req.status = 'pending' AND ($request_id IS NULL OR req.id = $request_id)
        RETURN req.id AS request_id, s.quorum_size AS quorum_size, s.salt AS salt, s.nonce AS nonce, s.ciphertext AS ciphertext
        ORDER BY req.created_at DESC
        LIMIT 1
        """
        result = session.run(
            query,
            editor_email=editor_email,
            target_email=target_email,
            project_id=project_id,
            secret_id=secret_id,
            request_id=request_id,
        ).single()
        return result.data() if result else None


def reject_secret_request_in_db(
    editor_email: str,
    target_email: str,
    project_id: str,
    secret_id: str,
    request_id: str | None = None,
) -> str | None:
    """Rejects the matching pending request and returns its request_id."""
    with neo4j_driver.session() as session:
        query = """
        MATCH (editor:User {email: $editor_email})-[r1:OWNS|HAS_ACCESS|REVIEWER_OF]->(p:Project {id: $project_id})-[:CONTAINS]->(s:Secret {id: $secret_id})
        WHERE type(r1) IN ['OWNS', 'REVIEWER_OF'] OR r1.role = 'editor'
        MATCH (target:User {email: $target_email})-[:MADE]->(req:AccessRequest)-[:FOR]->(s)
        WHERE req.status = 'pending' AND ($request_id IS NULL OR req.id = $request_id)
        WITH req ORDER BY req.created_at DESC LIMIT 1
        SET req.status = 'rejected'
        RETURN req.id AS request_id
        """
        result = session.run(
            query,
            editor_email=editor_email,
            target_email=target_email,
            project_id=project_id,
            secret_id=secret_id,
            request_id=request_id,
        ).single()
        return result["request_id"] if result else None


def mark_request_approved_in_db(request_id: str) -> bool:
    with neo4j_driver.session() as session:
        query = """
        MATCH (req:AccessRequest {id: $request_id})
        WHERE req.status = 'pending'
        SET req.status = 'approved'
        RETURN req
        """
        result = session.run(query, request_id=request_id).single()
        return bool(result)


def get_approved_request_for_claim(
    requester_email: str, secret_id: str, request_id: str | None = None
) -> dict | None:
    """Fetches the latest approved request without mutating its status yet."""
    with neo4j_driver.session() as session:
        query = """
        MATCH (target:User {email: $requester_email})-[:MADE]->(req:AccessRequest)-[:FOR]->(s:Secret {id: $secret_id})
        WHERE req.status = 'approved' AND ($request_id IS NULL OR req.id = $request_id)
        RETURN req.id AS request_id, s.access_window_hours AS access_window_hours
        ORDER BY req.created_at DESC
        LIMIT 1
        """
        result = session.run(
            query,
            requester_email=requester_email,
            secret_id=secret_id,
            request_id=request_id,
        ).single()
        return result.data() if result else None


def mark_request_expired_in_db(request_id: str) -> bool:
    """Lazily transitions an approved request to expired once its claim window lapses."""
    with neo4j_driver.session() as session:
        query = """
        MATCH (req:AccessRequest {id: $request_id})
        WHERE req.status = 'approved'
        SET req.status = 'expired'
        RETURN req
        """
        result = session.run(query, request_id=request_id).single()
        return bool(result)


def mark_request_claimed_in_db(
    requester_email: str, secret_id: str, request_id: str | None = None
) -> dict | None:
    with neo4j_driver.session() as session:
        query = """
        MATCH (target:User {email: $requester_email})-[:MADE]->(req:AccessRequest)-[:FOR]->(s:Secret {id: $secret_id})
        WHERE req.status = 'approved' AND ($request_id IS NULL OR req.id = $request_id)
        WITH req, s ORDER BY req.created_at DESC LIMIT 1
        SET req.status = 'claimed'
        RETURN req.id AS request_id, s.access_window_hours AS access_window_hours
        """
        result = session.run(
            query,
            requester_email=requester_email,
            secret_id=secret_id,
            request_id=request_id,
        ).single()
        return result.data() if result else None


def get_request_status_from_db(
    requester_email: str, secret_id: str, request_id: str | None = None
) -> dict | None:
    with neo4j_driver.session() as session:
        query = """
        MATCH (target:User {email: $requester_email})-[:MADE]->(req:AccessRequest)-[:FOR]->(s:Secret {id: $secret_id})
        WHERE $request_id IS NULL OR req.id = $request_id
        RETURN req.id AS request_id, req.status AS status, s.quorum_size AS quorum_size
        ORDER BY req.created_at DESC
        LIMIT 1
        """
        result = session.run(
            query,
            requester_email=requester_email,
            secret_id=secret_id,
            request_id=request_id,
        ).single()
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


def revoke_request_in_db(
    owner_email: str,
    target_email: str,
    project_id: str,
    secret_id: str,
    request_id: str | None = None,
) -> dict | None:
    """
    Revokes the active request (pending/approved/claimed) and returns its request_id.
    Returns None if caller is not the project owner or secret doesn't exist.
    """
    with neo4j_driver.session() as session:
        query = """
        MATCH (owner:User {email: $owner_email})-[:OWNS]->(p:Project {id: $project_id})-[:CONTAINS]->(s:Secret {id: $secret_id})
        OPTIONAL MATCH (target:User {email: $target_email})-[:MADE]->(req:AccessRequest)-[:FOR]->(s)
        WHERE req.status IN ['pending', 'approved', 'claimed'] AND ($request_id IS NULL OR req.id = $request_id)
        WITH req ORDER BY req.created_at DESC LIMIT 1
        FOREACH (_ IN CASE WHEN req IS NOT NULL THEN [1] ELSE [] END | SET req.status = 'revoked')
        RETURN true AS authorized, req.id AS request_id
        """
        result = session.run(
            query,
            owner_email=owner_email,
            target_email=target_email,
            project_id=project_id,
            secret_id=secret_id,
            request_id=request_id,
        ).single()
        return result.data() if result else None


def log_event(
    actor_email: str,
    event_type: str,
    secret_id: str | None = None,
    project_id: str | None = None,
    target_email: str | None = None,
    outcome: str = "success",
    reason: str | None = None,
):
    """
    Creates an immutable AuditEvent node linked to the Actor and optionally Secret/Project.
    """
    event_id = str(uuid.uuid4())
    with neo4j_driver.session() as session:
        if secret_id and project_id:
            query = """
            MATCH (actor:User {email: $actor_email})
            MATCH (p:Project {id: $project_id})-[:CONTAINS]->(s:Secret {id: $secret_id})
            CREATE (actor)-[:PERFORMED]->(e:AuditEvent {
                id: $event_id,
                type: $event_type,
                target: $target_email,
                timestamp: datetime(),
                outcome: $outcome,
                reason: $reason
            })-[:ABOUT]->(s)
            """
        elif secret_id:
            query = """
            MATCH (actor:User {email: $actor_email})
            MATCH (s:Secret {id: $secret_id})
            CREATE (actor)-[:PERFORMED]->(e:AuditEvent {
                id: $event_id,
                type: $event_type,
                target: $target_email,
                timestamp: datetime(),
                outcome: $outcome,
                reason: $reason
            })-[:ABOUT]->(s)
            """
        elif project_id:
            query = """
            MATCH (actor:User {email: $actor_email})
            MATCH (p:Project {id: $project_id})
            CREATE (actor)-[:PERFORMED]->(e:AuditEvent {
                id: $event_id,
                type: $event_type,
                target: $target_email,
                timestamp: datetime(),
                outcome: $outcome,
                reason: $reason
            })-[:ABOUT]->(p)
            """
        else:
            query = """
            MATCH (actor:User {email: $actor_email})
            CREATE (actor)-[:PERFORMED]->(e:AuditEvent {
                id: $event_id,
                type: $event_type,
                target: $target_email,
                timestamp: datetime(),
                outcome: $outcome,
                reason: $reason
            })
            """

        session.run(
            query,
            actor_email=actor_email,
            event_type=event_type,
            secret_id=secret_id,
            project_id=project_id,
            target_email=target_email,
            event_id=event_id,
            outcome=outcome,
            reason=reason,
        )


def get_audit_log(
    owner_email: str, project_id: str, secret_id: str, limit: int = 50, skip: int = 0
) -> list[dict] | None:
    with neo4j_driver.session() as session:
        auth_query = """
        MATCH (owner:User {email: $owner_email})-[:OWNS]->(p:Project {id: $project_id})-[:CONTAINS]->(s:Secret {id: $secret_id})
        RETURN s.id AS secret_id
        """
        authorized = session.run(
            auth_query,
            owner_email=owner_email,
            project_id=project_id,
            secret_id=secret_id,
        ).single()
        if not authorized:
            return None

        query = """
        MATCH (s:Secret {id: $secret_id})<-[:ABOUT]-(e:AuditEvent)<-[:PERFORMED]-(actor:User)
        RETURN e.id AS id, actor.email AS actor, e.type AS type, e.target AS target,
               toString(e.timestamp) AS timestamp, e.outcome AS outcome, e.reason AS reason
        ORDER BY e.timestamp DESC
        SKIP $skip LIMIT $limit
        """
        return session.run(
            query,
            secret_id=secret_id,
            limit=limit,
            skip=skip,
        ).data()


def assign_reviewer_in_db(owner_email: str, project_id: str, target_email: str) -> bool:
    """Creates a dedicated REVIEWER_OF relationship for a user."""
    with neo4j_driver.session() as session:
        query = """
        MATCH (owner:User {email: $owner_email})-[:OWNS]->(p:Project {id: $project_id})
        MATCH (target:User {email: $target_email})
        MERGE (target)-[r:REVIEWER_OF]->(p)
        RETURN target
        """
        result = session.run(
            query,
            owner_email=owner_email,
            project_id=project_id,
            target_email=target_email,
        ).single()
        return bool(result)


def get_eligible_approvers_from_db(
    requester_email: str, project_id: str, secret_id: str
) -> list[str] | None:
    """
    Verifies requester has access to project_id and secret_id belongs to project_id,
    then discovers all other users dynamically authorized to approve requests.
    """
    with neo4j_driver.session() as session:
        check_query = """
        MATCH (req_user:User {email: $requester_email})-[:OWNS|HAS_ACCESS|REVIEWER_OF]->(p:Project {id: $project_id})-[:CONTAINS]->(s:Secret {id: $secret_id})
        RETURN p.id AS pid
        """
        has_access = session.run(
            check_query,
            requester_email=requester_email,
            project_id=project_id,
            secret_id=secret_id,
        ).single()
        if not has_access:
            return None

        approvers_query = """
        MATCH (u:User)-[r:OWNS|HAS_ACCESS|REVIEWER_OF]->(p:Project {id: $project_id})
        WHERE (type(r) IN ['OWNS', 'REVIEWER_OF'] OR r.role = 'editor')
          AND u.email <> $requester_email
        RETURN collect(DISTINCT u.email) AS approvers
        """
        result = session.run(
            approvers_query,
            project_id=project_id,
            requester_email=requester_email,
        ).single()
        if not result:
            return []
        return [email for email in result["approvers"] if email is not None]

def evaluate_sorted_set_quorum(
    redis_client, request_id: str, quorum_size: int
) -> tuple[int, bool]:
    """
    Cleans expired approvals using Redis ZREMRANGEBYSCORE and counts live ones using ZCOUNT.
    Returns (current_live_approvals, quorum_reached_boolean).
    """
    approvals_key = f"approvals:{request_id}"
    now = time.time()

    redis_client.zremrangebyscore(approvals_key, 0, now)
    live_count = redis_client.zcount(approvals_key, now, "+inf")

    return live_count, live_count >= quorum_size

def get_approver_inbox_from_db(approver_email: str) -> list[dict]:
    """
    Finds all pending AccessRequests across projects where the user is an
    owner, editor, or reviewer (excluding the user's own requests).
    """
    with neo4j_driver.session() as session:
        query = """
        MATCH (approver:User {email: $approver_email})-[r:OWNS|HAS_ACCESS|REVIEWER_OF]->(p:Project)-[:CONTAINS]->(s:Secret)
        WHERE type(r) IN ['OWNS', 'REVIEWER_OF'] OR r.role = 'editor'
        MATCH (requester:User)-[:MADE]->(req:AccessRequest)-[:FOR]->(s)
        WHERE req.status = 'pending' AND requester.email <> $approver_email
        RETURN DISTINCT
            req.id AS request_id,
            s.id AS secret_id,
            s.key_name AS key_name,
            p.id AS project_id,
            p.name AS project_name,
            requester.email AS requester_email,
            s.quorum_size AS quorum_size,
            toString(req.created_at) AS created_at
        ORDER BY created_at DESC
        """
        return session.run(query, approver_email=approver_email).data()