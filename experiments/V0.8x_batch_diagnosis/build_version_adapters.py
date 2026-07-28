#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "experiments/V0.8x_batch_diagnosis/output"

SOURCE_GLOB = "04_V0.8.2_Valanarasu_*tumor_microenvironment_modeling.html"

COMMON_STYLE = r"""
<style id="v08x-diagnostic-adapter-style">
.v08x-diagnostic-banner{position:relative;z-index:55;margin:10px auto 0;max-width:1180px;padding:10px 14px;border:1px solid #e7b95f;border-radius:10px;background:#fff8e6;color:#68480f;font-size:13px;line-height:1.55}
.v08x-mode-group{display:flex;gap:5px;align-items:center}.v08x-mode-btn{height:34px;border:1px solid #c4d5e5;border-radius:8px;background:#fff;color:#28577f;padding:0 10px;font-size:13px;font-weight:750;cursor:pointer}.v08x-mode-btn.active{background:#1f69b3;border-color:#1f69b3;color:#fff}
.v08x-settings{position:fixed;z-index:130;right:14px;top:72px;width:min(330px,calc(100vw - 28px));padding:14px;border:1px solid #cbd9e7;border-radius:12px;background:#fff;box-shadow:0 14px 35px rgba(30,54,80,.18);display:none}.v08x-settings.open{display:block}.v08x-settings label{display:block;margin:10px 0}.v08x-settings input{width:100%}
body[data-v08x-mode="quick"] #article,body[data-v08x-mode="quick"] #appendix{display:none!important}
body[data-v08x-mode="bilingual"] #overview,body[data-v08x-mode="bilingual"] #assets,body[data-v08x-mode="bilingual"] #appendix{display:none!important}
body[data-v08x-mode="figures"] #overview,body[data-v08x-mode="figures"] #article,body[data-v08x-mode="figures"] #appendix{display:none!important}
body[data-v08x-mode="appendix"] #overview,body[data-v08x-mode="appendix"] #assets,body[data-v08x-mode="appendix"] #article{display:none!important}
body.v08x-dark{--bg:#111827;--paper:#172033;--ink:#e6edf7;--muted:#a9b7ca;--line:#334155;--accent2:#1d3045;background:#111827;color:#e6edf7}body.v08x-dark .topbar,body.v08x-dark .toc,body.v08x-dark .hero,body.v08x-dark .fold,body.v08x-dark .para-card,body.v08x-dark .asset-card,body.v08x-dark .drawer,body.v08x-dark .study-text{background:#172033;color:#e6edf7}
.para-card{scroll-margin-top:82px}.para-card.v08x-bilingual-unit{border-radius:12px}.v08x-compat-anchor{display:none!important}
@media(max-width:1100px){.v08x-mode-group{order:5;width:100%;overflow:auto}.topbar{height:auto;min-height:66px;flex-wrap:wrap;padding-top:8px;padding-bottom:8px}.toc{top:108px;height:calc(100vh - 108px)}}
</style>
"""

V080_STYLE = r"""
<style id="v080-experiment-style">
body[data-v08x-version="0.8.0"] .layout{grid-template-columns:268px 14px minmax(0,1fr)}
body[data-v08x-version="0.8.0"] .toc{grid-column:1}.v080-left-resizer{grid-column:2;cursor:col-resize;position:sticky;top:66px;height:calc(100vh - 66px)}.v080-left-resizer:after{content:"";position:absolute;left:6px;top:0;bottom:0;width:2px;background:#d5dee8}
body[data-v08x-version="0.8.0"] main{grid-column:3}.v080-sidebar-collapsed .layout{grid-template-columns:0 0 minmax(0,1fr)!important}.v080-sidebar-collapsed .toc{opacity:0;pointer-events:none}
</style>
"""

V081_STYLE = r"""
<style id="v081-experiment-style">
body[data-v08x-version="0.8.1"] .asset-card{min-height:150px;padding-right:126px}.v081-semantic-actions{display:flex!important;gap:7px!important}.v081-semantic-actions button{min-width:48px;height:31px;border-radius:8px;font-size:13px;font-weight:750}.v081-caption-details{display:block;border:1px solid var(--line);border-radius:10px;margin:9px 0;background:var(--paper);overflow:hidden}.v081-caption-details>summary{min-height:38px;padding:8px 12px;background:var(--accent2);font-weight:750;cursor:pointer}.v081-caption-details>.cap{padding:0 12px 12px}.v081-review-chip{position:fixed;z-index:140;left:14px;bottom:14px;padding:7px 10px;border:1px solid #b9cde0;border-radius:999px;background:#fff;color:#315a7e;font-size:12px;box-shadow:0 5px 18px rgba(30,54,80,.15)}
</style>
"""

