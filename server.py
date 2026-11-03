import os
import json
from flask import Flask, request, Response, send_from_directory, stream_with_context
from flask_cors import CORS
import requests

app = Flask(__name__, static_folder='.', static_url_path='')
CORS(app)

VERIFY_ET_BASE = 'https://verify.et'
# The verify.et key is a server-side secret, read from the environment (set it in the Render
# dashboard, never commit it). Rotating the key is now a one-field change here with no app rebuild,
# because the backend always authenticates to verify.et with THIS key and ignores whatever key a
# client happens to send (an older app build still ships a stale copy).
VERIFY_ET_API_KEY = os.environ.get('VERIFY_ET_API_KEY', '')

# --- AI vision extraction (reads the reference off a receipt image) -----------------
# The Android app POSTs { bank, imageBase64, prompt } to /api/verify/vision when its own
# on-device OCR cannot find the reference. We forward the image to an OpenRouter vision
# model and return the model's JSON straight through; the app reads extracted_value /
# extracted_type / confidence from it. The model is an env var so it can be swapped from
# the Render dashboard with no code change; the OpenRouter key is NEVER hardcoded.
OPENROUTER_URL = 'https://openrouter.ai/api/v1/chat/completions'
VISION_MODEL = os.environ.get('VISION_MODEL', 'google/gemini-2.5-flash-lite')
OPENROUTER_API_KEY = os.environ.get('OPENROUTER_API_KEY', '')

def get_api_key():
    # Always authenticate to verify.et with the backend's own key. A client-sent x-api-key is NOT
    # forwarded upstream, so rotating VERIFY_ET_API_KEY here never breaks an installed app that still
    # carries an old key. Returns '' only when the env var is unset (a misconfiguration), which the
    # callers turn into a 401/503 rather than silently calling verify.et unauthenticated.
    return VERIFY_ET_API_KEY

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

def _extract_json(text):
    """The model is told to return bare JSON; strip a ```json fence or surrounding prose if it adds one."""
    t = (text or '').strip()
    if t.startswith('```'):
        t = t.strip('`').strip()
        if t[:4].lower() == 'json':
            t = t[4:].strip()
    if not t.startswith('{'):
        start, end = t.find('{'), t.rfind('}')
        if start != -1 and end > start:
            t = t[start:end + 1]
    return t

# POST /api/verify/vision - read the transaction reference off a receipt image via an OpenRouter model
@app.route('/api/verify/vision', methods=['POST', 'OPTIONS'])
def verify_vision_proxy():
    if request.method == 'OPTIONS':
        return Response(status=200)

    # Light abuse gate: this route spends OpenRouter credit, so a caller must at least present the
    # app's key or a bearer token (the app always sends one). It is not a full auth check.
    if not (request.headers.get('Authorization') or request.headers.get('x-api-key')):
        return Response('{"error": "auth required"}', status=401, content_type='application/json')

    if not OPENROUTER_API_KEY:
        return Response('{"error": "vision model not configured"}', status=503, content_type='application/json')

    body = request.get_json(force=True, silent=True) or {}
    image_b64 = body.get('imageBase64') or ''
    prompt = body.get('prompt') or (
        'Extract the single transaction reference from this payment receipt. Respond with ONLY JSON: '
        '{"extracted_value": string, "extracted_type": "transaction_id"|"url"|"none", "confidence": "high"|"medium"|"low"}.'
    )
    if not image_b64:
        return Response('{"error": "imageBase64 required"}', status=400, content_type='application/json')

    data_url = image_b64 if image_b64.startswith('data:') else f'data:image/jpeg;base64,{image_b64}'
    payload = {
        'model': VISION_MODEL,
        'temperature': 0,
        'max_tokens': 400,
        'messages': [{
            'role': 'user',
            'content': [
                {'type': 'text', 'text': prompt},
                {'type': 'image_url', 'image_url': {'url': data_url}},
            ],
        }],
    }
    headers = {
        'Authorization': f'Bearer {OPENROUTER_API_KEY}',
        'Content-Type': 'application/json',
        'HTTP-Referer': 'https://server-q10f.onrender.com',
        'X-Title': 'DirexVerify',
    }
    try:
        resp = requests.post(OPENROUTER_URL, data=json.dumps(payload), headers=headers, timeout=45)
    except requests.exceptions.RequestException as e:
        # 502 is <500-but-not-429 to the app's rule, but a transport failure is genuinely retryable,
        # so report 503 and let the app's cold-start/retry handling take over.
        return Response(f'{{"error": "vision upstream error: {str(e)[:120]}"}}', status=503, content_type='application/json')

    if resp.status_code != 200:
        # Pass the retryable classes (429, 5xx) through so the app retries; collapse the rest to 502.
        code = resp.status_code if (resp.status_code == 429 or resp.status_code >= 500) else 502
        return Response(f'{{"error": "vision model http {resp.status_code}"}}', status=code, content_type='application/json')

    try:
        content = resp.json()['choices'][0]['message']['content']
    except (ValueError, KeyError, IndexError, TypeError):
        return Response('{"error": "vision model returned no content"}', status=502, content_type='application/json')

    # Return the model's own JSON straight through; the app reads extracted_value/extracted_type/confidence.
    return Response(_extract_json(content), status=200, content_type='application/json')

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    print(f"Starting Verify.et Full API Proxy Server on http://0.0.0.0:{port}")
    app.run(host='0.0.0.0', port=port, debug=False)
