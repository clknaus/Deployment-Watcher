#!/usr/bin/env python3
import argparse
import datetime
from enum import Enum
import os
import subprocess
import time
import logging
from email.mime.text import MIMEText
from typing import Callable, Any, List, Optional, Union
from dataclasses import dataclass

class LogLevel(Enum):
    DEBUG = logging.DEBUG
    INFO = logging.INFO
    WARNING = logging.WARNING
    ERROR = logging.ERROR
    CRITICAL = logging.CRITICAL

# ----------------------------------------
# Data Structures
# ----------------------------------------
@dataclass
class Task:
    command: List[str]
    expected_output: Optional[List[str]] = None
    retry_output: Optional[List[str]] = None
    
    def __str__(self):
        cmd_str = " ".join(self.command)
        if self.expected_output:
            output_str = " AND ".join(f"'{s}'" for s in self.expected_output)
            return f"CMD: '{cmd_str}' [Expects to proceed: {output_str}]"
        return f"CMD: '{cmd_str}' [Expects: Exit Code 0]"

# ----------------------------------------
# Custom Argument Parsing
# ----------------------------------------
class StoreTaskAction(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        tasks = getattr(namespace, 'tasks', [])
        if tasks is None:
            tasks = []
            
        if option_string == '--cmd':
            if not isinstance(values, list) or len(values) != 1:
                 raise argparse.ArgumentError(self, "A single command string must be provided for --cmd.")
            command_string = values[0]
            command_list = command_string.split() 
            tasks.append(Task(command=command_list, expected_output=None, retry_output=None))
        elif option_string == '--output':
            if not tasks:
                raise argparse.ArgumentError(self, "--output cannot be used before a --cmd")
            tasks[-1].expected_output = values
        elif option_string == '--retry-output':
            if not isinstance(values, list) or len(values) != 1:
                    raise argparse.ArgumentError(self, "A single retry string must be provided for --retry-output.")
            tasks[-1].retry_output = [values[0]]
            
        setattr(namespace, 'tasks', tasks)

# ----------------------------------------
# Retry Logic
# ----------------------------------------
def retry(func: Callable[[], Any], max_attempts: int, base_delay: int, interval: int, logger: logging.Logger, task: Task) -> Any:
    attempts = 0
    while attempts < max_attempts:
        try:
            output = func()
            if task.retry_output and [s for s in task.retry_output if s in output.stdout.strip()]:
                time.sleep(interval)
                continue
            if task.expected_output and not [s for s in task.expected_output if s in output.stdout.strip()]:
                raise ValueError(f"Output validation failed due to missmatch in contains that was expected: {task.expected_output}\n Output: {output}")
            if output.returncode != 0:
                raise ValueError(f"Output return code failed, return code: {output.returncode}")
                                 
            return
        
        except Exception as e:
            attempts += 1
            delay = base_delay ** attempts
            try_log(logger, f"{task.command} failed (attempt {attempts}/{max_attempts}): {e}", LogLevel.WARNING)
            time.sleep(delay)
    raise RuntimeError(f"{task.command} failed after {max_attempts} attempts")


# ----------------------------------------
# Generic Command Wrapper
# ----------------------------------------
def run_command(command: List[str], cwd: str) -> Callable[[], str]:
    def _command():
        result = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            check=True, #checks on Exit Code: 0
        )
        
        return result
    return _command

