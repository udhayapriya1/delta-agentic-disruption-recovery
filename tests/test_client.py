import httpx
from delta_demo.client import RecoveryClient


def test_retry_preserves_idempotency_payload():
    bodies=[]
    def endpoint(request):
        bodies.append(request.content)
        return httpx.Response(503 if len(bodies)<3 else 200,json={'confirmation':'test-fixture'})
    client=RecoveryClient('https://unit.invalid','not-real-token',httpx.MockTransport(endpoint))
    result=client.request('POST','/rebook',json={'idempotency_key':'fixed-test-key'})
    assert result.status_code==200
    assert len(bodies)==3 and len(set(bodies))==1
    client.close()


def test_conflict_is_not_retried():
    calls=[]
    def endpoint(request):
        calls.append(1);return httpx.Response(409)
    client=RecoveryClient('https://unit.invalid','not-real-token',httpx.MockTransport(endpoint))
    assert client.request('POST','/rebook',json={'idempotency_key':'same-key'}).status_code==409
    assert len(calls)==1
    client.close()
