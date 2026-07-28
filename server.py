import os
from flask import Flask, request, Response, send_from_directory
from flask_cors import CORS
import requests

app = Flask(__name__, static_folder='.', static_url_path='')
CORS(app)

@app.route('/')
def serve_index():
    return send_from_directory('.', 'index.html')

@app.route('/<path:path>')
def serve_static(path):
    if os.path.exists(os.path.join('.', path)):
        return send_from_directory('.', path)
    return send_from_directory('.', 'index.html')

@app.route('/api/verify', methods=['POST', 'OPTIONS'])
def verify_proxy():
    if request.method == 'OPTIONS':
        return Response(status=200)
    
    api_key = request.headers.get('x-api-key', '')
    if not api_key:
        auth_header = request.headers.get('Authorization', '')
        if auth_header.startswith('Bearer '):
            api_key = auth_header.split(' ')[1]
        else:
            api_key = auth_header

    payload = request.get_data()
    
    headers = {
        'Content-Type': 'application/json',
        'x-api-key': api_key,
        'User-Agent': 'VerifyEtVerifierProxy/1.0'
    }
    
    try:
        resp = requests.post(
            'https://verify.et/api/verify',
            data=payload,
            headers=headers,
            timeout=15
        )
        return Response(
            resp.content,
            status=resp.status_code,
            content_type=resp.headers.get('Content-Type', 'application/json')
        )
    except requests.exceptions.RequestException as e:
        return Response(
            f'{{"success": false, "message": "Proxy Error: {str(e)}"}}',
            status=500,
            content_type='application/json'
        )

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    print(f"Starting Verify.et Payment Proxy Server on http://0.0.0.0:{port}")
    app.run(host='0.0.0.0', port=port, debug=False)
