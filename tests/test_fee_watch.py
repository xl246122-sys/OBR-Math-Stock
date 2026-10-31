from copy import deepcopy
import pytest
from app.fee_watch import SOURCE, MAX_AGE_MS, update, view

NOW = 1793400000000

def observation():
    return {"source":SOURCE,"product":"DIRECT_US_EQUITIES","checked_ms":NOW,
            "terms":{"rules":[{"id":"promotion","rate":"0.0005","expires_ms":NOW+10000},
                              {"id":"vip","effective_ms":NOW+20000,"minimum":"0.17"}]}}


def test_initial_unchanged_changed_and_persistent_notification(tmp_path):
    path=tmp_path/"fees.json"
    original=observation()
    state, changed=update(path,original,NOW)
    assert not changed and state["change"] is None
    assert not update(path,original,NOW+1)[1]
    new=deepcopy(original); new["terms"]["rules"][0]["rate"]="0.0006"
    state,changed=update(path,new,NOW+2)
    assert changed and state["change"]["before"] == original["terms"]
    assert update(path,new,NOW+3)[0]["change"] == state["change"]


def test_future_rates_and_expiry_are_not_applied_early(tmp_path):
    path=tmp_path/"fees.json"
    state,_=update(path,observation(),NOW)
    assert state["active_rules"] == ["promotion"]
    state,changed=update(path,observation(),NOW+10000)
    assert changed and state["active_rules"] == []
    state,changed=update(path,observation(),NOW+20000)
    assert changed and state["active_rules"] == ["vip"]


def test_failed_import_keeps_baseline_and_stale_is_explicit(tmp_path):
    path=tmp_path/"fees.json"
    update(path,observation(),NOW)
    before=path.read_bytes()
    bad=observation();bad["source"]="https://example.com"
    with pytest.raises(ValueError):update(path,bad,NOW)
    assert path.read_bytes()==before
    assert view(path,NOW+MAX_AGE_MS+1)["status"] == "STALE"
    assert view(path,NOW)["account_fee_verified"] is False


def test_old_observation_cannot_replace_new(tmp_path):
    path=tmp_path/"fees.json"
    new=observation();new["checked_ms"]+=100
    update(path,new,NOW+100)
    with pytest.raises(ValueError,match="OUT_OF_ORDER"):
        update(path,observation(),NOW+100)