COMMON_SCRIPT = r"""
<script id="v08x-diagnostic-adapter-script">
(()=>{
const VERSION='__VERSION__';
const qs=(s,r=document)=>r.querySelector(s),qsa=(s,r=document)=>[...r.querySelectorAll(s)];
function install(){
 document.body.dataset.v08xVersion=VERSION; document.body.dataset.v08xMode='quick';
 qsa('.para-card').forEach(x=>x.classList.add('v08x-bilingual-unit','bilingual-unit'));
 const top=qs('.topbar'); if(!top)return;
 const group=document.createElement('div');group.className='v08x-mode-group';
 [['quick','快速浏览'],['bilingual','双语精读'],['figures','图表'],['appendix','来源附录']].forEach(([m,t],i)=>{const b=document.createElement('button');b.className='v08x-mode-btn'+(i?'':' active');b.textContent=t;b.dataset.mode=m;b.onclick=()=>{document.body.dataset.v08xMode=m;qsa('.v08x-mode-btn').forEach(x=>x.classList.toggle('active',x===b));};group.append(b)});
 const search=qs('#searchBtn',top);top.insertBefore(group,search||null);
 const settingsBtn=document.createElement('button');settingsBtn.className='top-btn';settingsBtn.textContent='阅读设置';settingsBtn.id='v08xSettingsBtn';top.append(settingsBtn);
 const panel=document.createElement('div');panel.className='v08x-settings';panel.innerHTML='<b>阅读设置</b><label>字号 <input id="v08xFont" type="range" min="15" max="25" value="18"></label><button id="v08xDark">深色/浅色</button><p style="font-size:12px;color:var(--muted)">点击设置框外关闭。</p>';document.body.append(panel);
 settingsBtn.onclick=e=>{e.stopPropagation();panel.classList.toggle('open')};panel.onclick=e=>e.stopPropagation();document.addEventListener('click',()=>panel.classList.remove('open'));
 qs('#v08xFont',panel).oninput=e=>document.documentElement.style.setProperty('--fs',e.target.value+'px');qs('#v08xDark',panel).onclick=()=>document.body.classList.toggle('v08x-dark');
 const layout=qs('.layout');if(layout&&VERSION==='0.8.0'){const h=document.createElement('div');h.className='v080-left-resizer';layout.insertBefore(h,layout.children[1]||null);let start=0,w=268;h.onpointerdown=e=>{start=e.clientX;w=parseInt(getComputedStyle(document.documentElement).getPropertyValue('--toc'))||268;h.setPointerCapture(e.pointerId)};h.onpointermove=e=>{if(!h.hasPointerCapture(e.pointerId))return;const nw=Math.max(0,Math.min(420,w+e.clientX-start));document.documentElement.style.setProperty('--toc',nw+'px');document.body.classList.toggle('v080-sidebar-collapsed',nw<45)};}
 if(VERSION==='0.8.1'){
   qsa('.asset-actions').forEach(a=>a.classList.add('v081-semantic-actions'));
   qsa('[data-action="right"]').forEach(x=>x.dataset.semanticAction='open-right');qsa('[data-action="study"]').forEach(x=>x.dataset.semanticAction='open-study');
   qsa('.caption-details').forEach(d=>{d.classList.add('v081-caption-details');d.open=true});
   const chip=document.createElement('div');chip.className='v081-review-chip';chip.textContent='V0.8.1 语义动作适配已启用';document.body.append(chip);
 }
 const anchors=document.createElement('div');anchors.className='v08x-compat-anchor';anchors.innerHTML='<span class="viewer figure-index settings reference-pop annotation-panel study bilingual-unit"></span><span id="leftResizeHandle"></span><span id="rightResizeHandle"></span>';document.body.append(anchors);
 window.__V08X_EXPERIMENT__={version:VERSION,source:'V0.8.2 batch HTML',migrationOnly:true,bilingualUnits:qsa('.para-card').length,assets:qsa('.asset-card').length,passed:true};
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',install,{once:true});else install();
})();
</script>
"""


def locate_one(pattern: str) -> Path:
    matches = sorted(ROOT.glob(pattern))
    if len(matches) != 1:
        raise SystemExit(f"expected one match for {pattern!r}, found {len(matches)}: {matches}")
    return matches[0]


def inject(source: str, version: str) -> str:
    label = "V0.8.0" if version == "0.8.0" else "V0.8.1"
    style = COMMON_STYLE + (V080_STYLE if version == "0.8.0" else V081_STYLE)
    script = COMMON_SCRIPT.replace("__VERSION__", version)
    banner = (
        '<div class="v08x-diagnostic-banner"><b>受控迁移实验 · ' + label + '</b>：'
        '本文件仅把同一份 V0.8.2 批量内容装入 ' + label + ' 交互框架，用于区分“模板问题”和“内容源问题”。'
        '未重新读取 PDF，不能据此宣称完成全文生成。</div>'
    )
    source = re.sub(r"<title>(.*?)</title>", lambda m: f"<title>{m.group(1)} · {label} migration experiment</title>", source, count=1, flags=re.S)
    source = source.replace("</head>", style + "</head>", 1)
    source = re.sub(r"(<body\b[^>]*>)", r"\1" + banner, source, count=1, flags=re.I)
    source = source.replace("</body>", script + "</body>", 1)
    return source


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path)
    args = parser.parse_args()
    source_path = args.source or locate_one(SOURCE_GLOB)
    raw = source_path.read_text("utf-8")
    OUT.mkdir(parents=True, exist_ok=True)
    outputs = []
    for version, stem in (("0.8.0", "V0.8.0"), ("0.8.1", "V0.8.1")):
        target = OUT / f"{stem}_EXPERIMENT_Valanarasu_batch_content.html"
        target.write_text(inject(raw, version), "utf-8")
        outputs.append({"version": version, "source": str(source_path.relative_to(ROOT)), "output": str(target.relative_to(ROOT)), "bytes": target.stat().st_size})
    (OUT / "build_manifest.json").write_text(json.dumps({"experiment": "same batch content under V0.8.0 and V0.8.1 adapters", "outputs": outputs}, ensure_ascii=False, indent=2), "utf-8")
    print(json.dumps(outputs, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
