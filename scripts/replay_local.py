"""Pull a captured hook from the deployed inbox and send it to a local URL.

Usage:
  INBOX_URL=https://your-inbox.vercel.app ADMIN_TOKEN=... \
    python scripts/replay_local.py 42 http://localhost:8000/webhooks/shopify
"""

import base64
import os
import sys

import httpx

SKIP = {"host", "content-length", "connection", "accept-encoding", "transfer-encoding"}
SKIP_PREFIXES = ("x-vercel-", "x-forwarded-", "x-real-ip", "forwarded", "cf-")


def main() -> None:
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    hook_id, target = sys.argv[1], sys.argv[2]
    inbox = os.environ["INBOX_URL"].rstrip("/")
    auth = ("admin", os.environ["ADMIN_TOKEN"])

    hook = httpx.get(f"{inbox}/api/hooks/{hook_id}", auth=auth, timeout=15).raise_for_status().json()
    body = base64.b64decode(hook["body"]) if hook["body_is_base64"] else hook["body"].encode()
    headers = {
        k: v for k, v in hook["headers"].items()
        if k.lower() not in SKIP and not k.lower().startswith(SKIP_PREFIXES)
    }
    headers["x-replayed-from"] = f"webhook-inbox/{hook_id}"

    r = httpx.request(hook["method"], target, headers=headers, content=body, timeout=30)
    print(f"{hook['method']} {target} -> HTTP {r.status_code}")
    print(r.text[:2000])


if __name__ == "__main__":
    main()
