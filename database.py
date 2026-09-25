import os
from dotenv import load_dotenv
from neo4j import GraphDatabase
import redis.asyncio as redis

load_dotenv()
neo4j_uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
neo4j_user = os.getenv("NEO4J_USER", "neo4j")
neo4j_password = os.getenv("NEO4J_PASSWORD")
AUTH=(neo4j_user,neo4j_password)

neo4j_driver=GraphDatabase.driver(neo4j_uri,auth=AUTH)
#neo4j_driver.verify_connectivity()

redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
redis_client=redis.Redis.from_url(redis_url)


async def test_connections():
    await redis_client.ping()
    print("Redis is connected!")
    
    neo4j_driver.verify_connectivity()
    print("Neo4j is connected!")

if __name__ == "__main__":
    import asyncio
    asyncio.run(test_connections())
