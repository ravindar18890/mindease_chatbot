import os
import requests
import gradio as gr
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime

# Load environment variables
load_dotenv()

os.environ["GRADIO_DISABLE_AUDIO"] = "1"

FIREBASE_API_KEY = os.getenv("FIREBASE_API_KEY")
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")

# Firebase REST Auth URLs
FB_SIGNUP = f"https://identitytoolkit.googleapis.com/v1/accounts:signUp?key={FIREBASE_API_KEY}"
FB_SIGNIN = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={FIREBASE_API_KEY}"

# Initialize Firebase Admin SDK
cred = credentials.Certificate("serviceAccountKey.json")
firebase_admin.initialize_app(cred)
db = firestore.client()

# ---------------------- SIGNUP ---------------------- #
def signup(email, password):
    data = {"email": email, "password": password, "returnSecureToken": True}

    try:
        res = requests.post(FB_SIGNUP, json=data)
        res.raise_for_status()
        user = res.json()

        db.collection("users").document(user["localId"]).set({
            "email": email,
            "created_at": datetime.utcnow(),
            "last_login": None
        })

        return "🎉 Signup successful! Please login."

    except Exception:
        return f"❌ Signup Error: {res.json()['error']['message']}"


# ---------------------- LOGIN ---------------------- #
def login(email, password, session):
    data = {"email": email, "password": password, "returnSecureToken": True}

    try:
        res = requests.post(FB_SIGNIN, json=data)
        res.raise_for_status()
        user = res.json()

        session["logged_in"] = True
        session["uid"] = user["localId"]
        session["email"] = user["email"]

        db.collection("users").document(user["localId"]).update({
            "last_login": datetime.utcnow()
        })

        return "✅ Login successful!", session

    except Exception:
        return "❌ Invalid email or password.", session


# ---------------------- SAVE MESSAGE ---------------------- #
def save_message(uid, role, text):
    db.collection("chats").document(uid).collection("messages").add({
        "role": role,
        "text": text,
        "time": datetime.utcnow()
    })


# ---------------------- LOAD CHAT HISTORY ---------------------- #
def load_history(session):
    if not session.get("logged_in"):
        return "❌ Please login first."

    uid = session["uid"]
    docs = (
        db.collection("chats")
        .document(uid)
        .collection("messages")
        .order_by("time")
        .stream()
    )

    history_text = "### 🕒 Chat History\n\n"
    for d in docs:
        msg = d.to_dict()
        time = msg["time"].strftime("%Y-%m-%d %H:%M:%S")
        history_text += f"**[{msg['role']}]** ({time}) → {msg['text']}\n\n"

    return history_text


# ---------------------- MISTRAL CHAT ---------------------- #
def chat_with_mistral(message, history, session):
    if not session.get("logged_in"):
        return "❌ Please login to chat.", history

    try:
        response = requests.post(
            "https://api.mistral.ai/v1/chat/completions",
            headers={"Authorization": f"Bearer {MISTRAL_API_KEY}"},
            json={
                "model": "mistral-small-latest",
                "messages": [{"role": "user", "content": message}],
            },
        )

        reply = response.json()["choices"][0]["message"]["content"]
        history.append(("You: " + message, reply))

        save_message(session["uid"], "user", message)
        save_message(session["uid"], "bot", reply)

        return history, ""

    except Exception as e:
        return history + [("Error", str(e))], ""


# ---------------------- LOGOUT ---------------------- #
def logout(session):
    session["logged_in"] = False
    session["uid"] = None
    session["email"] = None
    return "👋 Logged out.", session, [], ""


# ---------------------- CUSTOM CSS ---------------------- #
CUSTOM_CSS = """
<style>
body { background: #0F172A; font-family: 'Inter', sans-serif; }
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


# ---------------------- GRADIO UI ---------------------- #
with gr.Blocks(css=CUSTOM_CSS) as app:

    session = gr.State({"logged_in": False, "uid": None, "email": None})
    chat_history = gr.State([])

    gr.Markdown("## 💬 Modern AI Chatbot – Firebase Auth + Mistral AI")

    # SIGNUP TAB
    with gr.Tab("Signup"):
        with gr.Box(elem_classes="card"):
            s_email = gr.Textbox(label="Email")
            s_pass = gr.Textbox(label="Password", type="password")
            s_btn = gr.Button("Create Account")
            s_msg = gr.Markdown()
            s_btn.click(signup, [s_email, s_pass], s_msg)

    # LOGIN TAB
    with gr.Tab("Login"):
        with gr.Box(elem_classes="card"):
            l_email = gr.Textbox(label="Email")
            l_pass = gr.Textbox(label="Password", type="password")
            l_btn = gr.Button("Login")
            l_msg = gr.Markdown()
            l_btn.click(login, [l_email, l_pass, session], [l_msg, session])

    # CHAT TAB
    with gr.Tab("Chat"):
        with gr.Box(elem_classes="card"):
            chatbot = gr.Chatbot(height=450)
            msg = gr.Textbox(label="Type your message...")
            send = gr.Button("Send")
            log_btn = gr.Button("Logout")
            log_msg = gr.Markdown()

            send.click(chat_with_mistral, [msg, chatbot, session], [chatbot, msg])
            log_btn.click(logout, session, [log_msg, session, chatbot, chat_history])

    # HISTORY TAB
    with gr.Tab("Chat History"):
        with gr.Box(elem_classes="card"):
            h_btn = gr.Button("Load History")
            h_display = gr.Markdown()
            h_btn.click(load_history, session, h_display)

if __name__ == "__main__":
    app.launch(
        server_name="0.0.0.0",
        server_port=int(os.environ.get("PORT", 10000)),
        show_error=True,
        share=False,
        inbrowser=False
    )

