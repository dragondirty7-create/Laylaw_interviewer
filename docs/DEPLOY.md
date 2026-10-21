# Deploying Laylaw (web)

Not deployed yet. This file lists what a host has to provide and the steps once
one is chosen. **Choosing the host is a data-location decision.** Make it with
the privacy/legal review in `SECURITY.md`, not ad hoc.

## Host requirements (all required)
- **HTTPS only**, via a reverse proxy (Caddy, nginx, or a platform's TLS termination) in front of the app. The session cookie is `Secure`, so sign-in does not work over plain HTTP. That is intentional.
- **A persistent, private disk** for `LAYLAW_DATA_DIR`, encrypted at the volume level. The app adds its own per-client encryption on top.
- **One application process** (threads are fine). The app serializes writes per client with in-process locks.
- **A secret manager** for `LAYLAW_MASTER_KEY`. It must not be stored on the data disk, in the repo, in the image, or in shell history.
- **Encrypted backups** of `LAYLAW_DATA_DIR`, stored separately from the key. Without the key, the backups cannot be read. Without backups, a lost disk means lost data.
- **Restricted operator access.** Anyone who has both the key and the disk can read all client data.

These do **not** fit as-is: serverless functions with ephemeral filesystems, such as Vercel functions or AWS Lambda, and any public or shared object bucket.
Suitable shapes include a small VM or a container platform with an attached encrypted volume (for example Fly.io with a volume, Render with a persistent disk, or a VPS), with a region chosen deliberately.

## Steps
```sh
pip install -e ".[web]"
export LAYLAW_DATA_DIR=/srv/laylaw-data                          # on the encrypted volume
export LAYLAW_MASTER_KEY="$(python -m laylaw.web.admin generate-key)"   # store in the secret manager; never commit
export LAYLAW_TRUST_PROXY=1                                       # only when behind your TLS proxy

python -m laylaw.web.admin create-user <username> --display-name "<first name>"   # prompts for the password
waitress-serve --listen=127.0.0.1:8080 laylaw.web.wsgi:app
```
The proxy forwards `https://<your host>/` to `127.0.0.1:8080` and sets
`X-Forwarded-For`, `X-Forwarded-Proto` and `X-Forwarded-Host`.

## Before any real account
1. Create two synthetic accounts on the deployed instance. Run the checks in
   `HANDOFF.md` ("Deployed smoke test") in the client's own browser and phone.
2. Delete the synthetic accounts' workspaces, or keep them clearly labeled as test data.
3. Only then create the real account. Give the password to the client through a
   separate channel from the username and URL.

## Operator commands
`python -m laylaw.web.admin --help`: `create-user`, `reset-password`, `disable-user`,
`enable-user`, `revoke-sessions`, `list-users`, `confirm-workspace`.
