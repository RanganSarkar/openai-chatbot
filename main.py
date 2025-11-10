from fastapi.middleware.cors import CORSMiddleware
from fastapi import FastAPI, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr
from pymongo import MongoClient
from dotenv import load_dotenv
from openai import OpenAI
import os
import jwt
import datetime
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
# ------------------- Load Environment Variables -------------------
load_dotenv()

MONGO_URI = os.getenv("MONGO_URI")
DB_NAME = os.getenv("DB_NAME", "user_db")
SECRET_KEY = os.getenv("SECRET_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not MONGO_URI or not SECRET_KEY or not OPENAI_API_KEY:
    raise RuntimeError("❌ Missing required environment variables in .env")

# ------------------- Initialize Services -------------------
app = FastAPI(title="Chatbot with Auth + OpenAI")
security = HTTPBearer()

app.mount("/static", StaticFiles(directory="build/static"), name="static")

@app.get("/")
def serve_root():
    return FileResponse("build/index.html")

# ------------------- CORS Middleware -------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # React dev server
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


client = MongoClient(MONGO_URI)
db = client[DB_NAME]
users_col = db["users"]

openai_client = OpenAI(api_key=OPENAI_API_KEY)


# ------------------- Pydantic Models -------------------
class RegisterRequest(BaseModel):
    name: str
    email: EmailStr
    password: str

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class ChatRequest(BaseModel):
    message: str

# ------------------- Helper Functions -------------------
def create_jwt(email: str, expires_hours: int = 2) -> str:
    payload = {
        "email": email,
        "exp": datetime.datetime.utcnow() + datetime.timedelta(hours=expires_hours),
        "iat": datetime.datetime.utcnow()
    }
    token = jwt.encode(payload, SECRET_KEY, algorithm="HS256")
    if isinstance(token, bytes):
        token = token.decode("utf-8")
    return token

def decode_jwt(token: str):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

# ------------------- Routes -------------------
@app.post("/register")
def register_user(req: RegisterRequest):
    existing = users_col.find_one({"email": req.email})
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    user_doc = {"name": req.name, "email": req.email, "password": req.password}
    users_col.insert_one(user_doc)
    return {"message": "User registered successfully"}

@app.post("/login")
def login_user(req: LoginRequest):
    user = users_col.find_one({"email": req.email})
    if not user or user["password"] != req.password:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_jwt(req.email)
    return {"message": "Login successful", "token": token}

# Dependency to verify token
def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    token = credentials.credentials
    payload = decode_jwt(token)
    email = payload.get("email")
    user = users_col.find_one({"email": email})
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user

@app.post("/chat")
def chat(req: ChatRequest, user=Depends(get_current_user)):
    try:
        completion = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": f"You are a helpful assistant for user {user['name']}."},
                {"role": "user", "content": req.message}
            ]
        )
        reply = completion.choices[0].message.content
        return {"user": user["name"], "reply": reply}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"OpenAI error: {str(e)}")

@app.get("/")
def home():
    return {"message": "✅ FastAPI Chatbot running successfully!"}
