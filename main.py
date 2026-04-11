"""LINE Calendar Bot - Flask + LINE Messaging API (requests only)"""
import os
import json
import hmac
import hashlib
import base64
import logging
import requests
from flask import Flask, request, abort
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(name)s %(levelname)s %(message)s',
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

LINE_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET', '').strip()
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN', '').strip()
LINE_USER_ID = os.environ.get('LINE_USER_ID', '').strip()

GEMINI_API_KEY = os.environ.get('OPENAI_API_KEY', '').strip()
GEMINI_API_URL = 'https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent'


def verify_signature(body: bytes, signature: str ) -> bool:
    """LINE Webhook署名検証"""
    hash_val = hmac.new(
        LINE_CHANNEL_SECRET.encode('utf-8'),
        body,
        hashlib.sha256
    ).digest()
    expected = base64.b64encode(hash_val).decode('utf-8')
    return hmac.compare_digest(expected, signature)


def send_line_message(user_id: str, text: str):
    """LINEにメッセージを送信する"""
    url = 'https://api.line.me/v2/bot/message/push'
    headers = {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ' + LINE_CHANNEL_ACCESS_TOKEN
    }
    payload = {
        'to': user_id,
        'messages': [{'type': 'text', 'text': text}]
    }
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=10 )
        logger.info('LINE push response: ' + str(resp.status_code))
        return resp.status_code == 200
    except Exception as e:
        logger.error('LINE push error: ' + str(e))
        return False


def reply_line_message(reply_token: str, text: str):
    """LINEにリプライメッセージを送信する"""
    url = 'https://api.line.me/v2/bot/message/reply'
    headers = {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ' + LINE_CHANNEL_ACCESS_TOKEN
    }
    payload = {
        'replyToken': reply_token,
        'messages': [{'type': 'text', 'text': text}]
    }
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=10 )
        logger.info('LINE reply response: ' + str(resp.status_code))
        if resp.status_code != 200:
            logger.error('LINE reply error body: ' + resp.text)
    except Exception as e:
        logger.error('LINE reply error: ' + str(e))


def analyze_message_with_ai(text: str) -> str:
    """Gemini APIでメッセージを分析して予定・締切を検出する"""
    try:
        url = GEMINI_API_URL + '?key=' + GEMINI_API_KEY
        payload = {
            'contents': [
                {
                    'parts': [
                        {
                            'text': 'あなたはフリーランスのアシスタントです。以下のメッセージから予定、締切、タスクを検出して日本語で簡潔に報告してください。予定や締切がない場合は「特に予定・締切はありません」と答えてください。\n\n' + text
                        }
                    ]
                }
            ]
        }
        resp = requests.post(url, json=payload, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            return data['candidates'][0]['content']['parts'][0]['text']
        else:
            logger.error('Gemini API error: ' + str(resp.status_code) + ' ' + resp.text)
            return 'AI分析エラー: ' + str(resp.status_code)
    except Exception as e:
        logger.error('AI analysis error: ' + str(e))
        return 'AI分析エラー: ' + str(e)


@app.route('/webhook', methods=['POST'])
def webhook():
    """LINE Webhookエンドポイント"""
    signature = request.headers.get('X-Line-Signature', '')
    body = request.get_data()

    if not verify_signature(body, signature):
        logger.warning('Invalid signature')
        abort(400)

    try:
        events = json.loads(body.decode('utf-8')).get('events', [])
    except Exception as e:
        logger.error('JSON parse error: ' + str(e))
        abort(400)

    for event in events:
        if event.get('type') == 'message' and event.get('message', {}).get('type') == 'text':
            reply_token = event.get('replyToken', '')
            user_id = event.get('source', {}).get('userId', '')
            text = event['message']['text']

            logger.info('Received message from ' + user_id + ': ' + text)

            analysis = analyze_message_with_ai(text)
            reply_text = '📋 メッセージ分析結果:\n' + analysis

            reply_line_message(reply_token, reply_text)

    return 'OK', 200


@app.route('/auth/google')
def auth_google():
    """Google OAuth2認証開始"""
    try:
        from google_calendar import get_auth_url
        auth_url = get_auth_url()
        return '<a href="' + auth_url + '">Googleカレンダーと連携する</a>'
    except Exception as e:
        return 'エラー: ' + str(e), 500


@app.route('/auth/google/callback')
def auth_google_callback():
    """Google OAuth2コールバック"""
    try:
        from google_calendar import handle_callback
        code = request.args.get('code', '')
        handle_callback(code)
        return 'Googleカレンダーの連携が完了しました！'
    except Exception as e:
        return 'エラー: ' + str(e), 500


@app.route('/test/morning')
def test_morning():
    """朝の通知テスト"""
    try:
        from scheduler import send_morning_summary
        send_morning_summary()
        return '朝の通知を送信しました！'
    except Exception as e:
        return 'エラー: ' + str(e), 500


@app.route('/')
def index():
    return '<h2>LINE Calendar Bot</h2><p>Status: 稼働中</p>'


def _startup():
    from scheduler import start_scheduler
    start_scheduler()


_startup()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
