# -*- coding: utf-8 -*-
"""
Agent 通讯加密：AES-256-GCM（认证加密）+ gzip 压缩
信封格式：{"e": base64( nonce(12) || ciphertext || tag(16) )}
明文处理顺序：JSON → gzip 压缩 → AES-GCM 加密 → base64
密钥：由全局共享密钥 agent_comm_secret 经 SHA-256 派生 32 字节

去掉 token 后，GCM 的认证标签即为身份凭证：
只有持有共享密钥的一方才能构造出可被成功解密的合法报文。
"""
import base64
import gzip
import hashlib
import json

from flask import request, jsonify
from Crypto.Cipher import AES
from Crypto.Random import get_random_bytes

from modules.system.models import Setting

_NONCE_LEN = 12  # GCM 标准 nonce 长度（与 Go cipher.NewGCM 一致）
_TAG_LEN = 16    # GCM 认证标签长度


def _get_comm_key():
    """从 Setting 读取全局共享密钥并派生 32 字节 AES 密钥"""
    s = Setting.query.filter_by(key='agent_comm_secret').first()
    secret = s.value if s else ''
    return hashlib.sha256(secret.encode('utf-8')).digest()


def encrypt_dict(obj):
    """将 dict 压缩+加密，返回信封 dict {"e": base64}（供 jsonify）"""
    plaintext = json.dumps(obj, ensure_ascii=False).encode('utf-8')
    compressed = gzip.compress(plaintext)
    nonce = get_random_bytes(_NONCE_LEN)
    cipher = AES.new(_get_comm_key(), AES.MODE_GCM, nonce=nonce)
    ciphertext, tag = cipher.encrypt_and_digest(compressed)
    blob = nonce + ciphertext + tag
    return {'e': base64.b64encode(blob).decode('ascii')}


def encrypt_response(obj, code=200):
    """加密响应：返回 (envelope, code)"""
    return jsonify(encrypt_dict(obj)), code


def decrypt_request():
    """解密请求体信封，返回 dict；失败返回 None"""
    body = request.get_json(silent=True) or {}
    return _decrypt_blob(body.get('e', ''))


def encrypt_request_bytes(obj):
    """加密为可直接 POST 的请求体字节（Master 主动推送 Agent 用）"""
    return json.dumps(encrypt_dict(obj)).encode('utf-8')


def decrypt_bytes(data):
    """解密原始响应字节（解析 Agent 回包用），返回 dict；失败返回 None"""
    try:
        envelope = json.loads(data.decode('utf-8'))
    except Exception:
        return None
    if not isinstance(envelope, dict):
        return None
    return _decrypt_blob(envelope.get('e', ''))


def _decrypt_blob(blob_b64):
    """解密 base64 密文核心逻辑"""
    if not blob_b64:
        return None
    try:
        blob = base64.b64decode(blob_b64)
        nonce = blob[:_NONCE_LEN]
        tag = blob[-_TAG_LEN:]
        ciphertext = blob[_NONCE_LEN:-_TAG_LEN]
        cipher = AES.new(_get_comm_key(), AES.MODE_GCM, nonce=nonce)
        compressed = cipher.decrypt_and_verify(ciphertext, tag)
        plaintext = gzip.decompress(compressed)
        return json.loads(plaintext.decode('utf-8'))
    except Exception:
        return None
