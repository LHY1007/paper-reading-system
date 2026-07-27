#!/usr/bin/env python3
import argparse, hashlib, json
from pathlib import Path

def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('base')
    ap.add_argument('patch')
    ap.add_argument('output')
    args=ap.parse_args()
    base=Path(args.base); patch_path=Path(args.patch); output=Path(args.output)
    p=json.loads(patch_path.read_text('utf-8'))
    raw=base.read_bytes()
    if sha(raw)!=p['base_sha256']:
        raise SystemExit(f"base SHA256 mismatch: {sha(raw)} != {p['base_sha256']}")
    lines=raw.decode('utf-8').splitlines(keepends=True)
    for op in sorted(p['operations'], key=lambda x:x['i1'], reverse=True):
        old=''.join(lines[op['i1']:op['i2']]).encode('utf-8')
        if sha(old)!=op['old_sha256']:
            raise SystemExit(f"operation anchor mismatch at lines {op['i1']}:{op['i2']}")
        lines[op['i1']:op['i2']]=[op['new']] if op['new'] else []
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(''.join(lines),'utf-8')
    digest=sha(output.read_bytes())
    if digest!=p['target_sha256']:
        raise SystemExit(f"target SHA256 mismatch: {digest} != {p['target_sha256']}")
    print(f"built {output} {digest}")
if __name__=='__main__': main()
