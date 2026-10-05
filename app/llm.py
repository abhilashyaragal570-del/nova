import time
from google import genai
from google.genai import errors
from config import settings

client = genai.Client(api_key=settings.GEMINI_API_KEY)

MODEL = "gemini-flash-lite-latest"
MAX_RETRIES = 5


def ask(prompt: str) -> str:
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.models.generate_content(model=MODEL, contents=prompt)
            return response.text
        except errors.ServerError as e:
            if attempt == MAX_RETRIES:
                raise
            wait = 2 ** attempt
            print(f"Server busy ({e.code}). Retry {attempt}/{MAX_RETRIES} in {wait}s...")
            time.sleep(wait)
