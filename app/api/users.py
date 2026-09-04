"""User HTTP endpoints."""
from fastapi import APIRouter, HTTPException

from app.models.users import User, UserCreate
from app.services import users as user_service


router = APIRouter(
    prefix="/users",
    tags=["users"],
)


@router.post("", response_model=User)
async def create_user(user: UserCreate):

    return user_service.create_user(user)


@router.get("/{user_id}", response_model=User)
async def get_user(user_id: int):

    user = user_service.get_user(user_id)

    if user is None:
        raise HTTPException(
            status_code=404,
            detail="User not found",
        )

    return user