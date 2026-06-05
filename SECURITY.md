# Security Policy

## Do Not Commit Or Share Secrets

Never commit or share:

- `config.toml`
- `config.realtest.toml`
- `.env`
- Feishu `app_secret`
- Vision API keys
- Claude credentials
- Runtime `data/` or `data-test/`
- Logs under `data/logs/`
- Downloaded images, audio, and attachments

Use `config.example.toml` and `.env.example` as templates.

## Runtime Logs

The bridge records operational logs and message flow. `messages.log` can contain chat content. `audit.jsonl` can contain local paths and security decisions. Treat all runtime logs as private.

## Permission Profiles

Prefer:

- `readonly` for read-only usage.
- `safe` for normal group usage.
- `dev` only for trusted development groups.

Use `admin` / `bypassPermissions` only for highly trusted local testing or maintenance. It can allow Claude CLI to perform high-impact operations.

## Path Rules

Set `allowed_paths` narrowly. Do not grant whole-disk access in production groups unless every group member is trusted.

## Feishu Permissions

Grant only the permissions required by the enabled features. If group-history media lookup is not needed, do not grant `im:message.group_msg`.

## Incident Response

If a key is exposed:

1. Stop the bridge.
2. Revoke or rotate the exposed key in Feishu or the model provider.
3. Delete affected logs or runtime data before sharing diagnostics.
4. Restart with a new config.
