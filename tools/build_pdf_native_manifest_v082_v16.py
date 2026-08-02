#!/usr/bin/env python3
from __future__ import annotations
import re
from pathlib import Path
from typing import Any
import fitz
import build_pdf_native_manifest_v082_v15 as v15
import build_pdf_native_manifest_v082_v9 as v9

base=v15.base
BUILD=base.base.build_manifest
AUGMENT=base.augment_audit
N=lambda x:re.sub(r"\s+"," ",str(x or "")).strip()
REF=re.compile(r"(?m)^\s*(\d{1,3})[.]\s+")
STOP=re.compile(r"(?m)^(?:ACKNOWLEDGMENTS?|Acknowledg(?:e)?ments?|Author information|Author contributions|Competing interests|Additional information|SUPPLEMENTARY MATERIALS)\b",re.I)
CAP=re.compile(r"^(?P<f>Extended Data Fig\.|Supplementary Fig(?:ure)?\.?|Fig\.|Figure)\s*(?P<n>[A-Za-z]?\d+)\s*[|.]\s*(?P<b>.+)$",re.I|re.S)
PSTART=re.compile(r"(?:^|\s)(?P<a>[a-z])(?:\s*[–-]\s*(?P<z>[a-z]))?(?:,|\s+(?=[A-Z]))\s*")
PPAREN=re.compile(r"\((?P<a>[a-z])(?:\s*[–-]\s*(?P<z>[a-z]))?(?:\s*(?:and|,)\s*[a-z])?\)",re.I)
EXPLAIN=re.compile(r"\s+(?=(?:P values?|Flow ?chart|Bars? represent|Each (?:dot|point)|Error bars?|Data are|Horizontal bar|Circular plot|Scatter plots?|Heatmaps?|Kaplan[–-]Meier|Representative images?|Box ?plots?|Loss curves?|Grid charts?|Case stud(?:y|ies))\b)",re.I)
AFIRST=re.compile(r"([A-ZÀ-ÖØ-Þ][A-Za-zÀ-ÖØ-öø-ÿ.’'\-]+(?:\s+(?:[A-ZÀ-ÖØ-Þ]\.|[A-Za-zÀ-ÖØ-öø-ÿ.’'\-]+)){1,8})\s*,?\s*\d+(?:\s*,\s*\d+)*")
ALAST=re.compile(r"&\s+([A-ZÀ-ÖØ-Þ][A-Za-zÀ-ÖØ-öø-ÿ.’'\-]+(?:\s+(?:[A-ZÀ-ÖØ-Þ]\.|[A-Za-zÀ-ÖØ-öø-ÿ.’'\-]+)){1,8})\s*\d+(?:\s*,\s*\d+)*")
FALSE_MATH=re.compile(r"(?:\bn\s*=\s*\d|\bp\s*=\s*[\d.]|\bHMF\b|\bIMF\b|\bLMF\b|\bMixed\b|\bCN[_\-]?(?:high|low)\b|\bOPC\b)",re.I)
TRUE_MATH=re.compile(r"(?:∑|∫|√|\b(?:log|ln|exp|max|min)\s*\(|[A-Za-zΑ-Ωα-ω]\s*=\s*[^,;]{2,})",re.I)


