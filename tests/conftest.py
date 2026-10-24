"""Keep generated regression sessions out of the user's session directory."""
import shutil
import pytest
@pytest.fixture(autouse=True)
def separate_test_sessions(monkeypatch,tmp_path):
    from app import session,server
    shutil.copytree(session.MODULE_ROOT/'strategies',tmp_path/'strategies')
    monkeypatch.setattr(session,'ROOT',tmp_path)
    monkeypatch.setattr(server,'ROOT',tmp_path)
