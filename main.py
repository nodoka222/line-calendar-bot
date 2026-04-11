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


def verify_signature(body: bytes, signature: str) -> bool:
    hash_val = hmac.new(
        LINE_CHANNEL_SECRET.encode('utf-8'),
        body,
        hashlib.sha256
    ).digest()
    expected = base64.b64encode(hash_val).decode('utf-8')
    return hmac.compare_digest(expected, signature)


def send_line_message(user_id: str, text: str):
    url = 'https://api.line.me/v2/bot/message/push'
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {LINE_CHANNEL_ACCESS_TOKEN}'
    }
    payload = {'to': user_id, 'messages': [{'type': 'text', 'text': text}]}
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=10 )
        logger.info(f'LINE push response: {resp.status_code}')
        return resp.status_code == 200
    except Exception as e:
        logger.error(f'LINE push error: {e}')
        return False


def reply_line_message(reply_token: str, text: str):
    url = 'https://api.line.me/v2/bot/message/reply'
