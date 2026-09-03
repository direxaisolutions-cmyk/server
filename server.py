import os
from flask import Flask, request, Response, send_from_directory, stream_with_context
from flask_cors import CORS
import requests

app = Flask(__name__, static_folder='.', static_url_path='')
CORS(app)

VERIFY_ET_BASE = 'https://verify.et'

def get_api_key():
    api_key = request.headers.get('x-api-key', '')
    if not api_key:
        auth_header = request.headers.get('Authorization', '')
        if auth_header.startswith('Bearer '):
            api_key = auth_header.split(' ')[1]
        else:
            api_key = auth_header
    return api_key

def build_headers(api_key, extra=None):
    headers = {
        'Content-Type': 'application/json',
        'x-api-key': api_key,
        'User-Agent': 'VerifyEtVerifierProxy/2.0'
    }
    # Forward optional headers
    for h in ['Idempotency-Key', 'X-Webhook-Url', 'Accept']:
        val = request.headers.get(h)
        if val:
            headers[h] = val
    if extra:
        headers.update(extra)
    return headers

@app.route('/')
def serve_index():
    return send_from_directory('.', 'index.html')

@app.route('/<path:path>')
def serve_static(path):
    if os.path.exists(os.path.join('.', path)):
        return send_from_directory('.', path)
    return send_from_directory('.', 'index.html')

# POST /api/verify - Submit verification
@app.route('/api/verify', methods=['POST', 'OPTIONS'])
def verify_proxy():
    if request.method == 'OPTIONS':
        return Response(status=200)
    
    api_key = get_api_key()
    if not api_key:
        return Response('{"success": false, "message": "API key required"}', status=401, content_type='application/json')

    payload = request.get_data()
    query_string = request.query_string.decode('utf-8')
    url = f'{VERIFY_ET_BASE}/api/verify'
    if query_string:
        url += f'?{query_string}'
    
    headers = build_headers(api_key)
    
    try:
        resp = requests.post(url, data=payload, headers=headers, timeout=30)
        return Response(resp.content, status=resp.status_code, content_type=resp.headers.get('Content-Type', 'application/json'))
    except requests.exceptions.RequestException as e:
        return Response(f'{{"success": false, "message": "Proxy Error: {str(e)}"}}', status=500, content_type='application/json')

# GET /api/verify/:requestId - Poll verification status
@app.route('/api/verify/<request_id>', methods=['GET', 'OPTIONS'])
def verify_status_proxy(request_id):
    if request.method == 'OPTIONS':
        return Response(status=200)
    
    api_key = get_api_key()
    if not api_key:
        return Response('{"success": false, "message": "API key required"}', status=401, content_type='application/json')

    url = f'{VERIFY_ET_BASE}/api/verify/{request_id}'
    headers = build_headers(api_key)
    
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        return Response(resp.content, status=resp.status_code, content_type=resp.headers.get('Content-Type', 'application/json'))
    except requests.exceptions.RequestException as e:
        return Response(f'{{"success": false, "message": "Proxy Error: {str(e)}"}}', status=500, content_type='application/json')

# GET /api/verify/:requestId/events - SSE stream
@app.route('/api/verify/<request_id>/events', methods=['GET', 'OPTIONS'])
def verify_events_proxy(request_id):
    if request.method == 'OPTIONS':
        return Response(status=200)
    
    api_key = get_api_key()
    if not api_key:
        return Response('{"success": false, "message": "API key required"}', status=401, content_type='application/json')

    url = f'{VERIFY_ET_BASE}/api/verify/{request_id}/events'
    headers = {
        'x-api-key': api_key,
        'Accept': 'text/event-stream',
        'User-Agent': 'VerifyEtVerifierProxy/2.0'
    }
    
    try:
        def generate():
            with requests.get(url, headers=headers, stream=True, timeout=60) as resp:
                for line in resp.iter_lines(decode_unicode=True):
                    if line is not None:
                        yield line + '\n'
        
        return Response(stream_with_context(generate()), content_type='text/event-stream', headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no'
        })
    except requests.exceptions.RequestException as e:
        return Response(f'{{"success": false, "message": "Stream Error: {str(e)}"}}', status=500, content_type='application/json')

# GET /api/verify/history - Verification history
@app.route('/api/verify/history', methods=['GET', 'OPTIONS'])
def verify_history_proxy():
    if request.method == 'OPTIONS':
        return Response(status=200)
    
    api_key = get_api_key()
    if not api_key:
        return Response('{"success": false, "message": "API key required"}', status=401, content_type='application/json')

    query_string = request.query_string.decode('utf-8')
    url = f'{VERIFY_ET_BASE}/api/verify/history'
    if query_string:
        url += f'?{query_string}'
    
    headers = build_headers(api_key)
    
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        return Response(resp.content, status=resp.status_code, content_type=resp.headers.get('Content-Type', 'application/json'))
    except requests.exceptions.RequestException as e:
        return Response(f'{{"success": false, "message": "Proxy Error: {str(e)}"}}', status=500, content_type='application/json')

