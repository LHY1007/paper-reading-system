#!/usr/bin/env python3
from __future__ import annotations

import base64
import hashlib
import io
import lzma
import tarfile
from pathlib import Path, PurePosixPath


PART_DIR = Path('.github/v082-sentence-upgrade')
EXPECTED_PARTS = [f'chunk{i:02d}' for i in range(14)]
EXPECTED_B64_LENGTH = 122576
EXPECTED_B64_SHA256 = '77b159c78733c97570c589020ea3964e925954364a07ba3bc0e55539c5dab3d4'
EXPECTED_XZ_SHA256 = '20a4df7b68cde8bd06d89547f0d678052f56cf60fe4ea3154e89046e480f61e4'
EXPECTED_TAR_SHA256 = 'bbb1bb69f2809671a2a56d4cceb8e29da0558a92d51857d239ffb132101fd346'


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def safe_member_path(name: str) -> Path:
    pure = PurePosixPath(name)
    if pure.is_absolute() or not pure.parts or '..' in pure.parts:
        raise ValueError(f'unsafe archive member: {name!r}')
    target = Path(*pure.parts)
    if target.parts[0] in {'.git', '.github/v082-sentence-upgrade'}:
        raise ValueError(f'archive may not mutate protected path: {name!r}')
    return target


def main() -> None:
    actual = sorted(path.name for path in PART_DIR.glob('chunk*'))
    if actual != EXPECTED_PARTS:
        raise SystemExit(f'upgrade parts mismatch: expected {EXPECTED_PARTS}, found {actual}')

    encoded = ''.join((PART_DIR / name).read_text('ascii') for name in EXPECTED_PARTS).encode('ascii')
    if len(encoded) != EXPECTED_B64_LENGTH or sha256(encoded) != EXPECTED_B64_SHA256:
        raise SystemExit('staged base64 bundle failed length or SHA-256 verification')

    compressed = base64.b64decode(encoded, validate=True)
    if sha256(compressed) != EXPECTED_XZ_SHA256:
        raise SystemExit('compressed bundle SHA-256 mismatch')
    archive = lzma.decompress(compressed)
    if sha256(archive) != EXPECTED_TAR_SHA256:
        raise SystemExit('tar payload SHA-256 mismatch')

    written: list[dict[str, object]] = []
    with tarfile.open(fileobj=io.BytesIO(archive), mode='r:') as bundle:
        members = bundle.getmembers()
        if not members:
            raise SystemExit('upgrade archive is empty')
        for member in members:
            if not member.isfile() or member.issym() or member.islnk():
                raise SystemExit(f'unsupported archive member type: {member.name!r}')
            target = safe_member_path(member.name)
            source = bundle.extractfile(member)
            if source is None:
                raise SystemExit(f'cannot read archive member: {member.name!r}')
            data = source.read()
            if len(data) != member.size:
                raise SystemExit(f'archive member size mismatch: {member.name!r}')
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            written.append({'path': target.as_posix(), 'bytes': len(data), 'sha256': sha256(data)})

    print(f'applied {len(written)} sentence-pair upgrade files')
    for item in written:
        print(f"{item['sha256']}  {item['bytes']:>7}  {item['path']}")


if __name__ == '__main__':
    main()
