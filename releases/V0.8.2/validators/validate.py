#!/usr/bin/env python3
import argparse, hashlib, json, re
from pathlib import Path

def balanced(text, marker):
    start=text.index(marker)+len(marker); depth=0; string=False; esc=False
    for i,ch in enumerate(text[start:],start):
        if string:
            if esc: esc=False
            elif ch=='\\': esc=True
            elif ch=='"': string=False
        else:
            if ch=='"': string=True
            elif ch in '[{': depth+=1
            elif ch in ']}':
                depth-=1
                if depth==0: return text[start:i+1]
    raise ValueError('unbalanced JSON')

def main():
    p=argparse.ArgumentParser(); p.add_argument('html'); p.add_argument('--sha256',required=True); a=p.parse_args()
    raw=Path(a.html).read_bytes(); text=raw.decode('utf-8'); sha=hashlib.sha256(raw).hexdigest(); errors=[]
    if sha!=a.sha256: errors.append(f'sha256 mismatch: {sha}')
    required=['V0.8.2 Candidate','canvas-v082-style','canvas-v082-script','canvas-reader-canvas-v082','PDF layout span classification before bilingual generation','strict latin token boundaries','window.__v077ViewerTarget=viewerTarget']
    for token in required:
        if token not in text: errors.append('missing '+token)
    study=json.loads(balanced(text,'const V6_STUDY='))
    expected={'figure-1':10,'figure-2':10,'figure-3':14,'figure-4':10,'figure-5':15}
    for fid,n in expected.items():
        got=len(study.get(fid,{}).get('panels',[]))
        if got!=n: errors.append(f'{fid} panels {got}!={n}')
    ontology=json.loads(balanced(text,'const ONTOLOGY='))
    if len(ontology)<135: errors.append(f'ontology too small: {len(ontology)}')
    citations=re.findall(r'<sup class="citation"[^>]*data-refs="([^"]+)"',text)
    if len(citations)<250: errors.append(f'citation count too small: {len(citations)}')
    report={'passed':not errors,'sha256':sha,'ontology_terms':len(ontology),'citation_count':len(citations),'panel_counts':{k:len(study.get(k,{}).get('panels',[])) for k in expected},'errors':errors}
    print(json.dumps(report,ensure_ascii=False,indent=2))
    if errors: raise SystemExit(1)
if __name__=='__main__': main()
