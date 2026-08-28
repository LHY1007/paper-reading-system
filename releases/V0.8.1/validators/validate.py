#!/usr/bin/env python3
import argparse, hashlib, json, re
from pathlib import Path

def extract_object(text, marker):
    start=text.index(marker)+len(marker); depth=0; in_string=False; escaped=False
    for index in range(start,len(text)):
        char=text[index]
        if in_string:
            if escaped: escaped=False
            elif char=='\\': escaped=True
            elif char=='"': in_string=False
        else:
            if char=='"': in_string=True
            elif char=='{': depth+=1
            elif char=='}':
                depth-=1
                if depth==0: return json.loads(text[start:index+1])
    raise ValueError('unbalanced JSON object')

def main():
    parser=argparse.ArgumentParser(); parser.add_argument('html'); parser.add_argument('--sha256'); args=parser.parse_args()
    path=Path(args.html); raw=path.read_bytes(); text=raw.decode('utf-8'); errors=[]
    digest=hashlib.sha256(raw).hexdigest()
    if args.sha256 and digest!=args.sha256: errors.append('sha256 mismatch')
    for token in ['V0.8.1 Candidate','canvas-v081-style','canvas-v081-script','v081-right-open','v081-study-open',"captionDefault:'expanded'",'inferred coordinates forbidden']:
        if token not in text: errors.append('missing contract token: '+token)
    study=extract_object(text,'const V6_STUDY=')
    for figure_id,count in [('figure-4',10),('figure-5',15)]:
        panels=study.get(figure_id,{}).get('panels',[])
        if len(panels)!=count: errors.append(f'{figure_id}: panel count {len(panels)} != {count}')
        for title,body in panels:
            if len(body)<180: errors.append(f'{figure_id}/{title}: explanation too short')
            if re.search(r'(?m)^\s*(?:[-•]|训练集\s*$|验证集\s*$|风险方向\s*$|保护性方向\s*$)',body):
                errors.append(f'{figure_id}/{title}: list-like style detected')
    if errors:
        print(json.dumps({'passed':False,'errors':errors},ensure_ascii=False,indent=2)); raise SystemExit(1)
    print(json.dumps({'passed':True,'sha256':digest,'figure4_panels':10,'figure5_panels':15},ensure_ascii=False,indent=2))
if __name__=='__main__': main()
