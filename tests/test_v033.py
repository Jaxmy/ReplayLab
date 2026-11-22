import json,shutil,subprocess,sys
from pathlib import Path
import pytest
from app.session import Session,MODULE_ROOT

@pytest.mark.skipif(sys.platform!='win32',reason='Windows PowerShell 5.1 regression')
def test_windows_powershell_decodes_and_parses_launch_scripts():
    result=subprocess.run([shutil.which('powershell.exe'),'-NoProfile','-ExecutionPolicy','Bypass','-File',str(MODULE_ROOT/'tests/check-powershell.ps1')],capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=30)
    assert result.returncode==0,result.stdout+result.stderr
    for name in ('start.ps1','stop.ps1','setup.ps1'):assert name+': Windows PowerShell 5.1 parse PASS' in result.stdout

def test_v032_record_still_restores_after_startup_hotfix(tmp_path):
    s=Session({'start':'2024-01-01','end':'2024-01-02'})
    try:
        s.step(2);name=s.save();path=tmp_path/'sessions'/name
        payload=json.loads(path.read_text('utf-8'));payload['platform']='0.3.2';path.write_text(json.dumps(payload),'utf-8')
        restored=Session.restore(name)
        try:assert restored.view()['cursor']==2 and restored.broker.account()==s.broker.account()
        finally:restored.close()
    finally:s.close()
