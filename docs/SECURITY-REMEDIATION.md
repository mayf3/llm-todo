# Security remediation / incident response

This public repository must not contain the data/ runtime state, including
accounts, agent tokens, sessions, tasks, personal history, and backups.

Mandatory operator actions after pulling this security patch:

1. Treat every agent/account token from the previously committed data/agents.json
   and historical backups as compromised. Rotate tokens in the actual running
   service and all clients. Deleting Git files does not revoke a token.
2. Invalidate old JWT sessions. Newly issued JWTs have a 24-hour expiry; all
   older JWTs without exp are rejected after deployment.
3. Restart with an externally generated private LLM_TODO_TOKEN, preferably
   also a separate LLM_TODO_JWT_SECRET. Without a token the server will refuse
   to start (it no longer permits anonymous API access).
4. Review service logs for suspicious access and agent logins.
5. Purge affected data paths from historical Git commits, every branch/tag and
   reachable releases. Historic commits can remain accessible via forks/caches
   even after a normal deletion commit. Consider GitHub Support assistance.
6. Keep private data on protected local storage, never in source control.
   The .gitignore rule only prevents NEW, untracked files.

## Defense in depth

The server also refuses all credentials whose SHA-256 digests match the
historically exposed agent/account tokens and the archived mobile shared
token. This denylist does NOT rotate credentials in other services or remove
GitHub history. After deployment, provision replacement tokens and invalidate
all old sessions. Do not restore these values from an old backup.