# POST /api/verify/test-webhook - Test webhook
@app.route('/api/verify/test-webhook', methods=['POST', 'OPTIONS'])
def verify_test_webhook_proxy():
    if request.method == 'OPTIONS':
        return Response(status=200)
    
    api_key = get_api_key()
    if not api_key:
        return Response('{"success": false, "message": "API key required"}', status=401, content_type='application/json')

    payload = request.get_data()
    url = f'{VERIFY_ET_BASE}/api/verify/test-webhook'
    headers = build_headers(api_key)
    
    try:
        resp = requests.post(url, data=payload, headers=headers, timeout=15)
        return Response(resp.content, status=resp.status_code, content_type=resp.headers.get('Content-Type', 'application/json'))
    except requests.exceptions.RequestException as e:
        return Response(f'{{"success": false, "message": "Proxy Error: {str(e)}"}}', status=500, content_type='application/json')

# GET /api/credits/* - Credits endpoints
@app.route('/api/credits/<path:subpath>', methods=['GET', 'OPTIONS'])
def credits_proxy(subpath):
    if request.method == 'OPTIONS':
        return Response(status=200)
    
    api_key = get_api_key()
    if not api_key:
        return Response('{"success": false, "message": "API key required"}', status=401, content_type='application/json')

    url = f'{VERIFY_ET_BASE}/api/credits/{subpath}'
    headers = build_headers(api_key)
    
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        return Response(resp.content, status=resp.status_code, content_type=resp.headers.get('Content-Type', 'application/json'))
    except requests.exceptions.RequestException as e:
        return Response(f'{{"success": false, "message": "Proxy Error: {str(e)}"}}', status=500, content_type='application/json')

# GET /api/uptime/* - Uptime endpoints
@app.route('/api/uptime/<path:subpath>', methods=['GET', 'OPTIONS'])
def uptime_proxy(subpath):
    if request.method == 'OPTIONS':
        return Response(status=200)

    api_key = get_api_key()
    url = f'{VERIFY_ET_BASE}/api/uptime/{subpath}'
    headers = build_headers(api_key) if api_key else {'User-Agent': 'VerifyEtVerifierProxy/2.0'}

    try:
        resp = requests.get(url, headers=headers, timeout=15)
        return Response(resp.content, status=resp.status_code, content_type=resp.headers.get('Content-Type', 'application/json'))
    except requests.exceptions.RequestException as e:
        return Response(f'{{"success": false, "message": "Proxy Error: {str(e)}"}}', status=500, content_type='application/json')

# GET /api/uptime - Root uptime
@app.route('/api/uptime', methods=['GET', 'OPTIONS'])
def uptime_root_proxy():
    if request.method == 'OPTIONS':
        return Response(status=200)

    api_key = get_api_key()
    url = f'{VERIFY_ET_BASE}/api/uptime'
    headers = build_headers(api_key) if api_key else {'User-Agent': 'VerifyEtVerifierProxy/2.0'}

    try:
        resp = requests.get(url, headers=headers, timeout=15)
        return Response(resp.content, status=resp.status_code, content_type=resp.headers.get('Content-Type', 'application/json'))
    except requests.exceptions.RequestException as e:
        return Response(f'{{"success": false, "message": "Proxy Error: {str(e)}"}}', status=500, content_type='application/json')

# GET /api/bank-accounts - Bank accounts
@app.route('/api/bank-accounts', methods=['GET', 'POST', 'OPTIONS'])
def bank_accounts_proxy():
    if request.method == 'OPTIONS':
        return Response(status=200)
    
    api_key = get_api_key()
    if not api_key:
        return Response('{"success": false, "message": "API key required"}', status=401, content_type='application/json')

    url = f'{VERIFY_ET_BASE}/api/bank-accounts'
    headers = build_headers(api_key)
    
    try:
        if request.method == 'POST':
            resp = requests.post(url, data=request.get_data(), headers=headers, timeout=15)
        else:
            resp = requests.get(url, headers=headers, timeout=15)
        return Response(resp.content, status=resp.status_code, content_type=resp.headers.get('Content-Type', 'application/json'))
    except requests.exceptions.RequestException as e:
        return Response(f'{{"success": false, "message": "Proxy Error: {str(e)}"}}', status=500, content_type='application/json')

# GET /api/metrics - Metrics
@app.route('/api/metrics', methods=['GET', 'OPTIONS'])
def metrics_proxy():
    if request.method == 'OPTIONS':
        return Response(status=200)
    
    api_key = get_api_key()
    if not api_key:
        return Response('{"success": false, "message": "API key required"}', status=401, content_type='application/json')

    url = f'{VERIFY_ET_BASE}/api/metrics'
    headers = build_headers(api_key)
    
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        return Response(resp.content, status=resp.status_code, content_type=resp.headers.get('Content-Type', 'application/json'))
    except requests.exceptions.RequestException as e:
        return Response(f'{{"success": false, "message": "Proxy Error: {str(e)}"}}', status=500, content_type='application/json')

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    print(f"Starting Verify.et Full API Proxy Server on http://0.0.0.0:{port}")
    app.run(host='0.0.0.0', port=port, debug=False)
