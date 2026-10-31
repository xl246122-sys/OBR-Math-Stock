"""The sole authenticated HTTP operation is a fixed read-only market endpoint."""
import json
import urllib.error
import urllib.request
from datetime import datetime, timezone


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None  # never forward the API header to another destination


def exchange_info(api_key):
    request = urllib.request.Request(
        "https://api.binance.com/sapi/v1/equity/market/exchangeInfo",
        headers={"X-MBX-APIKEY": api_key}, method="GET")
    result = {"checked_utc": datetime.now(timezone.utc).isoformat()}
    try:
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=20) as response:
            data = json.load(response)
            if not isinstance(data, dict) or not isinstance(data.get("symbols"), list):
                raise ValueError("INVALID_EXCHANGE_RESPONSE")
            result.update(http_status=response.status, symbols=data["symbols"])
    except urllib.error.HTTPError as error:
        result["http_status"] = error.code
        try:
            code = json.load(error).get("code")
            if type(code) is int:
                result["api_error_code"] = code
        except (ValueError, AttributeError):
            pass
    except Exception as error:
        result["error_type"] = type(error).__name__  # no header/body/credential logging
    return result
