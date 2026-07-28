# main.py
import os
import glob
import time
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from google import genai
from google.genai import types
import firebase_admin
from firebase_admin import credentials, db

# === 1. تهيئة فايربيز الأمنية ===
def init_firebase():
    try:
        if not firebase_admin._apps:
            cred_json = {
                "type": os.getenv("FIREBASE_TYPE"),
                "project_id": os.getenv("FIREBASE_PROJECT_ID"),
                "private_key_id": os.getenv("FIREBASE_PRIVATE_KEY_ID"),
                "private_key": os.getenv("FIREBASE_PRIVATE_KEY").replace("\\n", "\n"),
                "client_email": os.getenv("FIREBASE_CLIENT_EMAIL"),
                "client_id": os.getenv("FIREBASE_CLIENT_ID"),
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
            firebase_admin.initialize_app(credentials.Certificate(cred_json), {
                'databaseURL': os.getenv("FIREBASE_DATABASE_URL")
            })
    except Exception as e: print(f"[Firebase Error] {e}")

init_firebase()

app = FastAPI(title="Smart Nursing Assistant")
templates = Jinja2Templates(directory=".")
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "").strip().lower()

class UserCredential(BaseModel):
    username: str
    password: str
    display_name: str

class ChatPayload(BaseModel):
    username: str
    prompt: str
    history: list = []

# === دوال فايربيز الآمنة ===
def get_users_db():
    ref = db.reference('users')
    return ref.get() or {}

def save_msg(username: str, role: str, content: str):
    try:
        ref = db.reference(f'chats/{username}')
        ref.push({'role': role, 'content': content, 'timestamp': int(time.time()*1000)})
    except: pass

def load_history(username: str):
    try:
        ref = db.reference(f'chats/{username}')
        data = ref.get()
        if data and isinstance(data, list):
            return sorted(data, key=lambda x: x.get('timestamp', 0))
    except: pass
    return []

# === تهيئة ذكاء جوجل ===
GEMINI_CTX, GEMINI_KEYS = [], []
try:
    keys = [os.getenv(f"GEMINI_API_KEY_{i}") for i in range(1, 6)]
    keys = [k for k in keys if k]
    pdfs = glob.glob("./*.pdf")
    if not pdfs: raise Exception("No PDFs in repo root.")
    client = genai.Client(api_key=keys[0])
    GEMINI_CTX = [client.files.upload(file=f) for f in pdfs]
    GEMINI_KEYS = keys
except Exception as e: print(f"[Gemini Init] {e}")

# === واجهات الـ API ===
@app.post("/api/login")
async def login(d: UserCredential):
    db = get_users_db()
    u = d.username.strip().lower()
    if u in db and d.password == db[u].get("password"):
        return {"status": "success", "name": db[u].get("name"), "username": u}
    return {"status": "error", "message": "بيانات خاطئة"}

@app.post("/api/admin/users/add")
async def add_user(d: UserCredential):
    db = get_users_db()
    u = d.username.strip().lower()
    if u == ADMIN_USERNAME: return {"status": "error", "message": "ممنوع تعديل حساب الأدمن"}
    if u in db: return {"status": "error", "message": "اسم المستخدم موجود بالفعل"}
    try:
        db.reference(f'users/{u}').set({"password": d.password, "name": d.display_name})
        return {"status": "success"}
    except: return {"status": "error", "message": "فشل الاتصال بالباييز"}

@app.get("/api/messages/{username}")
async def get_msgs(username: str):
    return JSONResponse(content=load_history(username))

@app.post("/api/chat")
async def ask_ai(req: ChatPayload):
    if not GEMINI_CTX or not GEMINI_KEYS:
        return JSONResponse(content={"reply": "⚠️ لم يتم تحميل الكتب المرجعية."}, status_code=500)
    
    system_instr = "أنت مساعد أكاديمي متخصص في المناهج التمريضية. أجب بالعربية بدقة بناءً على محتوى الملفات المرفقة فقط."
    last_err = None
    for k in GEMINI_KEYS:
        try:
            cl = genai.Client(api_key=k)
            ctx = [*GEMINI_CTX]
            for m in req.history[-8:]:
                ctx.append(f"{m['role']}: {m['content']}")
            ctx.append(f"Question: {req.prompt}")
            
            resp = cl.models.generate_content(model='gemini-2.0-flash-exp', contents=ctx, config=types.GenerateContentConfig(system_instruction=system_instr, temperature=0.2))
            ans = resp.text
            save_msg(req.username, "user", req.prompt)
            save_msg(req.username, "assistant", ans)
            return JSONResponse(content={"reply": ans})
        except Exception as e:
            last_err = e
    return JSONResponse(content={"reply": f"⚠️ خطأ النموذج: {last_err}"}, status_code=500)

@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})
