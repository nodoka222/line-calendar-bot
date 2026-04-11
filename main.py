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

LINE_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET', '')
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN', '')
LINE_USER_ID = os.environ.get('LINE_USER_ID', '')


def verify_signature(body: bytes, signature: str) -> bool:
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
        'Authorization': f'Bearer {LINE_CHANNEL_ACCESS_TOKEN}'
    }
    payload = {
        'to': user_id,
        'messages': [{'type': 'text', 'text': text}]
    }
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=10 )
        logger.info(f'LINE push response: {resp.status_code}')
        return resp.status_code == 200
    except Exception as e:
        logger.error(f'LINE push error: {e}')
        return False


def reply_line_message(reply_token: str, text: str):
    """LINEにリプライメッセージを送信する"""
    url = 'https://api.line.me/v2/bot/message/reply'
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {LINE_CHANNEL_ACCESS_TOKEN}'
    }
    payload = {
        'replyToken': reply_token,
        'messages': [{'type': 'text', 'text': text}]
    }
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=10 )
        logger.info(f'LINE reply response: {resp.status_code}')
    except Exception as e:
        logger.error(f'LINE reply error: {e}')


def analyze_message_with_ai(text: str) -> str:
    """AIでメッセージを分析して予定・締切を検出する"""
    try:
        from openai import OpenAI
        api_key = os.environ.get('OPENAI_API_KEY', '')

        client = OpenAI(
            api_key=api_key,
            base_url='https://generativelanguage.googleapis.com/v1beta/openai/'
         )

        response = client.chat.completions.create(
            model='gemini-2.0-flash',
            messages=[
                {
                    'role': 'system',
                    'content': 'あなたはフリーランスのアシスタントです。メッセージから予定、締切、タスクを検出して日本語で簡潔に報告してください。予定や締切がない場合は「特に予定・締切はありません」と答えてください。'
                },
                {
                    'role': 'user',
                    'content': f'以下のメッセージから予定・締切・タスクを検出してください:\n\n{text}'
                }
            ],
            max_tokens=500
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f'AI analysis error: {e}')
        return f'AI分析エラー: {str(e)}'


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
        logger.error(f'JSON parse error: {e}')
        abort(400)

    for event in events:
        if event.get('type') == 'message' and event.get('message', {}).get('type') == 'text':
            reply_token = event.get('replyToken', '')
            user_id = event.get('source', {}).get('userId', '')
            text = event['message']['text']

            logger.info(f'Received message from {user_id}: {text}')

            if user_id and not LINE_USER_ID:
                logger.info(f'LINE User ID detected: {user_id}')

            analysis = analyze_message_with_ai(text)
            reply_text = f'📋 メッセージ分析結果:\n{analysis}'

            reply_line_message(reply_token, reply_text)

    return 'OK', 200


@app.route('/auth/google')
def auth_google():
    """Google OAuth2認証開始"""
    try:
        from google_calendar import get_auth_url
        auth_url = get_auth_url()
        return f'<a href="{auth_url}">Googleカレンダーと連携する</a>'
    except Exception as e:
        return f'エラー: {e}', 500


@app.route('/auth/google/callback')
def auth_google_callback():
    """Google OAuth2コールバック"""
    try:
        from google_calendar import handle_callback
        code = request.args.get('code', '')
        handle_callback(code)
        return 'Googleカレンダーの連携が完了しました！LINEに通知します。'
    except Exception as e:
        return f'エラー: {e}', 500


@app.route('/test/morning')
def test_morning():
    """朝の通知テスト"""
    try:
        from scheduler import send_morning_summary
        send_morning_summary()
        return '朝の通知を送信しました！'
    except Exception as e:
        return f'エラー: {e}', 500


@app.route('/')
def index():
    return '''<h2>LINE Calendar Bot</h2>
<p>Status: 稼働中</p>
<p><a href="/auth/google">Googleカレンダーと連携する</a></p>
<p><a href="/test/morning">朝の通知テスト</a></p>'''


def _startup():
    from scheduler import start_scheduler
    start_scheduler()


_startup()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
