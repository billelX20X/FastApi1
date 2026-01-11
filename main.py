from fastapi import FastAPI
from pydantic import BaseModel
import asyncio

app = FastAPI()

# Pydantic model ensures the request body contains the right data
class TestRequest(BaseModel):
    user_id: str | int  # Accepts string or int

@app.get("/")
async def hello_world():
    return "Hello from FastAPI!"

@app.post("/test")
async def test(data: TestRequest):
    # In FastAPI, we use asyncio.sleep for non-blocking delays
    await asyncio.sleep(6)
    
    # No need for jsonify; FastAPI automatically converts dicts to JSON
    return {
        "status": "success",
        "user_id": data.user_id
    }
