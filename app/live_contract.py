"""Official equity LIMIT request validation only; contains no HTTP transport.

This module does not constitute a usable live executor. Wallet/asset selection,
account reconciliation, signed transport and lifecycle handling remain required.
"""
import hashlib
import hmac
import re
from urllib.parse import urlencode
from app.market import number, timestamp
from app.live_scope import InstrumentEvidence

PLACE_PATH = '/sapi/v1/equity/order/place'
CANCEL_PATH = '/sapi/v1/equity/order/cancel'
QUERY_PATH = '/sapi/v1/equity/order/detail'
SOURCE = 'https://developers.binance.com/en/docs/catalog/advanced-trading-stocks-trading/api/rest-api/trade'


def live_client_order_id(source_id, *, prefix='obr'):
    """Map a 64-char strategy SHA256 or exit key into Binance's 32-36 char clientOrderId format."""
    if not isinstance(source_id, str) or not source_id.strip():
        raise ValueError('INVALID_SOURCE_ORDER_ID')
    if not isinstance(prefix, str) or not re.fullmatch(r'[a-zA-Z0-9]{2,3}', prefix):
        raise ValueError('INVALID_CLIENT_ID_PREFIX')
    digest = hashlib.sha256(source_id.encode('utf-8')).hexdigest()[:32]
    client_id = f'{prefix}-{digest}'
    if not re.fullmatch(r'[a-zA-Z0-9_-]{32,36}', client_id):
        raise ValueError('INVALID_CLIENT_ORDER_ID')
    return client_id


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


def cancel_request(*, symbol, client_id, order_id=None):
    if not isinstance(symbol, str) or not re.fullmatch(r'[A-Z][A-Z0-9.-]{0,14}', symbol):
        raise ValueError('INVALID_SYMBOL')
    if not isinstance(client_id, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{32,36}', client_id):
        raise ValueError('INVALID_CLIENT_ORDER_ID')
    payload = {'symbol': symbol, 'origClientOrderId': client_id}
    if order_id is not None:
        if not isinstance(order_id, (str, int)) or not str(order_id).strip():
            raise ValueError('INVALID_ORDER_ID')
        payload['orderId'] = str(order_id)
    return payload


def query_request(*, symbol, client_id=None, order_id=None):
    if not isinstance(symbol, str) or not re.fullmatch(r'[A-Z][A-Z0-9.-]{0,14}', symbol):
        raise ValueError('INVALID_SYMBOL')
    if client_id is None and order_id is None:
        raise ValueError('ORDER_IDENTIFIER_REQUIRED')
    payload = {'symbol': symbol}
    if client_id is not None:
        if not isinstance(client_id, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{32,36}', client_id):
            raise ValueError('INVALID_CLIENT_ORDER_ID')
        payload['origClientOrderId'] = client_id
    if order_id is not None:
        if not isinstance(order_id, (str, int)) or not str(order_id).strip():
            raise ValueError('INVALID_ORDER_ID')
        payload['orderId'] = str(order_id)
    return payload


def sign_payload(params, secret, timestamp_ms, *, recv_window=5000):
    if not isinstance(secret, str) or len(secret) < 16:
        raise ValueError('INVALID_SIGNING_SECRET')
    timestamp(timestamp_ms)
    if type(recv_window) is not int or not 1 <= recv_window <= 60000:
        raise ValueError('INVALID_RECV_WINDOW')
    full = {**params, 'recvWindow': str(recv_window), 'timestamp': str(timestamp_ms)}
    query = urlencode(full)
    signature = hmac.new(secret.encode('utf-8'), query.encode('utf-8'), hashlib.sha256).hexdigest()
    return f'{query}&signature={signature}'
