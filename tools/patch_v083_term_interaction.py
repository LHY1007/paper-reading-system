#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

STYLE = r'''<style id="canvas-v083-term-interaction-style">
/* V0.8.3 formal: reliable delegated terminology interaction in body, viewer and figure-study. */
.term-pop[role="button"]{touch-action:manipulation}
#v6StudyDoc .term-pop,#viewerContent .term-pop{position:relative;z-index:2}
#termTooltip.v083-term-tooltip{z-index:9000!important;pointer-events:auto}
</style>'''

SCRIPT = r'''<script id="canvas-v083-term-interaction-script">
(function(){
'use strict';
const V='0.8.3';
let active=null;
function q(s,r=document){return r.querySelector(s)}
function ensureTooltip(){
 let tt=q('#termTooltip');
 if(!tt){
   tt=document.createElement('div');tt.id='termTooltip';tt.className='term-tooltip';
   tt.innerHTML='<strong></strong><span></span>';document.body.append(tt);
 }
 tt.classList.add('v083-term-tooltip');
 return tt;
}
function close(){
 const tt=ensureTooltip();tt.classList.remove('show');tt.style.display='none';
 active?.classList.remove('active');active=null;
}
function place(tt,el){
 const r=el.getBoundingClientRect(),pad=12,w=Math.min(420,Math.max(240,innerWidth-pad*2));
 tt.style.width=w+'px';tt.style.display='block';tt.classList.add('show');
 requestAnimationFrame(()=>{
   const h=tt.offsetHeight;
   let left=Math.min(Math.max(pad,r.left),Math.max(pad,innerWidth-w-pad));
   let top=r.bottom+8;
   if(top+h>innerHeight-pad)top=Math.max(pad,r.top-h-8);
   tt.style.left=left+'px';tt.style.top=top+'px';
 });
}
function open(el){
 const tt=ensureTooltip();
 if(active===el&&tt.classList.contains('show')){close();return}
 active?.classList.remove('active');active=el;el.classList.add('active');
 const strong=q('strong',tt),span=q('span',tt);
 if(strong)strong.textContent=el.textContent.trim();
 if(span)span.textContent=el.dataset.tip||el.getAttribute('data-definition')||'暂无术语解释。';
 place(tt,el);
}
function termFrom(target){return target&&target.closest?target.closest('.term-pop'):null}
// Capture phase is intentional: legacy sentence/annotation/figure handlers may stop bubbling.
document.addEventListener('click',function(e){
 const t=termFrom(e.target);if(!t)return;
 e.preventDefault();e.stopImmediatePropagation();open(t);
},true);
document.addEventListener('keydown',function(e){
 const t=termFrom(e.target);if(!t||!['Enter',' '].includes(e.key))return;
 e.preventDefault();e.stopImmediatePropagation();open(t);
},true);
document.addEventListener('pointerdown',function(e){
 if(active&&!termFrom(e.target)&&!e.target.closest?.('#termTooltip'))close();
},true);
addEventListener('resize',()=>{if(active)place(ensureTooltip(),active)});
addEventListener('scroll',()=>{if(active)place(ensureTooltip(),active)},true);
window.__CANVAS_V083_CONTRACT__={
 version:V,
 formal:true,
 termInteraction:'delegated capture click + keyboard; body/viewer/figure-study',
 legacyContentPreserved:true
};
})();
</script>'''

PATCH = STYLE + "\n" + SCRIPT


def patch_text(html: str) -> str:
    if 'id="canvas-v083-term-interaction-script"' in html:
        return html
    html = html.replace(
        '<meta content="0.8.2-candidate" name="paper-reader-version"/>',
        '<meta content="0.8.3" name="paper-reader-version"/>'
    )
    marker = '<meta content="1" name="v082-canonical-normalized"/>'
    if marker in html and 'name="paper-reader-release"' not in html:
        html = html.replace(marker, marker + '<meta content="V0.8.3-official-term-interaction-fix" name="paper-reader-release"/>', 1)
    if '</body>' not in html:
        raise ValueError('HTML has no closing </body> tag')
    return html.replace('</body>', PATCH + '\n</body>', 1)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument('input', type=Path)
    p.add_argument('output', type=Path, nargs='?')
    args = p.parse_args()
    out = args.output or args.input
    text = args.input.read_text('utf-8')
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(patch_text(text), 'utf-8')
    print(out)


if __name__ == '__main__':
    main()
