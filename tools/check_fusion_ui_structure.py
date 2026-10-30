"""Ensure extensions leave original markup, renderer and theme CSS intact."""
import hashlib
import json
import subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
BASE='c0619f3'

def original(path):
    return subprocess.check_output(['git','show',f'{BASE}:{path}'],cwd=ROOT).decode('utf-8').replace('\r\n','\n')

def main():
    result={}
    for name in ['style.css','pages.css','chrome.js','app.js']:
        path='ui/web/'+name
        result[name+'_unchanged']=original(path)==(ROOT/path).read_text(encoding='utf-8')
    for name in ['monitor.html','detail.html']:
        text=(ROOT/'ui/web'/name).read_text(encoding='utf-8')
        additions=['<script src="/static/fusion-v2.js"></script>\n']
        if name=='monitor.html':
            additions+=['<link rel="stylesheet" href="/static/fusion-v2.css">\n',
                        '      <section class="mon-sec fusion-extension" id="fusionV2Mount" aria-label="多模型融合监测"></section>\n\n']
        else:additions+=['              <div class="note" id="fusionModeBadge">等待融合模式数据</div>\n']
        for addition in additions:
            assert text.count(addition)==1
            text=text.replace(addition,'',1)
        result[name+'_original_markup_preserved']=text==original('ui/web/'+name)
    assert all(result.values()),result
    (ROOT/'docs/validation/ui_structure.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2))

if __name__=='__main__':main()
