import os
from dotenv import load_dotenv
import google.generativeai as genai

# Load .env file
load_dotenv()

# Get API key from environment
api_key = os.getenv("GEMINI_API_KEY")

if not api_key:
    raise ValueError("API key not found!")

genai.configure(api_key=api_key)

model = genai.GenerativeModel("gemini-2.5-flash")
response = model.generate_content("Hello Gemini")

print(response.text)