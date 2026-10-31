"""Official equity LIMIT request validation only; contains no HTTP transport.

This module does not constitute a usable live executor. Wallet/asset selection,
account reconciliation, signed transport and lifecycle handling remain required.
"""
import re
from app.market import number
from app.live_scope import InstrumentEvidence

PLACE_PATH = '/sapi/v1/equity/order/place'
SOURCE = 'https://developers.binance.com/en/docs/catalog/advanced-trading-stocks-trading/api/rest-api/trade'


def limit_request(*, symbol, side, price, quantity, wallet, quote_asset, client_id, instrument=None, now_ms=None):
    if not isinstance(symbol,str) or not re.fullmatch(r'[A-Z][A-Z0-9.-]{0,14}',symbol):
        raise ValueError('INVALID_SYMBOL')
    if side not in {'BUY','SELL'} or wallet != 'MAIN':
        raise ValueError('INVALID_SIDE_OR_WALLET')
    if quote_asset != 'USDC':
        raise ValueError('USDC_ONLY')
    if not isinstance(instrument,InstrumentEvidence):
        raise ValueError('INSTRUMENT_EVIDENCE_REQUIRED')
    instrument.require_allowed(symbol,now_ms)
    if not isinstance(client_id,str) or not re.fullmatch(r'[a-zA-Z0-9_-]{32,36}',client_id):
        raise ValueError('INVALID_CLIENT_ORDER_ID')
    price=number(price,positive=True);quantity=number(quantity,positive=True)
    if price.as_tuple().exponent < -2:
        raise ValueError('PRICE_PRECISION_EXCEEDS_TWO_DECIMALS')
    return {'symbol':symbol,'side':side,'orderType':'LIMIT','price':format(price,'f'),
            'quantity':format(quantity,'f'),'walletType':wallet,'quoteAsset':quote_asset,
            'clientOrderId':client_id,'timeInForce':'DAY','tradingSession':'RTH','tokenize':'false'}
