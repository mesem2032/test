import streamlit as st
import os
import glob
import requests
import urllib.parse
from google import genai
from google.genai import types

# 1. إعدادات الصفحة والتنسيق العربي (RTL)
st.set_page_config(page_title="المساعد التمريضي الذكي", page_icon="🩺", layout="centered")

st.markdown("""
    <style>
    /* محاذاة نصوص المحادثة والعناوين والمدخلات لليمين فقط دون تخريب القائمة الجانبية */
    .block-container, [data-testid="stChatMessage"], .stChatInputContainer, [data-testid="stSidebarContent"] {
        direction: rtl !important;
        text-align: right !important;
    }

    /* محاذاة مربع كتابة الأسئلة والقوائم */
    ul, ol, .stChatInputContainer textarea {
        direction: rtl !important;
        text-align: right !important;
    }

    /* إصلاح اتجاه العناصر داخل Sidebar والـ Dialog */
    [data-testid="stSidebarContent"] *, [data-testid="stDialog"] * {
        text-align: right !important;
        direction: rtl !important;
    }
    </style>
""", unsafe_allow_html=True)

# 2. رابط Realtime Database وتحديد اسم الأدمن من Secrets
RTDB_BASE_URL = st.secrets.get("FIREBASE_DATABASE_URL", "https://nurser-grade1-default-rtdb.firebaseio.com").rstrip('/')

# 👑 جلب اسم الأدمن من Secrets
ADMIN_USERNAME = st.secrets.get("ADMIN_USERNAME", "mohammed esmail").strip().lower()

# 3. جلب بيانات المستخدمين من Firebase
def get_users_from_rtdb():
    try:
        url = f"{RTDB_BASE_URL}/users.json"
        res = requests.get(url, timeout=5)
        if res.status_code == 200 and res.json():
            data = res.json()
            users = {}
            for u_id, u_info in data.items():
                if isinstance(u_info, dict):
                    pwd = str(u_info.get("password", "")).replace('"', '').replace("'", "").strip()
                    name = str(u_info.get("name", u_id)).replace('"', '').replace("'", "").strip()
                    users[str(u_id).strip().lower()] = {
                        "password": pwd,
                        "name": name
                    }
            return users
    except Exception as e:
        st.error(f"⚠️ خطأ في الاتصال بقاعدة البيانات: {e}")
    return {}

# 4. دوال إدارة المستخدمين (إضافة / تعديل / حذف)
def add_or_update_user_in_rtdb(uname, password, display_name):
    try:
        encoded_uname = urllib.parse.quote(uname)
        url = f"{RTDB_BASE_URL}/users/{encoded_uname}.json"
        payload = {
            "password": password,
            "name": display_name
        }
        res = requests.put(url, json=payload)
        return res.status_code == 200
    except Exception:
        return False

def delete_user_from_rtdb(uname):
    try:
        encoded_uname = urllib.parse.quote(uname)
        url = f"{RTDB_BASE_URL}/users/{encoded_uname}.json"
        res = requests.delete(url)
        requests.delete(f"{RTDB_BASE_URL}/chats/{encoded_uname}.json")
        return res.status_code == 200
    except Exception:
        return False

