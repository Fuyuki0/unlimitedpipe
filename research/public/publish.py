"""Publish public-domain records to the Hugging Face dataset unlimitedpipe/public-records.

One year at a time: collect it, write one Parquet file, upload it, delete the local copy
(so a small disk is enough). Statistics per year go to `stats.json` in the dataset, which the
dataset card is built from. Needs `hf auth login` with write access to the organization.

    research/.venv/bin/python research/public/publish.py federal_register 2026 2000
"""

from __future__ import annotations

import io
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

import httpx
import pyarrow as pa
import pyarrow.parquet as pq
from huggingface_hub import HfApi

sys.path.insert(0, str(Path(__file__).resolve().parent))
import federal_register  # noqa: E402
import sec_10k  # noqa: E402

REPO = "unlimitedpipe/public-records"


def read_jsonl_zst(path: Path):
    import zstandard

    with path.open("rb") as raw:
        for line in io.TextIOWrapper(
            zstandard.ZstdDecompressor().stream_reader(raw), encoding="utf-8"
        ):
            yield json.loads(line)


def stats_of(api: HfApi) -> dict:
    try:
        path = api.hf_hub_download(REPO, "stats.json", repo_type="dataset")
        return json.loads(Path(path).read_text())
    except Exception:
        return {}


def federal_register_year(year: int, work: Path, client: httpx.Client) -> tuple[Path, dict]:
    """Collect a year month by month into one Parquet file, a month in memory at a time (a
    busy year is over 90 million words: too much for a small machine at once)."""
    out = work / f"{year}.parquet"
    writer, counts = None, {"documents": 0, "words": 0}
    for month in range(1, 13):
        try:
            got = federal_register.month(year, month, work, client)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                continue  # a month not published yet
            raise
        path = work / got["file"]
        table = pa.Table.from_pylist(list(read_jsonl_zst(path)))
        writer = writer or pq.ParquetWriter(out, table.schema, compression="zstd")
        writer.write_table(table.cast(writer.schema), row_group_size=2000)
        path.unlink()
        counts["documents"] += got["documents"]
        counts["words"] += got["words"]
        time.sleep(2)
    if writer:
        writer.close()
    return out, counts


def sec_10k_quarter(year: int, quarter: int, work: Path, client) -> tuple[Path, dict]:
    """Stream a quarter's 10-Ks into Parquet, 100 filings at a time: a quarter's text does
    not fit in a small machine's memory at once."""
    out = work / f"{year}-Q{quarter}.parquet"
    writer, batch, counts = None, [], {"documents": 0, "words": 0}
    for record in sec_10k.records(client, year, quarter):
        batch.append(record)
        counts["documents"] += 1
        counts["words"] += len(record["text"].split())
        if len(batch) == 100:
            table = pa.Table.from_pylist(batch)
            writer = writer or pq.ParquetWriter(out, table.schema, compression="zstd")
            writer.write_table(table)
            batch = []
            print(f"  {year} Q{quarter}: {counts['documents']:,} filings", flush=True)
    if batch:
        table = pa.Table.from_pylist(batch)
        writer = writer or pq.ParquetWriter(out, table.schema, compression="zstd")
        writer.write_table(table)
    if writer:
        writer.close()
    return out, counts


def publish(api: HfApi, stats: dict, key: str, path: Path, counts: dict) -> None:
    api.upload_file(
        path_or_fileobj=str(path),
        path_in_repo=f"{key}.parquet",
        repo_id=REPO,
        repo_type="dataset",
        commit_message=f"{key}: {counts['documents']:,} documents",
    )
    stats[key] = counts
    api.upload_file(
        path_or_fileobj=json.dumps(stats, indent=1).encode(),
        path_in_repo="stats.json",
        repo_id=REPO,
        repo_type="dataset",
        commit_message=f"stats: {key}",
    )
    print(json.dumps({"published": key, **counts}), flush=True)


def main_sec(first: int, last: int) -> None:
    import os

    api = HfApi()
    api.create_repo(REPO, repo_type="dataset", private=False, exist_ok=True)
    stats = stats_of(api)
    client = sec_10k.Polite(os.environ["SEC_CONTACT"])
    step = -1 if last < first else 1
    for year in range(first, last + step, step):
        for quarter in (4, 3, 2, 1) if step < 0 else (1, 2, 3, 4):
            key = f"sec_10k/{year}-Q{quarter}"
            if key in stats:
                print(f"{key}: already published", flush=True)
                continue
            work = Path(tempfile.mkdtemp(prefix="public-records-"))
            try:
                path, counts = sec_10k_quarter(year, quarter, work, client)
                if counts["documents"]:
                    publish(api, stats, key, path, counts)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code != 404:  # 404: a quarter not indexed yet
                    raise
            finally:
                shutil.rmtree(work, ignore_errors=True)


def main(source: str, first: int, last: int) -> None:
    if source == "sec_10k":
        return main_sec(first, last)
    api = HfApi()
    api.create_repo(REPO, repo_type="dataset", private=False, exist_ok=True)
    stats = stats_of(api)
    step = -1 if last < first else 1
    with httpx.Client(
        headers={"User-Agent": federal_register.AGENT}, follow_redirects=True, timeout=120
    ) as client:
        for year in range(first, last + step, step):
            key = f"{source}/{year}"
            if key in stats:
                print(f"{key}: already published", flush=True)
                continue
            work = Path(tempfile.mkdtemp(prefix="public-records-"))
            try:
                path, counts = federal_register_year(year, work, client)
                if not counts["documents"]:
                    continue
                api.upload_file(
                    path_or_fileobj=str(path),
                    path_in_repo=f"{source}/{year}.parquet",
                    repo_id=REPO,
                    repo_type="dataset",
                    commit_message=f"{source} {year}: {counts['documents']:,} documents",
                )
                stats[key] = counts
                api.upload_file(
                    path_or_fileobj=json.dumps(stats, indent=1).encode(),
                    path_in_repo="stats.json",
                    repo_id=REPO,
                    repo_type="dataset",
                    commit_message=f"stats: {key}",
                )
                print(json.dumps({"published": key, **counts}), flush=True)
            finally:
                shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]), int(sys.argv[3]))
