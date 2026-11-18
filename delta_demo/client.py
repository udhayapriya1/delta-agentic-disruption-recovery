"""Bounded HTTP recovery; consequential retries retain the same idempotency payload."""
import time
import httpx


class RecoveryClient:
    def __init__(self, base_url, bearer_token, transport=None):
        self.client=httpx.Client(base_url=base_url,headers={'Authorization':'Bearer '+bearer_token},timeout=10,transport=transport)

    def close(self):
        self.client.close()

    def request(self, method, path, **kwargs):
        if method=='POST' and path in ['/rebook','/voucher'] and not kwargs.get('json',{}).get('idempotency_key'):
            raise ValueError('Consequential retry requires a persistent idempotency key')
        retryable=method=='GET' or (method=='POST' and path in ['/rebook','/voucher'])
        for attempt in range(3):
            try:
                response=self.client.request(method,path,**kwargs)
                if response.status_code not in [502,503,504] or not retryable or attempt==2:
                    return response
            except (httpx.TimeoutException,httpx.NetworkError):
                if not retryable or attempt==2:
                    raise
            time.sleep(.05 * 2**attempt)
        raise RuntimeError('unreachable')