# 💡 نافذة الـ Pop-up الخاصة بلواحة تحكم الأدمن
@st.dialog("🛠️ لوحة إدارة الحسابات", width="large")
def open_admin_modal():
    tab_add, tab_edit, tab_delete, tab_list = st.tabs([
        "➕ إضافة مستخدم", 
        "✏️ تعديل مستخدم", 
        "🗑️ حذف مستخدم", 
        "📋 قائمة المستخدمين"
    ])

    users_db = get_users_from_rtdb()

    # تبويب 1: إضافة مستخدم
    with tab_add:
        st.subheader("إضافة حساب جديد")
        with st.form("add_user_form"):
            new_uname = st.text_input("اسم المستخدم (Username)").strip().lower()
            new_pass = st.text_input("كلمة المرور (Password)").strip()
            new_name = st.text_input("الاسم الظاهر (Display Name)").strip()
            btn_add = st.form_submit_button("إضافة الحساب")

            if btn_add:
                if not new_uname or not new_pass or not new_name:
                    st.warning("⚠️ يرجى ملء كافة البيانات!")
                elif new_uname in users_db:
                    st.error("⚠️ اسم المستخدم هذا موجود بالفعل!")
                else:
                    if add_or_update_user_in_rtdb(new_uname, new_pass, new_name):
                        st.success(f"✅ تم إضافة المستخدم '{new_uname}' بنجاح!")
                        st.rerun()
                    else:
                        st.error("❌ حدث خطأ أثناء الإضافة.")

    # تبويب 2: تعديل مستخدم
    with tab_edit:
        st.subheader("تعديل بيانات حساب")
        if users_db:
            selected_user = st.selectbox("اختر المستخدم للتعديل", list(users_db.keys()))
            current_data = users_db[selected_user]
            
            with st.form("edit_user_form"):
                edit_pass = st.text_input("كلمة المرور الجديدة", value=current_data["password"]).strip()
                edit_name = st.text_input("الاسم الظاهر الجديد", value=current_data["name"]).strip()
                btn_edit = st.form_submit_button("حفظ التعديلات")

                if btn_edit:
                    if add_or_update_user_in_rtdb(selected_user, edit_pass, edit_name):
                        st.success(f"✅ تم تحديث بيانات '{selected_user}' بنجاح!")
                        st.rerun()
                    else:
                        st.error("❌ حدث خطأ أثناء التحديث.")

    # تبويب 3: حذف مستخدم
    with tab_delete:
        st.subheader("حذف حساب")
        if users_db:
            deletable_users = [u for u in users_db.keys() if u != ADMIN_USERNAME]
            if deletable_users:
                user_to_delete = st.selectbox("اختر الحساب المراد حذفه", deletable_users)
                if st.button("🚨 تأكيد حذف الحساب نهائياً", type="primary"):
                    if delete_user_from_rtdb(user_to_delete):
                        st.success(f"✅ تم حذف الحساب '{user_to_delete}' ومحادثاته بنجاح!")
                        st.rerun()
                    else:
                        st.error("❌ حدث خطأ أثناء الحذف.")
            else:
                st.info("لا يوجد مستخدمون آخرون لحذفهم.")

    # تبويب 4: عرض القائمة
    with tab_list:
        st.subheader("الحسابات المسجلة حالياً")
        st.json(users_db)

# 5. إدارة حالة تسجيل الدخول (Session State)
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
if "user_info" not in st.session_state:
    st.session_state.user_info = {}

# 6. واجهة تسجيل الدخول
if not st.session_state.authenticated:
    st.markdown("### 🔐 تسجيل الدخول")
    
    with st.form("login_form"):
        username_input = st.text_input("اسم المستخدم (Username)").strip().lower()
        password_input = st.text_input("كلمة المرور (Password)", type="password").strip()
        submit_button = st.form_submit_button("تسجيل الدخول")

        if submit_button:
            if not username_input or not password_input:
                st.warning("⚠️ يرجى إدخال اسم المستخدم وكلمة المرور.")
            else:
                users_db = get_users_from_rtdb()
                
                if username_input in users_db:
                    user_data = users_db[username_input]
                    if password_input == user_data["password"]:
                        st.session_state.authenticated = True
                        st.session_state.user_info = {
                            "username": username_input,
                            "name": user_data["name"]
                        }
                        st.success("تم تسجيل الدخول بنجاح! 🎉")
                        st.rerun()
                    else:
                        st.error("⚠️ كلمة المرور غير صحيحة.")
                else:
                    st.error("⚠️ اسم المستخدم غير موجود.")
    st.stop()

# 7. الواجهة الرئيسية بعد تسجيل الدخول بنجاح ✅
username = st.session_state.user_info["username"]
display_name = st.session_state.user_info["name"]

# عناصر القائمة الجانبية
st.sidebar.markdown(f"مرحباً بك يا **{display_name}** 👋")

if st.sidebar.button("🚪 تسجيل الخروج"):
    st.session_state.authenticated = False
    st.session_state.user_info = {}
    st.rerun()

if st.sidebar.button("🗑️ مسح محادثاتي السابقة"):
    try:
        encoded_uname = urllib.parse.quote(username)
        requests.delete(f"{RTDB_BASE_URL}/chats/{encoded_uname}.json")
    except Exception:
        pass
    st.session_state.messages = []
    st.rerun()

