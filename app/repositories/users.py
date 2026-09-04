"""User persistence operations."""
from app.models.users import User, UserCreate

users : dict[int, User] = {}

next_user_id = 1

def create_user(user_data:UserCreate) -> User:
    global next_user_id

    new_user = User(
        id=next_user_id,
        name=user_data.name,
        email=user_data.email,
        )
    users[next_user_id] = new_user

    next_user_id += 1

    return new_user

def get_user(user_id:int) -> User | None:

    return users.get(user_id)