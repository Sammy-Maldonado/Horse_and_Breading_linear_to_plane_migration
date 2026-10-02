# Public GitHub Publication Checklist

Run this checklist before making the migration toolkit public.

## 1. Secrets

Confirm `.env` is ignored and untracked:

```bash
git check-ignore .env
git status --short
```

Search tracked files for likely credentials or local secrets before the first public push. At minimum review occurrences of:

```text
LINEAR_API_KEY
PLANE_API_KEY
Authorization
Bearer
SECRET_KEY
POSTGRES_PASSWORD
DATABASE_URL
```

Do not rely only on `.gitignore`: anything already committed remains in Git history until explicitly removed.

## 2. Personal identity

The original migration used a specific Linear/Plane assignee identity. Before publication, inspect `scripts/import_plane_assignees.py` and remove any hardcoded personal email, user ID, workspace ID, or account-specific value.

Prefer environment/configuration values or values discovered from the source/target APIs.

Do not publish personal email addresses merely because they are not authentication secrets.

## 3. Generated artifacts

Verify `backups/` is ignored:

```bash
git check-ignore backups/
```

The repository must not include:

- Linear source backups;
- mapping JSON files;
- historical metadata exports;
- final audit output from a private migration;
- PostgreSQL dumps;
- API-response dumps containing private project data.

## 4. Local machine paths

Search for local paths such as:

```text
C:\Users\
/mnt/data/
/home/
Desktop/
```

Documentation and scripts should use project-relative paths or placeholders.

## 5. IDs and account-specific constants

Review tracked files for hardcoded:

- Plane workspace UUIDs;
- Plane project UUIDs;
- Linear team UUIDs;
- Linear project UUIDs;
- user UUIDs;
- account emails.

The public toolkit should obtain these from `.env`, source APIs, migration mappings, or explicit configuration.

## 6. Syntax-only validation

Before publishing, compile every Python script without executing migration writes:

```bash
python -m compileall scripts
```

On Windows with the Python launcher:

```powershell
py -m compileall scripts
```

## 7. Current-working-directory independence

The scripts should resolve project paths from `Path(__file__)`, not from the terminal's current directory.

Test at least one read-only script from the repository root and from another directory.

## 8. Do not rerun writes merely for publication

The completed production migration has already passed its final audit. Do not rerun import scripts just to prepare the GitHub repository.

Use syntax checks, static inspection, and disposable test projects for publication validation.

## 9. README and migration record

Confirm that public documentation:

- explains what is preserved;
- explains what cannot be represented natively;
- documents the Plane v1.4.2 reply-parent repair;
- documents exact-number preservation through ordered creation;
- explains the final audit;
- does not expose private source content.

## 10. Final Git review

Before the first public push:

```bash
git status
git diff --cached
git ls-files
```

Manually inspect the complete tracked-file list.

The repository is ready to publish only when the tracked set contains source code and public documentation, not private migration data.
