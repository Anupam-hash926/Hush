from app.database import neo4j_driver

def create_user_in_db(email: str, hashed_password: str):
    query = """
    MERGE (u:User {email: $email})
    ON CREATE SET u.password_hash = $password_hash
    RETURN u.email AS email
    """
      
    with neo4j_driver.session() as session:
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