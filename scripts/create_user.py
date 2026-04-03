"""
Generate a PBKDF2 password hash for secrets.yaml.

Usage:
    python scripts/create_user.py <username> <password>

Output — paste this into secrets.yaml under the 'users' key:

    users:
      <username>:
        password_hash: "<hash>"
"""

import sys
sys.path.insert(0, ".")
from api.routes.auth import hash_password

if len(sys.argv) != 3:
    print(__doc__)
    sys.exit(1)

username, password = sys.argv[1], sys.argv[2]
h = hash_password(password)
print(f"\nAdd to secrets.yaml:\n\n  users:\n    {username}:\n      password_hash: \"{h}\"\n")
