"""Public keys that sign SerOps Enterprise license keys (Ed25519, base64).

The private key never enters this repository. To rotate, add the new public
key here, ship a release, sign new licenses with the new key, and remove the
old key once every license signed with it has expired.
"""

PUBLIC_KEYS = [
    '33wf3AnfNieya3OlYqQsWxAx+QHqvuZREERzziXi29M=',  # 2026-10-21
]
