"""One-time script to register the entity secret hash with Circle.

Run once before any wallet creation:
    python scripts/register_circle_entity_secret.py
"""

import hashlib
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

api_key = os.getenv("CIRCLE_API_KEY", "")
entity_secret = os.getenv("CIRCLE_ENTITY_SECRET", "")

if not api_key or not entity_secret:
    print("ERROR: CIRCLE_API_KEY and CIRCLE_ENTITY_SECRET must be set in .env")
    sys.exit(1)

secret_bytes = bytes.fromhex(entity_secret.removeprefix("0x"))
secret_hash = hashlib.sha512(secret_bytes).hexdigest()

r = httpx.put(
    "https://api.circle.com/v1/w3s/config/entity/secretHash",
    headers={
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    },
    json={"hashAlgorithm": "SHA-512", "entitySecretHash": secret_hash},
    timeout=15,
)

print(f"Status: {r.status_code}")
print(r.text)

if r.status_code in (200, 201):
    print("\nEntity secret registered. You can now create Circle wallets.")
elif r.status_code == 409:
    print("\nAlready registered — nothing to do.")
else:
    print("\nFailed. Check your CIRCLE_API_KEY and CIRCLE_ENTITY_SECRET.")