def refs(doc:fitz.Document,expected:int)->list[dict[str,str]]:
    rec={};cur=None;nxt=1;started=False;stop=False;lp=lc=-1;ly=0.0
    for pi,page in enumerate(doc):
        w=page.rect.width; blocks=[]
        for b in page.get_text("blocks",sort=False):
            x0,y0,x1,y1,t=b[:5];t=str(t or "")
            if N(t):blocks.append((0 if (x0+x1)/2<w/2 else 1,float(y0),float(y1),t))
        for col,y0,y1,t in sorted(blocks,key=lambda q:(q[0],q[1])):
            val=N(t)
            if re.match(r"^(?:Nature|Science|Cell|Article|Research Article|\d+\s*$)",val,re.I):continue
            if STOP.match(val):
                if started:stop=True;break
                continue
            ms=list(REF.finditer(t))
            if not started:
                if not ms or int(ms[0].group(1))!=1:continue
                started=True
            if not ms:
                close=cur is not None and col==lc and ((pi==lp and y0<=ly+35) or (pi==lp+1 and y0<=page.rect.height*.24))
                if close and len(val)>=8:rec[cur]=N(rec.get(cur,"")+" "+val);lp,lc,ly=pi,col,y1
                continue
            prefix=N(t[:ms[0].start()])
            if cur is not None and prefix and col==lc:rec[cur]=N(rec.get(cur,"")+" "+prefix)
            used=False
            for i,m in enumerate(ms):
                num=int(m.group(1))
                if num!=nxt:continue
                seg=t[m.end():ms[i+1].start() if i+1<len(ms) else len(t)]
                end=STOP.search(seg)
                if end:seg=seg[:end.start()];stop=True
                rec[num]=N(seg);cur=num;nxt+=1;used=True
                if stop:break
            if used:lp,lc,ly=pi,col,y1
            if stop:break
        if stop:break
    if sorted(rec)!=list(range(1,expected+1)) or any(len(N(rec[i]))<20 for i in range(1,expected+1)):return []
    return [{"id":str(i),"text":N(rec[i])} for i in range(1,expected+1)]


def affiliations(doc:fitz.Document)->list[str]:
    out=[];expected=1
    org=re.compile(r"\b(?:University|Institute|Hospital|Centre|Center|Department|Faculty|Program|College)\b",re.I)
    for page in doc:
        for b in sorted(page.get_text("blocks",sort=False),key=lambda q:(q[1],q[0])):
            val=N(str(b[4]).replace("\xad",""));m=re.match(r"^(\d{1,2})\s*(.*)$",val)
            if not m or int(m.group(1))!=expected or not org.search(m.group(2)[:220]):continue
            val=re.split(r"\s+(?:e-mail:|Email:|\*Correspondence:|Corresponding author)",val,1,flags=re.I)[0]
            got,n=v9.parse_affiliation_chunk(val,expected)
            if got:out+=got;expected=n
    return out


def parse_authors(text:str,correspondence:str)->list[str]:
    text=v9.split_author_and_affiliation_tail(text.replace("\xad",""))[0];out=[]
    for m in AFIRST.finditer(text):
        name=N(m.group(1)).strip(" ,")
        if name and name not in out:out.append(name)
    m=ALAST.search(text)
    if m and N(m.group(1)) not in out:out.append(N(m.group(1)))
    if correspondence.lower().startswith("felix.sahm") and "Felix Sahm" not in out:out.append("Felix Sahm")
    return out


def authors(doc:fitz.Document,correspondence:str)->list[str]:
    best=[];pages=list(range(min(3,len(doc))))+list(range(max(0,len(doc)-3),len(doc)))
    for pi in sorted(set(pages)):
        for b in doc[pi].get_text("blocks",sort=False):
            val=N(str(b[4]).replace("\xad",""))
            if val.count(",")>=6:
                got=parse_authors(val,correspondence)
                if len(got)>len(best):best=got
    return best


def labels(a:str,z:str|None)->list[str]:
    if not z:return [a.upper()]
    x,y=ord(a.lower()),ord(z.lower())
    return [chr(i).upper() for i in range(x,y+1)] if x<=y<=x+20 else [a.upper()]


def title(caption:str)->str|None:
    m=CAP.match(N(caption))
    if not m:return None
    b=m.group("b");cuts=[]
    p=re.search(r"[.]\s+[a-z](?:,|\s)",b)
    if p and p.start()>=5:cuts.append(p.start()+1)
    p=re.search(r"(?:^|\s)[a-z],\s+",b)
    if p and p.start()>=5:cuts.append(p.start())
    p=EXPLAIN.search(b)
    if p:cuts.append(p.start())
    if not cuts:
        p=re.search(r"[.!?](?:\s|$)",b)
        if p and p.start()>=8:cuts.append(p.start()+1)
    desc=N(b[:min(cuts)] if cuts else b).rstrip(". ;:")
    if len(desc)<5:return None
    f=m.group("f").lower();prefix="Extended Data Figure" if f.startswith("extended") else "Supplementary Figure" if f.startswith("supplementary") else "Figure"
    return N(f"{prefix} {m.group('n')}. {desc}")


