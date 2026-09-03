from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()

class UserCreate(BaseModel):
    name: str
    email: str

class User(BaseModel):
    id: int
    name: str
    email: str

users = {}

next_user_id = 1
@app.get("/health")
async def health_check():
    return {"status": "ok"}
@app.post("/users", response_model=User)
async def create_user(user: UserCreate):
    global next_user_id

    new_user = User(
        id=next_user_id,
        name=user.name,
        email=user.email
    )

    users[next_user_id] = new_user
    next_user_id += 1
    return new_user

@app.get("/users/{user_id}")
async def get_user(user_id: int):
    return users.get(user_id)