# 8. قسم إدارة الحسابات (يظهر فقط للأدمن المعرف في Secrets)
if username.lower() == ADMIN_USERNAME:
    st.sidebar.divider()
    st.sidebar.markdown("### 👑 لوحة تحكم الأدمن")
    if st.sidebar.button("⚙️ فتح لوحة إدارة الحسابات"):
        open_admin_modal()

st.title("📚 المساعد التمريضي الذكي")

# 9. جلب مفاتيح Gemini
def get_gemini_keys():
    keys = []
    i = 1
    while True:
        key = st.secrets.get(f"GEMINI_API_KEY_{i}") or os.environ.get(f"GEMINI_API_KEY_{i}")
        if key:
            keys.append(key)
            i += 1
        else:
            break
    if not keys:
        single_key = st.secrets.get("GEMINI_API_KEY") or st.secrets.get("GOOGLE_API_KEY")
        if single_key:
            keys.append(single_key)
    return keys

gemini_keys = get_gemini_keys()
if not gemini_keys:
    st.error("⚠️ لم يتم العثور على أي مفاتيح GEMINI_API_KEY في إعدادات Secrets!")
    st.stop()

# 10. رفع ملفات الكتب
@st.cache_resource
def upload_books_once():
    pdf_files = glob.glob("./*.pdf")
    if not pdf_files:
        st.error("⚠️ لم يتم العثور على أي ملفات PDF في المستودع!")
        st.stop()
    client = genai.Client(api_key=gemini_keys[0])
    uploaded_files = []
    for path in pdf_files:
        u_file = client.files.upload(file=path)
        uploaded_files.append(u_file)
    return uploaded_files

with st.spinner("جاري تهيئة الكتب وقراءتها سحابياً..."):
    cached_uploaded_files = upload_books_once()

# 11. حفظ واسترجاع الرسائل من Realtime Database
def load_rtdb_messages(uname):
    try:
        encoded_uname = urllib.parse.quote(uname)
        res = requests.get(f"{RTDB_BASE_URL}/chats/{encoded_uname}.json")
        if res.status_code == 200 and res.json():
            chat_data = res.json()
            messages = []
            for msg_id in sorted(chat_data.keys()):
                messages.append({
                    "role": chat_data[msg_id]['role'],
                    "content": chat_data[msg_id]['content']
                })
            return messages
    except Exception:
        pass
    return []

def save_message_to_rtdb(uname, role, content):
    try:
        import time
        encoded_uname = urllib.parse.quote(uname)
        payload = {
            'role': role,
            'content': content,
            'timestamp': int(time.time() * 1000)
        }
        requests.post(f"{RTDB_BASE_URL}/chats/{encoded_uname}.json", json=payload)
    except Exception:
        pass

if "messages" not in st.session_state or st.session_state.get("active_user") != username:
    st.session_state["active_user"] = username
    st.session_state.messages = load_rtdb_messages(username)

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# 12. الرد بـ Gemini Flash
def ask_gemini_fast(prompt, history):
    system_instruction = (
        "أنت مساعد أكاديمي ومتخصص في المناهج التمريضية والطبية. "
        "أجب على سؤال الطالب باللغة العربية بدقة وبإسهاب بناءً على محتوى كتب الـ PDF المرفقة معك فقط."
    )
    
    last_error = None
    for index, api_key in enumerate(gemini_keys):
        try:
            client = genai.Client(api_key=api_key)
            contents = []
            contents.extend(cached_uploaded_files)
            
            for msg in history:
                role_label = "الطالب" if msg['role'] == 'user' else "المساعد"
                contents.append(f"{role_label}: {msg['content']}")
            
            contents.append(f"سؤال الطالب الحالي: {prompt}")

            response = client.models.generate_content(
                model='gemini-3.5-flash',
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    temperature=0.2,
                )
            )
            return response.text
        except Exception as e:
            last_error = e
            continue
            
    return f"⚠️ عذراً حدث خطأ في الاتصال بالنموذج: {last_error}"

if prompt := st.chat_input("اسأل أي سؤال في الكتب المقررة..."):
    save_message_to_rtdb(username, "user", prompt)
    st.session_state.messages.append({"role": "user", "content": prompt})
    
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("جاري البحث والإجابة من الكتب..."):
            answer = ask_gemini_fast(prompt, st.session_state.messages[:-1])
            
            save_message_to_rtdb(username, "assistant", answer)
            st.markdown(answer)
            st.session_state.messages.append({"role": "assistant", "content": answer})
