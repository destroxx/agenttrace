"""Make a new admin key and print it with the hash the API is configured with.

    python -m scripts.new_admin_key

The key goes to whoever administers the API; the hash goes into
ADMIN_KEY_SHA256 in apps/api/.env (or the host's environment). The API never
sees the key at rest, only the hash, so the environment alone cannot be used
to call it.
"""

from __future__ import annotations

from app.services.api_keys import generate_key, hash_key


def main() -> None:
    key = generate_key()
    print(f"admin key (keep it secret):   {key}")
    print(f"ADMIN_KEY_SHA256={hash_key(key)}")


if __name__ == "__main__":
    main()
