"""LINE Calendar Bot"""
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
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
app = Flask(__name__)

LINE_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET', '').strip()
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN', '').strip()
LINE_USER_ID = os.environ.get('LINE_USER_ID', '').strip()


def verify_signature(body, signature):
    h = hmac.new(LINE_CHANNEL_SECRET.encode('utf-8'), body, hashlib.sha256).digest()
    return hmac.compare_digest(base64.b64encode(h).decode('utf-8'), signature)


def reply_line_message(reply_token, text):
    requests.post(
        'https://api.line.me/v2/bot/message/reply',
        headers={'Content-Type': 'application/json',
                 'Authorization': f'Bearer {LINE_CHANNEL_ACCESS_TOKEN}'},
        json={'replyToken': reply_token, 'messages': [{'type': 'text', 'text': text}]},
        timeout=10
     )


def send_line_message(user_id, text):
    requests.post(
        'https://api.line.me/v2/bot/message/push',
        headers={'Content-Type': 'application/json',
                 'Authorization': f'Bearer {LINE_CHANNEL_ACCESS_TOKEN}'},
        json={'to': user_id, 'messages': [{'type': 'text', 'text': text}]},
        timeout=10
     )


def get_todays_schedule_text():
    try:
        from google_calendar import get_todays_events
        events = get_todays_events()
        if not events:
            return '今日の予定はありません。'
        lines = ['今日の予定：\n']
        for e in events:
            start = e.get('start', {})
            t = start.get('dateTime', start.get('date', ''))
            if 'T' in t:
                t = t[11:16]
            lines.append(f'・{t} {e.get("summary", "（タイトルなし）")}')
        return '\n'.join(lines)
    except Exception as e:
        logger.error(f'カレンダーエラー: {e}')
        return 'カレンダーの取得に失敗しました。'


@app.route('/')
def index():
    return 'LINE Calendar Bot 稼働中'


@app.route('/webhook', methods=['POST'])
def webhook():
    sig = request.headers.get('X-Line-Signature', '')
    body = request.get_data()
    if not verify_signature(body, sig):
        abort(400)
    events = json.loads(body.decode('utf-8')).get('events', [])
    for event in events:
        if event.get('type') == 'message' and event['message'].get('type') == 'text':
            token = event.get('replyToken', '')
            text = event['message']['text']
            if any(kw in text for kw in ['今日', '予定', 'スケジュール']):
                reply_line_message(token, get_todays_schedule_text())
            else:
                reply_line_message(token, '「今日の予定」と送るとGoogleカレンダーの予定をお知らせします。')
    return 'OK', 200


@app.route('/test/morning')
def test_morning():
    try:
        from scheduler import send_morning_summary
        send_morning_summary()
        return '朝の通知を送信しました！'
    except Exception as e:
        return f'エラー: {e}', 500


@app.route('/auth/google')
def auth_google():
    try:
        from google_calendar import get_auth_url
        url = get_auth_url()
        return f'<a href="{url}">Googleカレンダーと連携する</a>'
    except Exception as e:
        return f'エラー: {e}', 500


@app.route('/auth/google/callback')
def auth_google_callback():
    try:
        from google_calendar import handle_callback
        handle_callback(request.args.get('code', ''))
        return 'Googleカレンダーの連携が完了しました！'
    except Exception as e:
        return f'エラー: {e}', 500


try:
    from scheduler import start_scheduler
    start_scheduler()
except Exception as e:
    logger.error(f'スケジューラー起動エラー: {e}')

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
