import json
from decimal import Decimal as D
import pytest
from app.paper_config import PaperConfig
from app.execution import PaperBroker
from tests.test_execution import SESSION, NOW, FEES, quote


def test_defaults_and_custom_config(tmp_path):
    assert PaperConfig().public() == {"initial_cash":"600", "per_order_budget":"300", "max_positions":2,
                                      "fee_policy":"BINANCE_OFFICIAL_DYNAMIC","max_daily_loss":"6.00",
                                      "max_exposure":"600","max_daily_symbols":5}
    path = tmp_path / "paper.json"
    path.write_text(json.dumps({"paper_mode":True,"live_trading_enabled":False,
                               "initial_cash":"1200","per_order_budget":"400","max_positions":3}))
    assert PaperConfig.load(path).max_positions == 3
    assert PaperConfig.load(path).initial_cash == 1200


@pytest.mark.parametrize("kwargs", [{"initial_cash":"NaN"}, {"per_order_budget":"601"},
                                    {"max_positions":True}, {"max_positions":0},
                                    {"fee_policy":"ZERO_FEES"}])
def test_invalid_configuration(kwargs):
    with pytest.raises(ValueError):
        PaperConfig(**kwargs)


def test_pending_unknown_and_filled_positions_consume_slots():
    b = PaperBroker(600,300,FEES,SESSION)
    b.submit("one","TEST",100,1,NOW)
    b.submit("two","OTHER",100,1,NOW)
    b.cancel("two", confirmed=False)
    b.on_quote(quote(),NOW+1)
    with pytest.raises(ValueError,match="POSITION_LIMIT"):
        b.submit("three","THIRD",100,1,NOW+2)
    restored = PaperBroker.restore(json.loads(json.dumps(b.snapshot(),default=str)))
    assert restored.max_positions == 2
    with pytest.raises(ValueError,match="POSITION_LIMIT"):
        restored.submit("three","THIRD",100,1,NOW+2)


def test_confirmed_cancel_releases_slot_but_partial_fill_does_not():
    b = PaperBroker(600,300,FEES,SESSION)
    b.submit("one","TEST",100,2,NOW)
    b.submit("two","OTHER",100,1,NOW)
    b.on_quote(quote(size=1),NOW+1)
    b.cancel("one")
    with pytest.raises(ValueError,match="POSITION_LIMIT"):
        b.submit("three","THIRD",100,1,NOW+2)
    b.cancel("two")
    b.submit("three","THIRD",100,1,NOW+2)
    assert b.positions["TEST"].quantity == D(1)
