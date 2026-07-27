#!/usr/bin/env python3
"""Classify PDF text spans as body text or bibliographic citations before translation.

The classifier uses the source PDF's font size, vertical position and local line context.
It does not infer references from plain-text digit adjacency after HTML generation.
"""
from __future__ import annotations
import argparse, json, re
from dataclasses import dataclass, asdict
from pathlib import Path
import fitz

REF_RE=re.compile(r"^[0-9]+(?:[,-–][0-9]+)*$")

@dataclass
class Token:
    kind:str
    text:str
    refs:list[int]
    page:int
    bbox:list[float]

def expand_refs(text:str)->list[int]:
    out=[]
    for part in text.replace('–','-').split(','):
        if '-' in part:
            a,b=map(int,part.split('-',1));out.extend(range(a,b+1))
        else:out.append(int(part))
    return out

def line_tokens(line:dict,page_number:int,max_ref:int=999)->list[Token]:
    spans=line.get('spans',[])
    visible=[s for s in spans if s.get('text','').strip()]
    if not visible:return []
    body_sizes=[s['size'] for s in visible if not REF_RE.fullmatch(s['text'].strip())]
    if not body_sizes:return [Token('text',''.join(s['text'] for s in spans),[],page_number,[*line['bbox']])]
    body=max(body_sizes)
    body_spans=[s for s in visible if s['size']>=body*0.90 and not REF_RE.fullmatch(s['text'].strip())]
    body_y=(sum(s['bbox'][1] for s in body_spans)/len(body_spans)) if body_spans else None
    out=[];i=0;text_buffer=''
    while i<len(spans):
        s=spans[i];txt=s['text'];small=s['size']<=body*0.78
        if small and REF_RE.fullmatch(txt.strip()):
            j=i;display='';bbox=list(s['bbox'])
            while j<len(spans) and spans[j]['size']<=body*0.78 and REF_RE.fullmatch(spans[j]['text'].strip()):
                display+=spans[j]['text'].strip();bbox[2]=spans[j]['bbox'][2];bbox[3]=max(bbox[3],spans[j]['bbox'][3]);j+=1
            refs=expand_refs(display)
            raised=body_y is not None and (body_y-bbox[1])>=max(1.15,body*0.13)
            valid=body>=7.5 and raised and refs and all(1<=r<=max_ref for r in refs)
            prev=''.join(x['text'] for x in spans[:i])[-24:]
            nxt=''.join(x['text'] for x in spans[j:])[:24]
            excluded=bool(re.search(r'(?:Fig(?:ure)?|Table|n\s*=|×|=|ℝ)\s*$',prev,re.I) or re.match(r'\s*(?:%|μm|mm|pixels?|x\d)',nxt,re.I))
            if valid and not excluded:
                if text_buffer:out.append(Token('text',text_buffer,[],page_number,[*line['bbox']]));text_buffer=''
                out.append(Token('citation',display,refs,page_number,[round(x,3) for x in bbox]))
            else:text_buffer+=display
            i=j
        else:text_buffer+=txt;i+=1
    if text_buffer:out.append(Token('text',text_buffer,[],page_number,[*line['bbox']]))
    return out

def extract(pdf:Path,max_ref:int=999):
    doc=fitz.open(pdf);pages=[]
    for pno,page in enumerate(doc,1):
        blocks=[]
        for block in page.get_text('dict').get('blocks',[]):
            if 'lines' not in block:continue
            lines=[]
            for line in block['lines']:
                tokens=line_tokens(line,pno,max_ref)
                if tokens:lines.append([asdict(t) for t in tokens])
            if lines:blocks.append(lines)
        pages.append({'page':pno,'blocks':blocks})
    return {'source':str(pdf),'pages':pages}

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('pdf',type=Path);ap.add_argument('-o','--output',type=Path,required=True);ap.add_argument('--max-ref',type=int,default=999);a=ap.parse_args()
    a.output.write_text(json.dumps(extract(a.pdf,a.max_ref),ensure_ascii=False,indent=2),'utf-8')
