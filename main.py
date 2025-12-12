import os
import requests
import gradio as gr
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime

# Load environment variables
load_dotenv()

FIREBASE_API_KEY = os.getenv("FIREBASE_API_KEY")
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")

FB_SIGNUP = f"https://identitytoolkit.googleapis.com/v1/accounts:signUp?key={FIREBASE_API_KEY}"
FB_SIGNIN = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={FIREBASE_API_KEY}"

# Firebase Admin Setup
cred = credentials.Certificate("serviceAccountKey.json")
firebase_admin.initialize_app(cred)
db = firestore.client()


# ------------------ SAFE SIGNUP ------------------ #
def signup(email, password):
    data = {"email": email, "password": password, "returnSecureToken": True}
    try:
        res = requests.post(FB_SIGNUP, json=data)
        data = res.json()

        if res.status_code != 200:
            error_msg = data.get("error", {}).get("message", "Unknown error")
            return f"❌ Signup Error: {error_msg}"

        # Save to Firestore
        db.collection("users").document(data["localId"]).set({
            "email": email,
            "created_at": datetime.utcnow(),
            "last_login": None
        })

        return "🎉 Signup successful! Please login."

    except Exception as e:
        return f"❌ Signup failed: {str(e)}"


# ------------------ SAFE LOGIN ------------------ #
def login(email, password, session):
    data = {"email": email, "password": password, "returnSecureToken": True}

    try:
        res = requests.post(FB_SIGNIN, json=data)
        data = res.json()

        if res.status_code != 200:
            return "❌ Invalid email or password.", session

        session["logged_in"] = True
        session["uid"] = data["localId"]
        session["email"] = data["email"]

        db.collection("users").document(data["localId"]).update({
            "last_login": datetime.utcnow()
        })

        return "✅ Login successful!", session

    except Exception:
        return "❌ Login failed.", session


# ------------------ SAVE MESSAGES ------------------ #
def save_message(uid, role, text):
    db.collection("chats").document(uid).collection("messages").add({
        "role": role,
        "text": text,
        "time": datetime.utcnow()
    })


# ------------------ LOAD CHAT HISTORY ------------------ #
def load_history(session):
    if not session.get("logged_in"):
        return "❌ Please login to view history."

    uid = session["uid"]
    docs = db.collection("chats").document(uid).collection("messages").order_by("time").stream()

    history_text = "### 🕒 Chat History\n\n"
    for d in docs:
        msg = d.to_dict()
        t = msg["time"].strftime("%Y-%m-%d %H:%M:%S")
        history_text += f"**[{msg['role']}]** ({t}) → {msg['text']}\n\n"

    return history_text


# ------------------ MISTRAL AI CHAT (NO ERRORS) ------------------ #
def mistral_chat(message, history, session):
    if history is None:
        history = []

    if not session.get("logged_in"):
        history.append(("System", "❌ Please login to chat."))
        return history, history

    try:
        response = requests.post(
            "https://api.mistral.ai/v1/chat/completions",
            headers={"Authorization": f"Bearer {MISTRAL_API_KEY}"},
            json={
                "model": "mistral-small-latest",
                "messages": [{"role": "user", "content": message}]
            }
        )

        data = response.json()

        bot_reply = data["choices"][0]["message"]["content"]

        # Append correctly
        history.append((message, bot_reply))

        # Save chat messages
        save_message(session["uid"], "user", message)
        save_message(session["uid"], "bot", bot_reply)

        return history, history

    except Exception as e:
        history.append(("Error", f"❌ Chat Error: {str(e)}"))
        return history, history


# ------------------ LOGOUT ------------------ #
def logout(session):
    session["logged_in"] = False
    session["uid"] = None
    session["email"] = None

    return "👋 Logged out successfully.", session, [], []


# ------------------ CUSTOM UI CSS ------------------ #
CUSTOM_CSS = """
<style>
body { background: #0F172A; font-family: 'Inter', sans-serif;}
.gradio-container { max-width: 900px !important; margin: auto; }

.card {
    background: rgba(255,255,255,0.07);
    padding: 25px;
    border-radius: 16px;
    backdrop-filter: blur(12px);
    box-shadow: 0 10px 25px rgba(0,0,0,0.4);
}

h1, h2, h3 { color: #38bdf8 !important; }

label { color: #e2e8f0 !important; }

textarea, input {
    background: rgba(255,255,255,0.15) !important;
    color: white !important;
    border-radius: 10px !important;
}

button {
    border-radius: 10px !important;
    font-weight: bold !important;
}
</style>
"""


# ------------------ APP UI ------------------ #
with gr.Blocks(css=CUSTOM_CSS, theme=gr.themes.Soft()) as app:

    session = gr.State({"logged_in": False, "uid": None, "email": None})
    chat_history = gr.State([])

    gr.Markdown("## 💬 Modern AI Chat App with Firebase Auth + Firestore")

    # Signup Tab
    with gr.Tab("Signup"):
        with gr.Box(elem_classes="card"):
            s_email = gr.Textbox(label="Email")
            s_pass = gr.Textbox(label="Password", type="password")
            s_btn = gr.Button("Create Account")
            s_msg = gr.Markdown()
            s_btn.click(signup, inputs=[s_email, s_pass], outputs=s_msg)

    # Login Tab
    with gr.Tab("Login"):
        with gr.Box(elem_classes="card"):
            l_email = gr.Textbox(label="Email")
            l_pass = gr.Textbox(label="Password", type="password")
            l_btn = gr.Button("Login")
            l_msg = gr.Markdown()
            l_btn.click(login, inputs=[l_email, l_pass, session], outputs=[l_msg, session])

    # Chat Tab
    with gr.Tab("Chat"):
        with gr.Box(elem_classes="card"):
            chatbot = gr.Chatbot()
            msg = gr.Textbox(label="Message")
            send = gr.Button("Send")
            logout_btn = gr.Button("Logout")
            logout_msg = gr.Markdown()

            send.click(mistral_chat,
                       inputs=[msg, chat_history, session],
                       outputs=[chatbot, chat_history])

            logout_btn.click(logout,
                             inputs=[session],
                             outputs=[logout_msg, session, chatbot, chat_history])

    # History Viewer
    with gr.Tab("Chat History Viewer"):
        with gr.Box(elem_classes="card"):
            history_btn = gr.Button("🔄 Load Chat History")
            history_display = gr.Markdown()

            history_btn.click(load_history,
                              inputs=[session],
                              outputs=[history_display])


port = int(os.environ.get("PORT", 10000))
app.launch()


