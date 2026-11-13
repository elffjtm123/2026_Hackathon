"""Download a public model in verified HTTP ranges when full CDN transfers stall."""

import argparse
import concurrent.futures
import hashlib
import os
import time
from pathlib import Path

import httpx


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    parser.add_argument("output", type=Path)
    parser.add_argument("--size", type=int, required=True)
    parser.add_argument("--sha256")
    args = parser.parse_args()
    output = args.output.resolve()
    parts = output.parent / (output.name + ".parts")
    parts.mkdir(parents=True, exist_ok=True)
    chunk_size = 16 * 1024 * 1024
    spans = [
        (i, start, min(start + chunk_size, args.size) - 1)
        for i, start in enumerate(range(0, args.size, chunk_size))
    ]

    def download(span: tuple[int, int, int]) -> Path:
        index, start, end = span
        target = parts / f"{index:05d}.part"
        if target.is_file() and target.stat().st_size == end - start + 1:
            return target
        for attempt in range(4):
            try:
                separator = "&" if "?" in args.url else "?"
                url = args.url + f"{separator}range_part={index}&attempt={attempt}"
                with httpx.Client(follow_redirects=True, timeout=90) as client:
                    with client.stream(
                        "GET", url, headers={"Range": f"bytes={start}-{end}"}
                    ) as response:
                        response.raise_for_status()
                        if response.status_code != 206 or not response.headers.get(
                            "content-range", ""
                        ).startswith(f"bytes {start}-{end}/"):
                            raise ValueError("CDN did not return the requested range")
                        with target.open("wb") as stream:
                            for data in response.iter_bytes():
                                stream.write(data)
                if target.stat().st_size != end - start + 1:
                    raise ValueError("Incomplete range")
                return target
            except (httpx.HTTPError, OSError, ValueError):
                if attempt == 3:
                    raise
                time.sleep(attempt + 1)
        raise RuntimeError("Download failed")

    with concurrent.futures.ThreadPoolExecutor(max_workers=32) as pool:
        for completed, _ in enumerate(pool.map(download, spans), 1):
            if completed == 1 or completed % 8 == 0 or completed == len(spans):
                print(f"{output.name}: {completed}/{len(spans)} parts", flush=True)
    digest = hashlib.sha256()
    temporary = output.with_suffix(output.suffix + ".verified-download")
    with temporary.open("wb") as destination:
        for index, _, _ in spans:
            with (parts / f"{index:05d}.part").open("rb") as source:
                while data := source.read(1024 * 1024):
                    destination.write(data)
                    digest.update(data)
    if temporary.stat().st_size != args.size or (args.sha256 and digest.hexdigest() != args.sha256):
        raise ValueError("Model size/checksum mismatch; original target not replaced")
    os.replace(temporary, output)
    print(f"Verified {output.name}: {digest.hexdigest()}", flush=True)


if __name__ == "__main__":
    main()
