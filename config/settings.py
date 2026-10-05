import os
from dotenv import load_dotenv

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-flash-lite-latest")
NOVA_SYSTEM_PROMPT = os.getenv(
    "NOVA_SYSTEM_PROMPT",
    "You are Nova, a friendly and precise AI assistant. Keep answers clear and concise.",
)

if not GEMINI_API_KEY:
    raise RuntimeError("GEMINI_API_KEY is missing. Add it to your .env file.")
