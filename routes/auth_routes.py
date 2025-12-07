from fastapi import APIRouter, HTTPException, Depends
from datetime import datetime
from pydantic import BaseModel

from models.models import UserCreate, UserLogin, Token
from db.database import users_collection
from utils.auth_utils import hash_password, verify_password, create_access_token
from services.dependencies import get_current_user

router = APIRouter(prefix="/auth", tags=["Authentication"])


async def get_user_by_email(email: str):
    return await users_collection.find_one({"email": email})


# ✅ REGISTER
@router.post("/register")
async def register(user: UserCreate):
    existing = await get_user_by_email(user.email)
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    user_doc = {
        "name": user.name,
        "email": user.email,
        "hashed_password": hash_password(user.password),
        "role": "operator",
        "created_at": datetime.utcnow(),
    }

    result = await users_collection.insert_one(user_doc)

    return {"message": "User registered successfully", "id": str(result.inserted_id)}


# ✅ LOGIN
@router.post("/login", response_model=Token)
async def login(user: UserLogin):
    db_user = await get_user_by_email(user.email)
    if not db_user or not verify_password(user.password, db_user["hashed_password"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    token = create_access_token(
        data={"sub": db_user["email"], "role": db_user.get("role", "operator")}
    )

    return {"access_token": token, "token_type": "bearer"}


# ✅ GET CURRENT USER PROFILE
@router.get("/me")
async def get_my_profile(current_user=Depends(get_current_user)):
    return current_user


# ✅ CHANGE PASSWORD
class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


@router.post("/change-password")
async def change_password(
    payload: ChangePasswordRequest,
    current_user=Depends(get_current_user)
):
    db_user = await users_collection.find_one({"email": current_user["email"]})

    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")

    if not verify_password(payload.old_password, db_user["hashed_password"]):
        raise HTTPException(status_code=400, detail="Current password is incorrect")

    new_hashed = hash_password(payload.new_password)

    await users_collection.update_one(
        {"_id": db_user["_id"]},
        {"$set": {"hashed_password": new_hashed}}
    )

    return {"message": "Password updated successfully"}