# ----------------------------------------
# Logging & Email Helpers
# ----------------------------------------
def try_log(logger : logging.Logger, message: str, level: LogLevel):
    try:
        match level:
            case LogLevel.DEBUG: logger.debug(message)
            case LogLevel.INFO: logger.info(message)
            case LogLevel.WARNING: logger.warning(message)
            case LogLevel.ERROR: logger.error(message)
            case LogLevel.CRITICAL: logger.critical(message)
            case _: logger.log(logging.NOTSET, message)
    except Exception as e:
        print(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {message}")

def send_email(error_msg: str, subject: str, email_recipient: str, email_sender: str, logger: logging.Logger):
    try:
        msg = MIMEText(error_msg)
        msg["Subject"] = subject
        msg["From"] = email_sender
        msg["To"] = email_recipient
        with subprocess.Popen(["/usr/sbin/sendmail", "-t", "-oi"], stdin=subprocess.PIPE) as p:
            p.communicate(msg.as_string().encode("utf-8"))
    except Exception as e:
        try_log(logger, f"Failed to send email: {e}", LogLevel.ERROR)

# ----------------------------------------
# Main Loop
# ----------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Sequential Command Poller")
    
    # Config
    parser.add_argument("--repo-dir", default=os.getenv("REPO_DIR", "./app"))
    parser.add_argument("--interval", type=int, default=int(os.getenv("INTERVAL", "60")))
    parser.add_argument("--log-file", default=os.getenv("LOG_FILE", "error.log"))
    parser.add_argument("--error-email-recipient", default=os.getenv("ERROR_EMAIL_RECIPIENT", ""))
    parser.add_argument("--error-email-sender", default=os.getenv("ERROR_EMAIL_SENDER", ""))
    parser.add_argument("--exit-on-max-attempts", action="store_true", default=os.getenv("EXIT_ON_MAX_ATTEMPTS", "false").lower() in ("1","true","yes"))
    parser.add_argument("--max-attempts", type=int, default=int(os.getenv("MAX_ATTEMPTS", "5")))
    parser.add_argument("--base-delay", type=int, default=int(os.getenv("BASE_DELAY", "2")))
    
    # Commands
    parser.add_argument("--cmd", nargs=1, action=StoreTaskAction, dest='tasks', help="Command to execute (as a single quoted string).")
    parser.add_argument("--output", nargs='+', action=StoreTaskAction, dest='tasks', help="List of validation strings. Used as 'success validation'.")
    parser.add_argument("--retry-output", nargs=1, action=StoreTaskAction, dest='tasks', help="Retry condition on Command output.")
    
    args = parser.parse_args() 

    # Logging Setup
    handlers = [logging.StreamHandler()]
    try:
        log_dir = os.path.dirname(args.log_file)
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir)
        handlers.append(logging.FileHandler(args.log_file, mode="a"))
    except Exception as e:
        print(f"⚠️ Failed to create file handler: {e}")
        return
    
    logger = logging.getLogger(__name__)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s", handlers=handlers)

    if not hasattr(args, 'tasks') or not args.tasks:
        try_log(logger, "No arguments provided, using default command chain.", LogLevel.INFO)
        args.tasks = [
            Task(command=["git pull origin main"], expected_output=["files changed"], retry_output=["Already up to date."]),
            Task(command=["docker compose build"], expected_output=None),
            Task(command=["docker compose --profile prod up -d"], expected_output=[''])
        ]

    consecutive_failures = 0

    while True:
        try:
            # ---------------------------------------------------------
            # Logic: Consecutively Run Command Chain.
            # ---------------------------------------------------------
            for i, task in enumerate(args.tasks):
                retry(
                    run_command(task.command, cwd=args.repo_dir),
                    max_attempts=args.max_attempts, base_delay=args.base_delay, interval=args.interval, logger=logger, task=task
                )

            consecutive_failures = 0 

        except RuntimeError as e_runtimError:
            try_log(logger, f"RuntimError: {e_runtimError}", LogLevel.ERROR)
            if bool(args.error_email_recipient):
                send_email(f"Error: {e_runtimError}", "Command Chain Failed", args.error_email_recipient, args.error_email_sender, logger)
            raise RuntimeError(e_runtimError)
        
        except Exception as e:
            consecutive_failures += 1
            try_log(logger, f"Cycle failed ({consecutive_failures}/{args.max_attempts}): {e}", LogLevel.ERROR)
            
            if consecutive_failures >= args.max_attempts:
                if bool(args.error_email_recipient):
                    send_email(f"Error: {e}", "Command Chain Failed", args.error_email_recipient, args.error_email_sender, logger)
                if args.exit_on_max_attempts:
                    raise RuntimeError("Max attempts reached.")

        time.sleep(args.interval)

if __name__ == "__main__":
    main()