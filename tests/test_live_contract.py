import json
from decimal import Decimal
import pytest
from app.execution import Fees
from app.live_contract import limit_request, cancel_request, query_request, live_client_order_id, sign_payload
from app.live_scope import InstrumentEvidence, InstrumentRegistry, public_scope
from app.live_execution import LiveLedger, RecordedLiveTransport
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


def test_client_order_id_mapping_and_signed_payload():
    sha_id = 'f' * 64
    cid = live_client_order_id(sha_id)
    assert len(cid) == 36 and cid.startswith('obr-')
    req = request(client_id=cid)
    assert req['clientOrderId'] == cid
    cancel = cancel_request(symbol='TEST', client_id=cid, order_id='12345')
    assert cancel['origClientOrderId'] == cid and cancel['orderId'] == '12345'
    query = query_request(symbol='TEST', client_id=cid)
    assert query['origClientOrderId'] == cid
    signed = sign_payload(req, 's' * 32, 1793400000000)
    assert 'recvWindow=5000&timestamp=1793400000000&signature=' in signed
    assert ('s' * 32) not in signed


def test_instrument_registry_loads_and_filters_authoritative_evidence(tmp_path):
    path = tmp_path / 'instrument-evidence.json'
    path.write_text(json.dumps({
        'schema': 1,
        'instruments': [
            {
                'symbol': 'AAPL',
                'security_type': 'STOCK',
                'listing_country': 'US',
                'instrument_form': 'UNDERLYING_SECURITY',
                'source_reference': 'https://www.sec.gov/edgar',
                'checked_ms': 1000,
                'expires_ms': 50000,
            },
            {
                'symbol': 'FAKE',
                'security_type': 'CRYPTO',
                'listing_country': 'US',
                'instrument_form': 'TOKENIZED',
                'source_reference': 'https://example.com/bad',
                'checked_ms': 1000,
                'expires_ms': 50000,
            },
        ],
    }), encoding='utf-8')
    reg = InstrumentRegistry.load(path)
    summary = reg.summary(['AAPL', 'FAKE', 'MSFT'], 2000)
    assert summary['verified_symbols'] == ['AAPL']
    assert summary['verified_count'] == 1 and summary['unverified_count'] == 2
    assert summary['status'] == 'PARTIAL_VERIFIED'


def test_live_ledger_card_settlement_unknown_order_and_manual_position_isolation():
    fees = Fees(Decimal('0.0005'), Decimal('0.0005'), Decimal('0.17'))
    ledger = LiveLedger('600', '300', fees, max_positions=2)
    transport = RecordedLiveTransport()
    with pytest.raises( PermissionError ):
        transport.place_order({'provenance': 'SIMULATED', 'clientOrderId': 'a' * 32}, 1500)
    # Cannot submit before startup reconciliation
    with pytest.raises(ValueError, match='LIVE_ACCOUNT_NOT_RECONCILED'):
        ledger.submit_entry(source_id='sig-1', symbol='TEST', price='100.00', quantity='2', instrument=EVIDENCE, transport=transport, now_ms=1500)
    # Reconcile with a pre-existing manual position on MANUAL_SYM
    assert ledger.reconcile_account(
        main_usdc_available='600',
        exchange_positions={'MANUAL': '5'},
        open_orders=[],
        now_ms=1500,
    )
    assert ledger.external_positions['MANUAL'] == Decimal('5')
    assert 'MANUAL' not in ledger.strategy_positions
    manual_ev = replace(EVIDENCE, symbol='MANUAL')
    with pytest.raises(ValueError, match='EXTERNAL_POSITION_ISOLATED'):
        ledger.submit_entry(source_id='sig-m', symbol='MANUAL', price='50.00', quantity='1', instrument=manual_ev, transport=transport, now_ms=1500)

    # Submit BUY order: status='S' is ACCEPTED_PENDING_REPORT, NOT FILLED
    buy_order = ledger.submit_entry(source_id='sig-1', symbol='TEST', price='100.00', quantity='2', instrument=EVIDENCE, transport=transport, now_ms=1500)
    assert buy_order.state == 'ACCEPTED_PENDING_REPORT'
    assert ledger.main_usdc_reserved == Decimal('200.17')
    assert ledger.main_usdc_free == Decimal('399.83')
    assert 'TEST' not in ledger.strategy_positions

    # Apply execution report for BUY fill
    ledger.apply_execution_report({
        'clientOrderId': buy_order.client_id,
        'status': 'FILLED',
        'filledQty': '2',
        'lastPrice': '100.00',
        'fee': '0.17',
        'tradeId': 't-1',
    }, 1600)
    assert buy_order.state == 'FILLED'
    assert ledger.main_usdc_reserved == Decimal('0')
    assert ledger.strategy_positions['TEST'].quantity == Decimal('2')

    # Submit SELL exit order and fill -> settles to CARD wallet, never added to MAIN USDC
    sell_order = ledger.submit_exit(source_id='exit-1', symbol='TEST', price='102.00', quantity='2', reason='TAKE_PROFIT', instrument=EVIDENCE, transport=transport, now_ms=1700)
    assert sell_order.state == 'ACCEPTED_PENDING_REPORT'
    ledger.apply_execution_report({
        'clientOrderId': sell_order.client_id,
        'status': 'FILLED',
        'filledQty': '2',
        'lastPrice': '102.00',
        'fee': '0.17',
        'tradeId': 't-2',
    }, 1800)
    assert sell_order.state == 'FILLED'
    assert ledger.strategy_positions['TEST'].quantity == Decimal('0')
    assert ledger.main_usdc_free == Decimal('399.83')  # Unchanged: no auto-transfer from CARD
    assert ledger.card_settlement_usdc == Decimal('203.83')
    assert ledger.realized_pnl_usdc == Decimal('3.66')

    # Timed-out order creation latches UNKNOWN_ORDER_STATE without releasing reserved funds
    timeout_transport = RecordedLiveTransport({('PLACE', live_client_order_id('sig-timeout')): TimeoutError('network timeout')})
    unknown = ledger.submit_entry(source_id='sig-timeout', symbol='TEST', price='100.00', quantity='1', instrument=EVIDENCE, transport=timeout_transport, now_ms=1900)
    assert unknown.state == 'UNKNOWN_ORDER_STATE'
    assert ledger.main_usdc_reserved == Decimal('100.17')
    with pytest.raises(ValueError, match='LIVE_UNKNOWN_ORDER_STATE'):
        ledger.submit_entry(source_id='sig-blocked', symbol='TEST', price='100.00', quantity='1', instrument=EVIDENCE, transport=transport, now_ms=1950)
