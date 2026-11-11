# SerOps Enterprise (`ee/`)

Code in this directory (and in `frontend/src/ee/`) is licensed under the
[SerOps Enterprise License](LICENSE),
not the AGPL-3.0 that covers the rest of the repository.

- **SerOps works fully without it.** Delete `backend/ee/` and
  `frontend/src/ee/` and you have the complete Community edition, under the
  AGPL only. CI runs every test that way.
- **Enterprise only adds governance features** for large organisations
  (central identity, compliance, administration at scale). No Community
  feature ever moves here: see the
  [open source promise](https://serops.ai/docs/open-source-promise/).
- **Off until licensed.** Without a valid license key, Enterprise features
  are hidden. When a key expires they switch off; no data is deleted and
  nothing else is blocked.

## License keys

A license key is a JSON document signed with Ed25519, checked offline
against the public keys in `licensing/keys.py`: no license server, no
network call, no telemetry, so it works air-gapped. Install it in
**Settings → Enterprise license** (platform staff, or the admin of a
single-organisation install), or `PUT /api/ee/license/`.

Maintainers sign keys with `python manage.py ee_license_sign` and the
private key, which is never stored in the repository or an image.

## Rules for code here

- Community code never imports `ee`. Ask `Utils.edition.has_feature(code)`
  (backend) or `useEdition()` (frontend) instead.
- Enterprise code may import Community code.
- Feature codes live in `licensing/features.py`.
