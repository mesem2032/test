# main.py
import os
import sys
import glob
import time
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from google import genai
from google.genai import types
import firebase_admin
from firebase_admin import credentials, db

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

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
        return True
    except Exception as e: print(f"[Firebase Init Error] {e}")
    return False

init_firebase()

app = FastAPI(title="Smart Nursing Assistant")

class UserAuth(BaseModel):
    username: str
    password: str

class AdminAddUser(BaseModel):
    username: str
    password: str
    display_name: str

class ChatPayload(BaseModel):
    username: str
    prompt: str
    history: list = []

def get_users_db():
    try:
        ref = db.reference('users')
        data = ref.get()
        return data if isinstance(data, dict) else {}
    except: return {}

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

GEMINI_CTX, GEMINI_KEYS = [], []
try:
    keys = [os.getenv(f"GEMINI_API_KEY_{i}") for i in range(1, 6)]
    keys = [k for k in keys if k]
    pdfs = glob.glob(str(BASE_DIR / "*.pdf"))
    if not pdfs: raise FileNotFoundError("No PDF books found.")
    client = genai.Client(api_key=keys[0])
    GEMINI_CTX = [client.files.upload(file=f) for f in pdfs]
    GEMINI_KEYS = keys
except Exception as e: print(f"[Gemini Init Warning] {e}")

@app.post("/api/login")
async def login(d: UserAuth):
    uname = d.username.strip().lower()
    pwd = d.password.strip()
    db_data = get_users_db()
    
    if uname in db_data:
        user_role = db_data[uname].get("role", "")
        is_admin = (user_role == "admin")
        
        if pwd == db_data[uname].get("password"):
            return {"status": "success", "name": db_data[uname].get("name"), "username": uname, "isAdmin": is_admin}
            
    return {"status": "error", "message": "الحساب غير موجود أو كلمة المرور خاطئة"}

@app.post("/api/promote-to-admin")
async def promote_to_admin(req: ChatPayload):
    try:
        u = req.username.strip().lower()
        db_data = get_users_db()
        if u in db_data:
            db.reference(f'users/{u}').update({"role": "admin"})
            return {"status": "success", "message": "تم الترقية بنجاح! أعد تسجيل الدخول."}
        return {"status": "error", "message": "لم يتم العثور على الحساب في قاعدة البيانات."}
    except Exception as e:
        return {"status": "error", "message": f"حدث خطأ أثناء الترقية: {str(e)}"}

@app.post("/api/admin/users/add")
async def add_user(d: AdminAddUser):
    db_data = get_users_db()
    u = d.username.strip().lower()
    if u in db_data: return {"status": "error", "message": "اسم المستخدم موجود بالفعل"}
    try:
        db.reference(f'users/{u}').set({
            "password": d.password, 
            "name": d.display_name or "جديد"
        })
        return {"status": "success"}
    except Exception as e: return {"status": "error", "message": f"خطأ أثناء الإضافة: {str(e)}"}

@app.get("/api/admin/users/list")
async def get_admin_users_list():
    users = get_users_db()
    table_data = []
    for u_id, u_info in users.items():
        table_data.append({
            "username": u_id,
            "name": u_info.get("name", ""),
            "is_admin": u_info.get("role", "") == "admin"
        })
    return JSONResponse(content=table_data)

# ✅ التصحيح النهائي للحذف
@app.post("/api/admin/users/delete")
async def delete_user(req: ChatPayload):
    try:
        u = req.username.strip().lower()
        
        # استخدام Reference مباشر ومسحه
        user_ref = db.reference(f'users/{u}')
        user_ref.delete()
        
        chat_ref = db.reference(f'chats/{u}')
        chat_ref.delete()
        
        return {"status": "success", "message": "تم حذف الحساب بنجاح"}
    except Exception as e:
        # طباعة الخطأ في السيرفر لمعرفة السبب بدقة
        print(f"[Delete Error] {str(e)}") 
        return {"status": "error", "message": f"فشل الحذف تقنياً: {str(e)}"}

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
            
            resp = cl.models.generate_content(model='gemini-2.0-flash', contents=ctx, config=types.GenerateContentConfig(system_instruction=system_instr, temperature=0.2))
            ans = resp.text
            save_msg(req.username, "user", req.prompt)
            save_msg(req.username, "assistant", ans)
            return JSONResponse(content={"reply": ans})
        except Exception as e:
            last_err = e
    return JSONResponse(content={"reply": f"⚠️ خطأ النموذج: {last_err}"}, status_code=500)

@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    try:
        return templates.TemplateResponse("index.html", {"request": request})
    except Exception as e:
        return HTMLResponse(content=f"<h1>Error loading template: {e}</h1>", status_code=500)