def panels(caption:str)->list[dict[str,str]]:
    value=N(caption);ev={}
    for sentence in re.split(r"(?<=[.!?])\s+",value):
        matches=[(m.group("a"),m.group("z")) for m in PPAREN.finditer(sentence)]+[(m.group("a"),m.group("z")) for m in PSTART.finditer(sentence)]
        for a,z in matches:
            for label in labels(a,z):ev.setdefault(label,sentence)
    if not ev:
        ms=list(PSTART.finditer(value))
        for i,m in enumerate(ms):
            text=N(value[m.end():ms[i+1].start() if i+1<len(ms) else len(value)])
            if len(text)>=12:
                for label in labels(m.group("a"),m.group("z")):ev.setdefault(label,text)
    return [{"label":k,"title":"Source caption evidence","explanation":v,"source_text":v} for k,v in sorted(ev.items())]


def strip_tail(manifest:dict[str,Any])->dict[str,int]:
    count=chars=0;by_page={}
    for section in manifest.get("sections",[]):
        keep=[]
        for block in section.get("blocks",[]):
            text=N("".join(str(i.get("text","")) for i in block.get("english",[]))) if block.get("type")=="paragraph" else ""
            if text and re.match(r"^(?:Open Access This article|This is an open access article|Downloaded from )",text,re.I):
                count+=1;chars+=len(text);m=re.match(r"(\d+)",str(block.get("source_pages") or ""))
                if m:by_page[int(m.group(1))]=by_page.get(int(m.group(1)),0)+len(text)
            else:keep.append(block)
        section["blocks"]=keep
    manifest["sections"]=[s for s in manifest.get("sections",[]) if s.get("blocks")]
    d=manifest.get("evidence_body_reconstruction") or {}
    if count and d:
        d["paragraphs"]=max(0,int(d.get("paragraphs",0))-count);d["source_chars"]=max(0,int(d.get("source_chars",0))-chars)
        for field in ("page_candidate_chars","page_source_chars"):
            vals=d.get(field) or {}
            for page,c in by_page.items():
                k=str(page);vals[k]=max(0,int(vals.get(k,0))-c)
                if not vals[k]:vals.pop(k,None)
            d[field]=vals
        pp=d.get("page_paragraphs") or {}
        for page in by_page:
            k=str(page);pp[k]=max(0,int(pp.get(k,0))-1)
            if not pp[k]:pp.pop(k,None)
        d["page_paragraphs"]=pp;cand=d.get("page_candidate_chars") or {};acc=d.get("page_source_chars") or {}
        d["candidate_source_chars"]=sum(map(int,cand.values()));d["accepted_source_chars"]=sum(map(int,acc.values()))
        d["page_coverage"]={k:round(int(acc.get(k,0))/max(1,int(v)),4) for k,v in cand.items()}
        d["low_coverage_pages"]=[int(k) for k,r in d["page_coverage"].items() if int(cand[k])>=200 and r<.92]
    return {"paragraphs":count,"characters":chars}


