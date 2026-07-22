import os

from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_SECRET_KEY")

if not url:
    raise RuntimeError("SUPABASE_URL not found")

if not key:
    raise RuntimeError("SUPABASE_SECRET_KEY not found")

client = create_client(url, key)

print("✅ Successfully connected to Supabase!")