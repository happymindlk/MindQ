from pydantic import BaseModel
from fastapi import APIRouter, Request

from app.security import enforce_rate_limit, public_limiter

router = APIRouter()


class ChatMessage(BaseModel):
    message: str


class ChatReply(BaseModel):
    reply: str


# Pre-defined FAQ knowledge base with keyword matching
FAQ_ENTRIES = [
    {
        "keywords": ["hello", "hi", "hey", "good morning", "good afternoon"],
        "reply": "Hello! I'm your Assess Pulse assistant. How can I help you today? You can ask me about getting started, access codes, test duration, or anything else!"
    },
    {
        "keywords": ["start", "begin", "how do i", "get started", "first step"],
        "reply": "To get started, enter your access code (format: HM-XXXX-X) and your email address on the login page. Once logged in, you'll see your assessment dashboard with all available tests."
    },
    {
        "keywords": ["access code", "code", "hm-", "login code", "where is my code"],
        "reply": "Your access code was provided by your organization or HR department. It follows the format HM-XXXX-X (e.g., HM-A7K2-B). If you haven't received one, please contact your organization administrator."
    },
    {
        "keywords": ["how long", "duration", "time", "minutes", "hours"],
        "reply": "Each test typically takes 15–30 minutes to complete. Your progress is saved automatically every few seconds, so you won't lose any work if you need to take a break."
    },
    {
        "keywords": ["save", "autosave", "progress", "lose", "lost"],
        "reply": "Don't worry! Your responses are automatically saved every 5 seconds as you work. You can safely close the browser and return later — your progress will be right where you left off."
    },
    {
        "keywords": ["stuck", "help", "problem", "issue", "error", "bug"],
        "reply": "I'm sorry you're having trouble! Try refreshing the page first. If the issue persists, please contact your organization administrator with a description of the problem."
    },
    {
        "keywords": ["submit", "finish", "complete", "done", "end"],
        "reply": "When you're ready, click the Submit button on the test page. Once submitted, you cannot change your answers. Make sure you've reviewed everything before submitting!"
    },
    {
        "keywords": ["score", "result", "results", "grade", "feedback"],
        "reply": "Your results are processed after you complete all assigned tests. Your organization administrator will share your results with you according to their process."
    },
    {
        "keywords": ["password", "forgot", "reset", "account"],
        "reply": "Candidates don't need a password — just your access code and email. If you're an HR user, use the password reset option on the login page or contact your admin."
    },
    {
        "keywords": ["privacy", "data", "secure", "confidential", "gdpr"],
        "reply": "Your data is handled with strict confidentiality. All responses are stored securely and only accessible by authorized administrators within your organization. We take your privacy seriously."
    },
]


@router.post("/message", response_model=ChatReply)
async def chat_message(chat: ChatMessage, request: Request):
    """Simple FAQ chatbot with keyword matching."""
    enforce_rate_limit(public_limiter, request, "chat_message")
    msg = chat.message.lower().strip()

    best_match = None
    best_score = 0

    for entry in FAQ_ENTRIES:
        score = sum(1 for kw in entry["keywords"] if kw in msg)
        if score > best_score:
            best_score = score
            best_match = entry

    if best_match and best_score > 0:
        return ChatReply(reply=best_match["reply"])

    return ChatReply(
        reply="I'm not sure about that. You can ask me about getting started, access codes, test duration, saving progress, or submitting tests. For other questions, please contact your organization administrator."
    )
