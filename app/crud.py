from app.database import neo4j_driver
import uuid


def create_user_in_db(email: str, hashed_password: str):

    query = """
    MERGE (u:User {email: $email})
    ON CREATE SET u.password_hash = $password_hash
    RETURN u.email AS email
    """
      
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

def create_secret_in_db(email: str, project_id: str, key_name: str, encrypted_data: dict):
    with neo4j_driver.session() as session:
        query = """
        MATCH (u:User {email: $email})-[r:OWNS|HAS_ACCESS]->(p:Project {id: $project_id})
        CREATE (s:Secret {
            id: randomUUID(),
            key_name: $key_name,
            salt: $salt,
            nonce: $nonce,
            ciphertext: $ciphertext
        })
        CREATE (p)-[:CONTAINS]->(s)
        RETURN s.id AS id, s.key_name AS key_name
        """    
        result = session.run(query,email=email,project_id=project_id,key_name=key_name,salt=encrypted_data["salt"],nonce=encrypted_data["nonce"],ciphertext=encrypted_data["ciphertext"])
        record = result.single()
        if not record:
            return None
        return {"id":record["id"],"key_name":record["key_name"]}

def get_project_secrets_from_db(email: str, project_id: str):
    with neo4j_driver.session() as session:
        query = """
        MATCH (u:User {email: $email})-[r:OWNS|HAS_ACCESS]->(p:Project {id: $project_id})-[:CONTAINS]->(s:Secret)
        RETURN s.id AS id, s.key_name AS key_name, s.salt AS salt, s.nonce AS nonce, s.ciphertext AS ciphertext
        """
        result = session.run(query,email=email,project_id=project_id)
        return result.data()