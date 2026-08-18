#!/usr/bin/env python3
from __future__ import annotations

import tempfile
from pathlib import Path

from validate_v083_component_format import validate


CSS = """
<style>
.metadata{display:grid}.qa-grid{display:grid}.qa,.x{padding:1px}.qa h3{margin:0}.story{padding:1px}
</style>
"""

GOOD = f"""<!doctype html><html><head>{CSS}</head><body>
<section class='hero'><details class='paper-info'><div class='metadata'>
<div><span>Journal</span><b>Example</b></div><div><span>DOI</span><b>10.0/example</b></div>
</div></details></section>
<details id='overview-bilingual-folded'><summary>一页概览与方法流程概括</summary>
<section class='card' id='overview-clone'><h2 data-toc-en='Overview' data-toc-zh='一页概览'>一页概览</h2>
<div class='qa-grid'>
<article class='qa'><h3 data-toc-ignore='1'>Q1</h3><p>A1</p></article>
<article class='qa'><h3 data-toc-ignore='1'>Q2</h3><p>A2</p></article>
<article class='qa'><h3 data-toc-ignore='1'>Q3</h3><p>A3</p></article>
<article class='qa'><h3 data-toc-ignore='1'>Q4</h3><p>A4</p></article>
<article class='qa'><h3 data-toc-ignore='1'>Q5</h3><p>A5</p></article>
<article class='qa'><h3 data-toc-ignore='1'>Q6</h3><p>A6</p></article>
</div><h3 data-toc-ignore='1'>方法流程概括</h3><p>Flow</p><div class='story'><b>整体结论</b><p>Conclusion</p></div>
</section></details></body></html>"""

BAD = f"""<!doctype html><html><head>{CSS}</head><body>
<section class='hero'><details class='paper-info'><div class='paper-info-grid'><div><strong>DOI</strong><span>10.0/example</span></div></div></details></section>
<details id='overview-bilingual-folded'><summary>一页概览与方法流程概括</summary>
<div class='overview-grid'><div class='overview-card'><h3>Q</h3><p>A</p></div></div><div class='method-flow'>Flow</div>
</details></body></html>"""


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        good = root / 'good.html'
        bad = root / 'bad.html'
        good.write_text(GOOD, 'utf-8')
        bad.write_text(BAD, 'utf-8')
        good_result = validate(good)
        bad_result = validate(bad)
        assert good_result['passed'], good_result
        assert not bad_result['passed'], bad_result
        expected = {'.overview-grid', '.overview-card', '.method-flow', '.paper-info-grid'}
        text = '\n'.join(bad_result['errors'])
        for selector in expected:
            assert selector in text, (selector, bad_result)
        print('V0.8.3 component-format regression tests passed')


if __name__ == '__main__':
    main()
