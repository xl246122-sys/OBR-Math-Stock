import pytest
from app.live_contract import limit_request
from app.live_scope import InstrumentEvidence,public_scope
from dataclasses import replace

EVIDENCE=InstrumentEvidence('TEST','STOCK','US','UNDERLYING_SECURITY','https://example.com/synthetic-only',1000,2000)


def request(**changes):
    values=dict(symbol='TEST',side='BUY',price='100.01',quantity='0.5',wallet='MAIN',quote_asset='USDC',client_id='a'*32,instrument=EVIDENCE,now_ms=1500)
    values.update(changes)
    return limit_request(**values)


def test_live_contract_is_explicit_limit_regular_session_and_no_tokenization():
    data=request()
    assert data['orderType']=='LIMIT' and data['tradingSession']=='RTH'
    assert data['walletType']=='MAIN' and data['tokenize']=='false'
    assert 'fee' not in data and 'notional' not in data


@pytest.mark.parametrize('changes',[{'price':'1.001'},{'price':'NaN'},{'quantity':'0'},
                                    {'wallet':''},{'quote_asset':''},{'client_id':'a'*64},{'side':'SHORT'}])
def test_invalid_live_contract_rejected(changes):
    with pytest.raises(ValueError):request(**changes)


@pytest.mark.parametrize('changes',[{'wallet':'CARD'},{'quote_asset':'USDT'}, {'instrument':None},
    {'instrument':replace(EVIDENCE,security_type='CRYPTO')},
    {'instrument':replace(EVIDENCE,security_type='OPTION')},
    {'instrument':replace(EVIDENCE,security_type='FUTURE')},
    {'instrument':replace(EVIDENCE,security_type='CFD')},
    {'instrument':replace(EVIDENCE,security_type='UNKNOWN')},
    {'instrument':replace(EVIDENCE,listing_country='GB')},
    {'instrument':replace(EVIDENCE,instrument_form='TOKENIZED')},
    {'instrument':replace(EVIDENCE,symbol='OTHER')},
    {'now_ms':2000},{'now_ms':999}])
def test_user_scope_is_enforced(changes):
    with pytest.raises(ValueError):request(**changes)


def test_equities_and_etfs_use_approved_wallet_without_tokenization():
    for kind in ('STOCK','ETF'):
        for side in ('BUY','SELL'):
            data=request(side=side,instrument=replace(EVIDENCE,security_type=kind))
            assert data['walletType']=='MAIN' and data['quoteAsset']=='USDC'
            assert data['tokenize']=='false'
    scope=public_scope()
    assert scope['sell_settlement_wallet']=='CARD' and scope['settlement_accepted']
    assert not scope['automatic_transfers']
