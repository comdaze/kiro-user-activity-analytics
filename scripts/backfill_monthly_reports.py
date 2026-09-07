#!/usr/bin/env python3
"""Synchronously backfill Kiro monthly reports, oldest month first."""
import argparse
import json
from datetime import date, datetime

import boto3
from botocore.config import Config
from botocore.exceptions import ReadTimeoutError


def add_month(month: str, delta: int = 1) -> str:
    parsed = datetime.strptime(month, "%Y-%m")
    index = parsed.year * 12 + parsed.month - 1 + delta
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def last_closed_month(today: date | None = None) -> str:
    today = today or date.today()
    return add_month(f"{today.year:04d}-{today.month:02d}", -1)


def month_range(start: str, end: str):
    current = start
    while current <= end:
        yield current
        current = add_month(current)


def validate_range(start: str, end: str, current: str, include_current_partial: bool) -> None:
    for value, label in ((start, "--start"), (end, "--end")):
        try:
            datetime.strptime(value, "%Y-%m")
        except ValueError as exc:
            raise SystemExit(f"{label} must be YYYY-MM") from exc
    if start > end:
        raise SystemExit("--start must not be after --end")
    if end > current:
        raise SystemExit("future months are not allowed")
    if end == current and not include_current_partial:
        raise SystemExit("current month requires --include-current-partial")


def lambda_client_config() -> Config:
    return Config(connect_timeout=10, read_timeout=920, retries={"mode": "standard", "max_attempts": 2})


def build_invocation_payload(month: str, notify: bool, notification_channel: str = "dev") -> dict:
    if notification_channel not in {"dev", "prod", "both"}:
        raise ValueError("notification_channel must be dev, prod, or both")
    return {
        "month": month, "report_type": "final", "notify": bool(notify),
        "notification_channel": notification_channel, "backfill": True,
    }


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--function-name", default="kiro-monthly-credits-report")
    parser.add_argument("--region")
    parser.add_argument("--profile")
    parser.add_argument("--start", default="2026-02")
    parser.add_argument("--end", default=None, help="default: last closed month")
    parser.add_argument("--include-current-partial", action="store_true")
    parser.add_argument("--notify", action="store_true", help="explicitly send Feishu notifications")
    parser.add_argument(
        "--notification-channel", choices=("dev", "prod", "both"), default="dev",
        help="explicit Feishu channel when --notify is used (default: dev)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    end = args.end or last_closed_month()
    current = date.today().strftime("%Y-%m")
    if args.include_current_partial and args.end is None:
        end = current
    validate_range(args.start, end, current, args.include_current_partial)
    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    client = session.client("lambda", config=lambda_client_config())
    for month in month_range(args.start, end):
        payload = build_invocation_payload(month, args.notify, args.notification_channel)
        print(
            f"Invoking {month} (notify={args.notify}, channel={args.notification_channel}) ...",
            flush=True,
        )
        try:
            response = client.invoke(FunctionName=args.function_name, InvocationType="RequestResponse", Payload=json.dumps(payload).encode())
        except ReadTimeoutError as exc:
            raise SystemExit(f"Backfill timed out at {month}; check Lambda logs/S3, then rerun from this month") from exc
        body = response["Payload"].read().decode("utf-8", errors="replace")
        if response.get("FunctionError"):
            print(body)
            raise SystemExit(f"Backfill stopped at {month}: {response['FunctionError']}")
        print(body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
