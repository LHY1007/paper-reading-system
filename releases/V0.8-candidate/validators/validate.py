#!/usr/bin/env python3
from pathlib import Path
from bs4 import BeautifulSoup
import hashlib, json, sys
base=Path(sys.argv[1]); candidate=Path(sys.argv[2])
b=BeautifulSoup(base.read_text("utf-8"),"html.parser"); c=BeautifulSoup(candidate.read_text("utf-8"),"html.parser")
def h(soup,sel): return hashlib.sha256(soup.select_one(sel).encode("utf-8")).hexdigest()
checks={
 "quick_pane":h(b,"#quick-pane")==h(c,"#quick-pane"),
 "bilingual_pane":h(b,"#bilingual-pane")==h(c,"#bilingual-pane"),
 "reference_data":(b.find("script",id="referenceData").string or "")== (c.find("script",id="referenceData").string or ""),
 "study_source":(b.find("script",id="canvas-reader-v060-script").string or "")== (c.find("script",id="canvas-reader-v060-script").string or ""),
 "figure_ids":[x.id for x in b.select(".figure-card[id]")]==[x.id for x in c.select(".figure-card[id]")],
 "table_ids":[x.id for x in b.select(".table-card[id]")]==[x.id for x in c.select(".table-card[id]")],
 "study_button_count":len(b.select(".figure-study-button"))==len(c.select(".figure-study-button")),
}
print(json.dumps({"passed":all(checks.values()),"checks":checks},ensure_ascii=False,indent=2))
raise SystemExit(0 if all(checks.values()) else 1)
