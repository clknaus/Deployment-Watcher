#!/usr/bin/env python3
import argparse
import os
import subprocess
import time
import logging
from email.mime.text import MIMEText

# ----------------------------------------
# Retry with exponential base^n backoff
# ----------------------------------------
def retry(func, max_attempts, base_delay, task_name="task"):
    attempts = 0
    while attempts < max_attempts:
        try:
            return func()
        except Exception as e:
            attempts += 1
            delay = base_delay ** attempts
            logging.warning(f"{task_name} failed (attempt {attempts}/{max_attempts}): {e}")
            time.sleep(delay)
    raise RuntimeError(f"{task_name} failed after {max_attempts} attempts")

# ----------------------------------------
# Git + Docker logic
# ----------------------------------------
def git_pull(repo_dir, branch, remote):
    def _pull():
        result = subprocess.run(
            ["git", "pull", remote, branch],
            cwd=repo_dir,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout
    return _pull

def docker_compose_up(repo_dir):
    def _compose():
        subprocess.run(
            ["docker-compose", "build"],
            cwd=repo_dir,
            check=True,
        )
        subprocess.run(
            ["docker-compose", "up", "-d"],
            cwd=repo_dir,
            check=True,
        )
    return _compose

# ----------------------------------------
# Error handling
# ----------------------------------------
def send_email(error_msg: str, subject: str, email_recipient: str, email_sender: str):
    missing = {
        "error_msg": error_msg,
        "email_recipient": email_recipient,
        "subject": subject,
        "email_sender": email_sender,
    }

    if not all(missing.values()):
        for name, value in missing.items():
            if not value:
                logging.error(f"missing parameter {name}")
        return

    try:
        msg = MIMEText(error_msg)
        msg["Subject"] = subject
        msg["From"] = email_sender
        msg["To"] = email_recipient

        # Uses local sendmail
        with subprocess.Popen(["/usr/sbin/sendmail", "-t", "-oi"], stdin=subprocess.PIPE) as p:
            p.communicate(msg.as_string().encode("utf-8"))
    except Exception as e:
            logging.error(f"Failed to send email: {e}")

# ----------------------------------------
# Main loop
# ----------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Git + Docker poller")
    parser.add_argument("--repo-dir", default=os.getenv("REPO_DIR", "/app/repo"))
    parser.add_argument("--branch", default=os.getenv("BRANCH", "main"))
    parser.add_argument("--remote", default=os.getenv("REMOTE", "origin"))
    parser.add_argument("--interval", type=int, default=int(os.getenv("INTERVAL", "60")))
    parser.add_argument("--error-email-recipient", default=os.getenv("ERROR_EMAIL_RECIPIENT", ""))
    parser.add_argument("--error-email-sender", default=os.getenv("ERROR_EMAIL_SENDER", ""))
    parser.add_argument("--log-file", default=os.getenv("LOG_FILE", "/app/error.log"))
    parser.add_argument("--max-attempts", type=int, default=int(os.getenv("MAX_ATTEMPTS", "5")))
    parser.add_argument("--base-delay", type=int, default=int(os.getenv("BASE_DELAY", "2")))
    args = parser.parse_args()

    handlers = [logging.StreamHandler()]

    try:
        handlers.append(logging.FileHandler(args.log_file, mode="a"))
    except Exception as e:
        print(f"⚠️ Failed to create file handler: {e}")
        return

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s: %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(args.log_file, mode="a")
        ]
    )
    
    logging.info("Starting deployment watcher...")
    consecutive_failures = 0

    while True:
        try:
            pull_output = retry(
                git_pull(args.repo_dir, args.branch, args.remote),
                max_attempts=args.max_attempts,
                base_delay=args.base_delay,
                task_name="git pull"
            )

            if "Already up to date." not in pull_output:
                logging.info("Changes detected, rebuilding containers...")
                retry(
                    docker_compose_up(args.repo_dir),
                    max_attempts=args.max_attempts,
                    base_delay=args.base_delay,
                    task_name="docker-compose"
                )
            consecutive_failures = 0  # reset after success

        except Exception as e:
            consecutive_failures += 1
            logging.warning(f"Deployment attempt failed ({consecutive_failures}/{args.max_attempts}): {e}")
            if consecutive_failures >= args.max_attempts:
                send_email(
                    error_msg=f"Deployment failed {args.max_attempts} times in a row: {e}", 
                    subject="Deployment failed", 
                    email_recipient=args.error_email_recipient, 
                    email_sender=args.error_email_sender or "error@localhost"
                )
                consecutive_failures = 0  # reset after logging/email

        time.sleep(args.interval)

if __name__ == "__main__":
    main()
