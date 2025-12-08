# Git + Docker Deployment Watcher

## Purpose
This script continuously monitors a Git repository for changes and automatically rebuilds and starts Docker containers using `docker-compose` when updates are detected. It is designed for long-running, fault-tolerant deployments, with retry logic and error notifications.

Key features:
- Periodically pulls a specified Git branch.
- Detects changes and rebuilds Docker containers.
- Retries failed operations with exponential backoff.
- Logs errors to a file and can send email notifications on repeated failures.
- Configurable through command-line arguments or environment variables.

---

## External Dependencies
The script requires the following to be installed on the host system:

- **Python 3** (>= 3.6 recommended)
- **Git** (`git` command-line)
- **Docker** and **docker-compose** (`docker-compose` CLI)
- **Sendmail** or equivalent MTA for sending email notifications
- Standard Python modules:
  - `argparse`
  - `os`
  - `subprocess`
  - `time`
  - `logging`
  - `email.mime.text`

---

## Deployment Watcher: Arguments / Environment Variables
The script supports both command-line arguments and environment variables. Environment variables are used as defaults if the corresponding CLI argument is not provided.

| Argument                  | Environment Variable    | Type | Default          | Description                                       |
| ------------------------- | ----------------------- | ---- | ---------------- | ------------------------------------------------- |
| `--repo-dir`              | `REPO_DIR`              | str  | `/app/repo`      | Path to the local Git repository                  |
| `--branch`                | `BRANCH`                | str  | `main`           | Git branch to monitor                             |
| `--remote`                | `REMOTE`                | str  | `origin`         | Git remote name                                   |
| `--interval`              | `INTERVAL`              | int  | `60`             | Polling interval in seconds                       |
| `--error-email-recipient` | `ERROR_EMAIL_RECIPIENT` | str  | `""`             | Recipient email address for failure notifications |
| `--error-email-sender`    | `ERROR_EMAIL_SENDER`    | str  | `""`             | Sender email address for failure notifications    |
| `--log-file`              | `LOG_FILE`              | str  | `/app/error.log` | Path to the log file                              |
| `--exit-on-max-attempts`  | `EXIT_ON_MAX_ATTEMPTS`  | bool | `False`          | Exit the application if max attempts are reached  |
| `--max-attempts`          | `MAX_ATTEMPTS`          | int  | `5`              | Maximum retry attempts per operation              |
| `--base-delay`            | `BASE_DELAY`            | int  | `2`              | Base delay (seconds) for exponential backoff      |

---

## Example Usage

### Deployment Watcher: Using Environment Variables (Docker-friendly)
```bash
export REPO_DIR=/app/repo
export BRANCH=main
export REMOTE=origin
export INTERVAL=30
export ERROR_EMAIL=alerts@example.com
export LOG_FILE=/app/error.log
export MAX_ATTEMPTS=5
export BASE_DELAY=2
```

## ssh_pubadder.sh: Arguments / Environment Variables
Argument	Environment Variable	Type	Default	Description
None	KEY_NAME	string	deploy_key	Base name for the public key file (without .pub). Script looks for ${SSH_DIR}/${KEY_NAME}.pub when PUBLIC_KEY is not set.
None	PUBLIC_KEY	string	empty	Public key content (single-line SSH public key). If set, this value is used instead of reading a .pub file.
None	SSH_DIR	path	$HOME/.ssh	Directory containing the public key file and authorized_keys. Can be used to target a non-standard .ssh location.
None	HOME	path	system user home (from environment or getent)	Fallback home directory used to compute SSH_DIR when SSH_DIR is not provided.
None	AUTHORIZED_KEYS	path	${SSH_DIR}/authorized_keys	Path where the public key will be appended. Documented for clarity; normally not set by users.

---
