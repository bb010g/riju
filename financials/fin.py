#!/usr/bin/env python3

import argparse
import csv
import decimal
import gzip
import io
import json
import logging
import os
import pathlib
import sys
from urllib.parse import urlparse

import boto3

logging.basicConfig(level=logging.INFO)

ROOT = pathlib.Path(__file__).parent


def die(msg):
    raise AssertionError(msg)


def get_csv(year, month, force_download=False):
    target_dir = ROOT / f"{year}-{month:02d}"
    logging.info(f"Using base directory {target_dir}")
    target_dir.mkdir(exist_ok=True)
    latest_csv = target_dir / "latest.csv"
    if force_download or not latest_csv.exists():
        try:
            latest_csv.unlink()
        except FileNotFoundError:
            pass
        s3 = boto3.client("s3")
        o = urlparse(os.environ["BILLING_REPORTS_URL"], allow_fragments=False)
        assert o.scheme == "s3"
        bucket = o.netloc
        base_prefix = o.path.strip("/") + "/"
        report_name = base_prefix.rstrip("/").split("/")[-1]
        logging.info(f"List s3://{bucket}/{base_prefix}")
        month_prefixes = [
            elt["Prefix"]
            for elt in s3.list_objects_v2(
                Bucket=bucket, Prefix=f"{base_prefix}", Delimiter="/"
            )["CommonPrefixes"]
        ]
        if not month_prefixes:
            die("no report prefixes found")
        expected_month_prefix = f"{base_prefix}{year}{month:02d}"
        matching_month_prefixes = [
            p for p in month_prefixes if p.startswith(expected_month_prefix)
        ]
        if not matching_month_prefixes:
            die(f"no report prefix for the specified month ({expected_month_prefix})")
        if len(matching_month_prefixes) > 1:
            die(f"multiple matching report prefixes: {repr(matching_month_prefixes)}")
        (month_prefix,) = matching_month_prefixes
        stream = io.BytesIO()
        manifest_path = f"{month_prefix}{report_name}-Manifest.json"
        logging.info(f"Download s3://{bucket}/{manifest_path}")
        s3.download_fileobj(bucket, manifest_path, stream)
        manifest = json.loads(stream.getvalue())
        (report_path,) = manifest["reportKeys"]
        if not report_path.endswith(".csv.gz"):
            die(f"unexpected report extension in {report_path}")
        basename = pathlib.Path(report_path).name.removesuffix(".csv.gz")
        logging.info(f"Download s3://{bucket}/{report_path}")
        s3.download_file(bucket, report_path, f"{target_dir}/{basename}.csv.gz")
        logging.info(f"Decompress {basename}.csv.gz")
        with gzip.open(f"{target_dir}/{basename}.csv.gz") as f_read:
            with open(f"{target_dir}/{basename}.csv", "wb") as f_write:
                while chunk := f_read.read(1024):
                    f_write.write(chunk)
        latest_csv.symlink_to(f"{basename}.csv")
    return latest_csv


def read_csv(csv_path):
    rows = []
    with open(csv_path) as f:
        reader = csv.reader(f)
        header = next(reader)
        for row in reader:
            rows.append(dict(zip(header, row)))
    return rows


def classify_costs(csv_path):
    items = read_csv(csv_path)
    for item in items:
        cost = decimal.Decimal(item["lineItem/UnblendedCost"])
        if not cost:
            continue
        breakpoint()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("date")
    parser.add_argument("-f", "--force-download", action="store_true")
    args = parser.parse_args()
    year, month = map(int, args.date.split("-"))
    csv_path = get_csv(year, month, force_download=args.force_download)
    analyze(csv_path)


if __name__ == "__main__":
    main()
    sys.exit(0)
