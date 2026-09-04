"""User business rules."""
from app.models.users import User, UserCreate
from app.repositories import users as user_repository


def create_user(user: UserCreate) -> User:
    return user_repository.create_user(user)


def get_user(user_id: int) -> User | None:
    return user_repository.get_user(user_id)