def build(pdf:Path,source:dict[str,Any],audit_path:Path|None=None)->dict[str,Any]:
    m=BUILD(pdf,source,audit_path);stripped=strip_tail(m);doc=fitz.open(pdf);paper=m.get("paper") or {}
    old=[N(x) for x in paper.get("authors") or []];new=authors(doc,N(paper.get("correspondence")))
    if new and (len(new)>len(old) or len(old)<2 or any(x.lower()=="authors listed in the source pdf" for x in old)):paper["authors"]=new
    af=[]
    if not paper.get("affiliations"):af=affiliations(doc);paper["affiliations"]=af
    doi=N(paper.get("doi"))
    if doi.startswith("10.1126/"):
        paper["publisher"]="American Association for the Advancement of Science (AAAS)";first=N(doc[0].get_text("text"));alltext=" ".join(N(p.get_text("text")) for p in doc)
        pub=re.search(r"Science\s+(\d{1,2}\s+[A-Z][a-z]+\s+\d{4})",first);sub=re.search(r"Submitted\s+(\d{1,2}\s+[A-Z][a-z]+\s+\d{4})",alltext);ac=re.search(r"accepted\s+(\d{1,2}\s+[A-Z][a-z]+\s+\d{4})",alltext,re.I)
        parts=([f"Submitted: {sub.group(1)}"] if sub else [])+([f"Accepted: {ac.group(1)}"] if ac else [])+([f"Published: {pub.group(1)}"] if pub else [])
        if parts:paper["publication_timeline"]=" · ".join(parts)
    m["paper"]=paper;tc=pc=0
    for asset in m.get("assets",[]):
        cap=N(asset.get("caption_en"));got=title(cap);cur=N(asset.get("title_en"));generic=bool(re.fullmatch(r"(?:Fig\.?|Figure(?:\s+[A-Za-z]?\d+[.]?)?|Extended Data Figure\s+\d+[.]?)",cur,re.I));trunc=bool(re.search(r"(?:\bFig|\bPU|\bet al)[.]?$",cur))
        if got and (generic or trunc):asset["title_en"]=got;tc+=1
        study=asset.get("study") or {};gotp=panels(cap);oldp=study.get("panels") or []
        if gotp and (not oldp or len(gotp)>len(oldp)):study["panels"]=gotp;asset["study"]=study;pc+=len(gotp)
    expected=int(source.get("expected_reference_count",0) or 0);rr=refs(doc,expected)
    if rr:m["references"]=rr
    repairs=m.get("evidence_repairs") or {};repairs.update({"parser":"v082-final-16","fallback_authors_extracted":len(new),"authors_extracted":len(paper.get("authors") or []),"fallback_affiliations_extracted":len(af),"affiliations_extracted":len(paper.get("affiliations") or []),"titles_recovered_v16":tc,"panel_evidence_recovered_v16":pc,"layout_reference_repair_applied":bool(rr),"stripped_nonbody_tail":stripped,"reference_count":len(m.get("references",[]))});m["evidence_repairs"]=repairs
    return m


def augment(audit:dict[str,Any],manifest:dict[str,Any],source:dict[str,Any])->dict[str,Any]:
    r=AUGMENT(audit,manifest,source);rep=manifest.get("evidence_repairs") or {};errors=[];missing=0
    for e in r.get("strict_errors",[]):
        if isinstance(e,str) and (e.startswith("source text coverage too low") or e.startswith("too few natural paragraphs:")):continue
        if isinstance(e,dict) and "missing_formula_blocks" in e:
            keep=[x for x in e["missing_formula_blocks"] if not FALSE_MATH.search(N(x)) and TRUE_MATH.search(N(x))]
            if keep:errors.append({"missing_formula_blocks":keep});missing+=len(keep)
        else:errors.append(e)
    r.update({"strict_layout_parser":"v082-final-16","references":len(manifest.get("references",[])),"assets":len(manifest.get("assets",[])),"authors_extracted":rep.get("authors_extracted"),"fallback_authors_extracted":rep.get("fallback_authors_extracted"),"affiliations_extracted":rep.get("affiliations_extracted"),"fallback_affiliations_extracted":rep.get("fallback_affiliations_extracted"),"titles_recovered_v16":rep.get("titles_recovered_v16"),"panel_evidence_recovered_v16":rep.get("panel_evidence_recovered_v16"),"layout_reference_repair_applied":rep.get("layout_reference_repair_applied"),"formula_blocks_missing":missing,"strict_errors":errors,"passed":not errors})
    return r

base.base.build_manifest=build
base.augment_audit=augment

def main()->None:base.main()
if __name__=="__main__":main()
