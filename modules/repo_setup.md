# Repo Setup: identity, credentials, remotes

Load when wiring a new repo or clone, before a first push/fetch, or whenever git
identity or credentials are in doubt. This module is procedure only — the actual names,
emails, and tokens live in org-level instruction files and each project's `.env`, never
in this framework.

## Identity

- Identity is per-repo: `git config --local` only; never touch global git config or
  global credential files.
- `user.name` = first name only (no surname). `user.email` = the org's expected email
  from the parent folder's instruction file — a GitHub noreply address outside personal
  orgs. Company emails never go in commits.
- Verify `git config --local user.email` matches the org's expected value before every
  commit; a mismatch or empty value → stop and warn, do not commit.
- Never assume sibling projects share an account or token; a subproject whose expected
  email differs from its parent folder's → flag before using its credentials.
- Keep account/org separation out of user-visible output — warnings stay generic.

## Credentials

- Project secrets live in the project's `.env` (gitignored): `source .env`, then refer
  to values only by variable name.
- Per-repo credential store:
  `git config --local credential.helper 'store --file=.git/.git-credentials'`, then
  populate from the project's own token:
  `source .env && echo "https://x-access-token:${GITHUB_TOKEN}@github.com" > .git/.git-credentials && chmod 600 .git/.git-credentials`
- Before any push/pull/fetch: helper configured and store non-empty, else set it up
  first. Never bypass with an inline token URL; never parse `.git-credentials` directly.

## GitHub CLI (`gh`) — project token only

- `gh` reads `GH_TOKEN` / `GITHUB_TOKEN` from the env before its own login file, so
  `source .env && gh pr create ...` acts with THIS repo's token. That is the only way
  to use it; `gh` is deliberately never logged in.
- NEVER `gh auth login | setup-git | switch | refresh | token`: a login is one global
  token for every folder, and `setup-git` installs a global git credential helper that
  git asks before the repo's own store — both silently override per-repo credentials.
  `token` prints the secret. Claude Code denies these via `global/hooks/guard_gh_auth.py`
  (it matches the text anywhere in a Bash command, heredocs included — write docs that
  quote them with the Edit tool); other harnesses rely on this rule. `gh auth status`
  is fine.
- Clone with `git clone` + the Credentials steps above, not `gh repo clone`.
- Health check: `~/.config/gh/hosts.yml` absent and
  `git config --global --get-all credential.helper` empty.
- Raw API call without gh: `source .env && curl -s -H "Authorization: token $GITHUB_TOKEN" https://api.github.com/...`
- Scheduled push via cron: absolute paths (`git -C /abs/path push origin main
  >>/tmp/<repo>-push.log 2>&1`), dry-run scheduled first, one-shot entries removed
  after they fire.
