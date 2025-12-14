#!/usr/bin/env python3
import argparse
import datetime
from email import parser
from enum import Enum
import os
import subprocess
import time
import logging
from email.mime.text import MIMEText
from typing import Callable, Any

parser.add_argument("--exit-on-max-attempts", action="store_true", default=os.getenv("EXIT_ON_MAX_ATTEMPTS", "false").lower() in ("1","true","yes"))

class LogLevel(Enum):
    DEBUG = logging.DEBUG
    INFO = logging.INFO
    WARNING = logging.WARNING
    ERROR = logging.ERROR
    CRITICAL = logging.CRITICAL
    
# ----------------------------------------
# Retry with periodically exponential base_delay^attempts backoff
# ----------------------------------------
def retry(func: Callable[[], Any], max_attempts: int, base_delay: int, logger: logging.Logger, task_name: str = "task") -> Any:
    attempts = 0
    while attempts < max_attempts:
        try:
            return func()
        except Exception as e:
            attempts += 1
            delay = base_delay ** attempts
            try_log(logger, f"{task_name} failed (attempt {attempts}/{max_attempts}): {e}", LogLevel.WARNING)
            time.sleep(delay)
    raise RuntimeError(f"{task_name} failed after {max_attempts} attempts")


# ----------------------------------------
# Git + Docker logic
# ----------------------------------------
def git_pull(repo_dir: str, branch: str, remote: str):
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
# Error handling: safe try
# ----------------------------------------
def try_log(logger : logging.Logger, message: str, level: LogLevel):
    try:
        match level:
            case LogLevel.DEBUG:
                logger.debug(message)
            case LogLevel.INFO:
                logger.info(message)
            case LogLevel.WARNING:
                logger.warning(message)
            case LogLevel.ERROR:
                logger.error(message)
            case LogLevel.CRITICAL:
                logger.critical(message)
            case _:
                logger.log(logging.NOTSET, message)
    except Exception as e:
        print(f"Failed to log with exception: {e}")
        print(f"{datetime.now().strftime("%Y-%m-%d %H:%M:%S")} {message}")

# ----------------------------------------
# Error handling: send Email
# ----------------------------------------
def send_email(error_msg: str, subject: str, email_recipient: str, email_sender: str, logger: logging.Logger):
    try:
        msg = MIMEText(error_msg)
        msg["Subject"] = subject
        msg["From"] = email_sender
        msg["To"] = email_recipient

        # Uses local sendmail
        with subprocess.Popen(["/usr/sbin/sendmail", "-t", "-oi"], stdin=subprocess.PIPE) as p:
            p.communicate(msg.as_string().encode("utf-8"))
        try_log(logger, f"Email has been sent successfully.", LogLevel.INFO)
    except Exception as e:
        try_log(logger, f"Failed to send email: {e}", LogLevel.ERROR)

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
    parser.add_argument("--exit-on-max-attempts", type=bool, default=bool(os.getenv("EXIT_ON_MAX_ATTEMPTS", False)))
    parser.add_argument("--max-attempts", type=int, default=int(os.getenv("MAX_ATTEMPTS", "5")))
    parser.add_argument("--base-delay", type=int, default=int(os.getenv("BASE_DELAY", "2")))
    args = parser.parse_args()       

    # ----------------------------------------
    # Initialization & Boundary check
    # ----------------------------------------
    handlers = [logging.StreamHandler()]

    try:
        handlers.append(logging.FileHandler(args.log_file, mode="a"))
    except Exception as e:
        print(f"⚠️ Failed to create file handler: {e}")
        return

    logger = logging.getLogger(__name__)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s: %(message)s",
        handlers=handlers
    )

    max_attempts_limit = 0
    if args.max_attempts < max_attempts_limit:
        error_message = f"{args.max_attempts} < {max_attempts_limit}"
        try_log(logger, error_message, LogLevel.ERROR)
        raise RuntimeError(error_message)

    base_delay_limit = 2
    if args.base_delay < 2:
        error_message = f"{args.base_delay} < {base_delay_limit}"
        try_log(logger, error_message, LogLevel.ERROR)
        raise RuntimeError(error_message)
    
    if not bool(args.error_email_recipient):
        try_log(logger, "Parameter error_email_recipient is invalid. Emails won't be sent.", LogLevel.WARNING)
    
    try_log(logger, "Starting deployment watcher...", LogLevel.INFO)

    # ----------------------------------------
    # Application Logic
    # ----------------------------------------
    consecutive_failures = 0

    while True:
        try:
            pull_output = retry(
                git_pull(args.repo_dir, args.branch, args.remote),
                max_attempts=args.max_attempts,
                base_delay=args.base_delay,
                logger=logger,
                task_name="git pull"
            )

            if "Already up to date." not in pull_output:
                try_log(logger, "Changes detected, rebuilding containers...", LogLevel.INFO)
                retry(
                    docker_compose_up(args.repo_dir),
                    max_attempts=args.max_attempts,
                    base_delay=args.base_delay,
                    logger=logger,
                    task_name="docker-compose"
                )
            consecutive_failures = 0  # reset after success

        except Exception as e:
            consecutive_failures += 1
            try_log(logger, f"Deployment attempt failed ({consecutive_failures}/{args.max_attempts}): {e}", LogLevel.ERROR)
            if consecutive_failures >= args.max_attempts:
                if bool(args.error_email_recipient):
                    send_email(
                        error_msg=f"Deployment failed {args.max_attempts} times in a row: {e}", 
                        subject="Deployment failed", 
                        email_recipient=args.error_email_recipient, 
                        email_sender=args.error_email_sender or "error@localhost",
                        logger=logger
                    )
                if args.exit_on_max_attempts:
                    RuntimeError("Max attempts reached... Exiting Application.")
                consecutive_failures = 0

        time.sleep(args.interval)

if __name__ == "__main__":
    main()
