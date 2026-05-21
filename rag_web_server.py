#!/usr/bin/env python3
"""Academic RAG Web Backend - Hybrid Search"""

import os, sys, json, uuid, shutil, requests, math, re, logging, threading, atexit
import hashlib, base64, hmac, time as _time
import html as html_lib
from pathlib import Path
from datetime import datetime
from urllib.parse import quote
from flask import Flask, request, jsonify, send_from_directory, Response, g
from flask_cors import CORS
from werkzeug.utils import secure_filename
from functools import wraps

BASE_DIR = os.path.abspath(os.getenv('RAG_BASE_DIR', os.path.dirname(__file__)))
app = Flask(__name__, static_folder=os.path.join(BASE_DIR, 'static'))
CORS(app)
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

CONFIG = {
    'base_dir': BASE_DIR,
    'ollama_url': os.getenv('OLLAMA_BASE_URL', 'http://localhost:11434'),
    'embedding_model': os.getenv('EMBEDDING_MODEL', 'bge-m3'),
    'chat_model': os.getenv('OLLAMA_CHAT_MODEL', 'mistral-nemo'),
    'deepseek_api_key': os.getenv('DEEPSEEK_API_KEY', ''),
    'deepseek_model': os.getenv('DEEPSEEK_MODEL', 'deepseek-chat'),
    'deepseek_base_url': os.getenv('DEEPSEEK_BASE_URL', 'https://api.deepseek.com/v1'),
    'auth_code': os.getenv('RAG_AUTH_CODE', 'change-me'),
    'upload_dir': os.path.join(BASE_DIR, 'uploads'),
    'session_dir': os.path.join(BASE_DIR, 'chat_sessions'),
    'export_api_key': os.getenv('RAG_EXPORT_API_KEY') or None,
}
DEEP_READS_DIR = os.path.join(CONFIG['base_dir'], 'deep_reads')
os.makedirs(DEEP_READS_DIR, exist_ok=True)
if not os.path.exists(CONFIG['upload_dir']):
    os.makedirs(CONFIG['upload_dir'], exist_ok=True)
if not os.path.exists(CONFIG['session_dir']):
    os.makedirs(CONFIG['session_dir'], exist_ok=True)
ALLOWED_EXTENSIONS = {'pdf', 'txt', 'md', 'json', 'csv'}
BATCH_EXTENSIONS = {'pdf', 'txt', 'md', 'json', 'csv', 'zip'}

# ---- User system globals ----
USER_DATA_DIR = os.path.join(CONFIG['base_dir'], 'user_data')
USERS_FILE = os.path.join(CONFIG['base_dir'], 'users.json')
JWT_SECRET = os.getenv('RAG_JWT_SECRET', 'change-me-in-production')
os.makedirs(USER_DATA_DIR, exist_ok=True)

# ---- Usage tracking ----
USAGE_FILE = os.path.join(CONFIG['base_dir'], 'usage_stats.json')
_usage_lock = threading.Lock()
_usage_data = {}  # {username: {endpoint: count, ...}, ...}

def _load_usage():
    """Load usage stats from disk"""
    global _usage_data
    try:
        if os.path.exists(USAGE_FILE):
            with open(USAGE_FILE, 'r') as f:
                _usage_data = json.load(f)
    except:
        _usage_data = {}

def _save_usage():
    """Save usage stats to disk"""
    try:
        with open(USAGE_FILE, 'w') as f:
            json.dump(_usage_data, f, indent=2, ensure_ascii=False)
    except:
        pass

_load_usage()

ENDPOINT_CATEGORIES = {
    '查询': ['/api/query', '/api/search', '/api/ask', '/api/chat', '/api/v1/chat/completions'],
    '文档浏览': ['/api/knowledge-bases', '/api/kb-documents', '/api/kb-document-detail', '/api/tags'],
    '知识库管理': ['/api/create', '/api/delete-kb', '/api/rename-kb'],
    '文档上传': ['/api/upload', '/api/batch-upload'],
    '精读报告': ['/api/prefetch'],
    '论文撰写': ['/api/papers', '/api/papers/'],
    '文档修改': ['/api/docmod'],
    'Agent': ['/api/agent/chat', '/api/agent/sessions'],
}

@app.after_request
def track_usage(response):
    """Track API usage after each request"""
    if hasattr(g, 'user') and request.path.startswith('/api/'):
        endpoint = request.path
        with _usage_lock:
            if g.user not in _usage_data:
                _usage_data[g.user] = {}
            if endpoint not in _usage_data[g.user]:
                _usage_data[g.user][endpoint] = 0
            _usage_data[g.user][endpoint] += 1
            total = sum(sum(v.values()) for v in _usage_data.values())
            if total % 10 == 0:
                _save_usage()
    return response

def generate_jwt(username, role, expires_hours=72):
    """Generate a simple JWT token: base64(header).base64(payload).hmac(signature)"""
    header = base64.urlsafe_b64encode(json.dumps({'alg': 'HS256', 'typ': 'JWT'}).encode()).decode().rstrip('=')
    payload = {
        'username': username,
        'role': role,
        'iat': int(_time.time()),
        'exp': int(_time.time()) + expires_hours * 3600,
    }
    payload_b64 = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip('=')
    signature = hmac.new(JWT_SECRET.encode(), f'{header}.{payload_b64}'.encode(), hashlib.sha256).hexdigest()
    return f'{header}.{payload_b64}.{signature}'

def verify_jwt(token):
    """Verify JWT token, return {username, role} or None."""
    try:
        parts = token.split('.')
        if len(parts) != 3:
            return None
        header_b64, payload_b64, signature = parts
        expected_sig = hmac.new(JWT_SECRET.encode(), f'{header_b64}.{payload_b64}'.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected_sig):
            return None
        # Pad base64
        padded = payload_b64 + '=' * (4 - len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded))
        if payload.get('exp', 0) < _time.time():
            return None
        return {'username': payload['username'], 'role': payload['role']}
    except Exception:
        return None

def hash_password(password):
    return 'sha256:' + hashlib.sha256(password.encode()).hexdigest()

def check_password(password, password_hash):
    return hash_password(password) == password_hash

def load_users():
    """Load users from users.json. Create default admin on first run."""
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    # First run: create default admin
    users = {
        'admin': {
            'password_hash': hash_password('admin123'),
            'role': 'admin',
            'created_at': datetime.now().isoformat(),
            'display_name': '管理员',
        }
    }
    save_users(users)
    return users

def save_users(users):
    with open(USERS_FILE, 'w', encoding='utf-8') as f:
        json.dump(users, f, ensure_ascii=False, indent=2)

def call_llm(messages, timeout=60, prefer_cloud=True):
    """Call LLM: prefer DeepSeek cloud API, fallback to local Ollama."""
    if prefer_cloud:
        ds_url = CONFIG.get('deepseek_base_url', 'https://api.deepseek.com/v1').rstrip('/') + '/chat/completions'
        ds_key = CONFIG.get('deepseek_api_key', '') or os.environ.get('DEEPSEEK_API_KEY', '')
        ds_model = CONFIG.get('deepseek_model', 'deepseek-chat')
        if ds_key:
            try:
                r = requests.post(ds_url,
                    headers={'Authorization': f'Bearer {ds_key}', 'Content-Type': 'application/json'},
                    json={'model': ds_model, 'messages': messages, 'temperature': 0.1, 'max_tokens': 1024},
                    timeout=timeout)
                r.raise_for_status()
                return r.json()['choices'][0]['message']['content'].strip()
            except Exception as e:
                logger.warning(f"DeepSeek call failed, falling back to local: {e}")
    # Fallback: local Ollama
    r = requests.post(f"{CONFIG['ollama_url']}/api/chat",
        json={'model': CONFIG['chat_model'], 'messages': messages, 'stream': False,
              'options': {'temperature': 0.1, 'num_predict': 512}},
        timeout=min(timeout, 180))
    return r.json()['message']['content'].strip()

def require_auth(roles=None):
    """Parameterized auth decorator.
    roles=None: any logged-in user
    roles=['admin']: admin only
    Requires valid JWT token.
    """
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            token = request.headers.get('Authorization', '')
            if token.startswith('Bearer '):
                token = token[7:]
            
            payload = verify_jwt(token)
            if not payload:
                return jsonify({'error': 'Unauthorized'}), 401
            g.user = payload['username']
            g.role = payload['role']
            
            # Check role restriction
            if roles and g.role not in roles:
                return jsonify({'error': 'Forbidden: insufficient role'}), 403
            
            return f(*args, **kwargs)
        return decorated
    return decorator

# ---- Paper writing helpers ----
def get_papers_dir():
    d = os.path.join(USER_DATA_DIR, g.user, 'papers')
    os.makedirs(d, exist_ok=True)
    return d

def get_paper_path(paper_id):
    return os.path.join(get_papers_dir(), paper_id, 'meta.json')

def load_paper(paper_id):
    p = get_paper_path(paper_id)
    if not os.path.exists(p):
        return None
    with open(p, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_paper(paper_id, data):
    d = os.path.join(get_papers_dir(), paper_id)
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, 'meta.json')
    with open(p, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

@app.route('/')
def index():
    return send_from_directory('static', 'index.html')

def _download_headers(filename, mimetype=None):
    """Build RFC 5987 compatible download headers for non-ASCII filenames."""
    ascii_name = secure_filename(filename) or 'download'
    headers = {
        'Content-Disposition': f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"
    }
    if mimetype:
        headers['Content-Type'] = mimetype
    return headers


def _split_text_for_docmod_diff(text):
    """Mirror frontend DocMod sentence/paragraph diff units."""
    value = text or ''
    if not value:
        return []
    units = []
    current = []
    punctuation = set('。！？.!?；;')

    def push_current():
        nonlocal current
        compact = re.sub(r'[ \t]+', ' ', ''.join(current)).strip()
        if compact:
            units.append(compact)
        current = []

    for ch in value:
        if ch == '\r':
            continue
        if ch == '\n':
            push_current()
            units.append('↵')
            continue
        current.append(ch)
        if ch in punctuation:
            push_current()
    push_current()
    return [unit for idx, unit in enumerate(units)
            if unit != '↵' or (idx > 0 and idx < len(units) - 1 and units[idx - 1] != '↵')]


def _compute_docmod_diff(old_text, new_text):
    """Compute frontend-compatible DocMod diff actions using sentence/paragraph units."""
    old_units = _split_text_for_docmod_diff(old_text)
    new_units = _split_text_for_docmod_diff(new_text)
    if not old_units and old_text:
        old_units = (old_text or '').split('\n')
    if not new_units and new_text:
        new_units = (new_text or '').split('\n')
    if len(old_units) * len(new_units) > 50000000:
        old_units = (old_text or '').split('\n')
        new_units = (new_text or '').split('\n')

    m, n = len(old_units), len(new_units)
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(1, m + 1):
        prev = dp[i - 1]
        row = dp[i]
        old_unit = old_units[i - 1]
        for j in range(1, n + 1):
            if old_unit == new_units[j - 1]:
                row[j] = prev[j - 1] + 1
            else:
                row[j] = row[j - 1] if row[j - 1] >= prev[j] else prev[j]

    actions = []
    i, j = m, n
    while i > 0 or j > 0:
        if i > 0 and j > 0 and old_units[i - 1] == new_units[j - 1]:
            actions.append({'type': 'unchanged', 'oldIdx': i, 'newIdx': j, 'content': old_units[i - 1]})
            i -= 1
            j -= 1
        elif j > 0 and (i == 0 or dp[i][j - 1] >= dp[i - 1][j]):
            actions.append({'type': 'added', 'newIdx': j, 'content': new_units[j - 1]})
            j -= 1
        else:
            actions.append({'type': 'deleted', 'oldIdx': i, 'content': old_units[i - 1]})
            i -= 1
    actions.reverse()
    return actions


def _docmod_diff_to_markdown(diff_actions, title):
    lines = [f'# {title} - Diff 审阅版', '', '> 图例：`+` 表示新增内容，`-` 表示删除内容，空白行表示未变化内容。', '']
    for action in diff_actions:
        content = action['content']
        if content == '↵':
            lines.append('')
            continue
        if action['type'] == 'added':
            lines.append(f'> + {content}')
        elif action['type'] == 'deleted':
            lines.append(f'> - ~~{content}~~')
        else:
            lines.append(content)
    lines.append('')
    return '\n\n'.join(lines)


def _docmod_diff_to_html(diff_actions, title):
    rows = []
    for action in diff_actions:
        content = action['content']
        if content == '↵':
            rows.append('<div class="diff-break"></div>')
            continue
        escaped = html_lib.escape(content)
        typ = action['type']
        if typ == 'added':
            rows.append(f'<div class="diff-line diff-added"><span class="diff-mark">+</span><span>{escaped}</span></div>')
        elif typ == 'deleted':
            rows.append(f'<div class="diff-line diff-deleted"><span class="diff-mark">-</span><span>{escaped}</span></div>')
        else:
            rows.append(f'<div class="diff-line diff-unchanged"><span class="diff-mark"></span><span>{escaped}</span></div>')
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>
@page {{ margin: 18mm 14mm; }}
body {{ font-family: 'Noto Sans CJK SC', 'Microsoft YaHei', 'PingFang SC', 'DejaVu Sans', sans-serif; line-height: 1.65; color: #24292f; }}
h1 {{ color: #334155; font-size: 22px; margin-bottom: 8px; }}
.legend {{ color: #666; font-size: 13px; margin-bottom: 18px; }}
.diff-line {{ display: flex; gap: 8px; padding: 4px 8px; margin: 2px 0; border-radius: 4px; white-space: pre-wrap; word-break: break-word; }}
.diff-mark {{ width: 16px; flex: 0 0 16px; font-weight: 700; }}
.diff-added {{ background: #e6ffed; color: #116329; border-left: 3px solid #2da44e; }}
.diff-deleted {{ background: #ffebe9; color: #82071e; border-left: 3px solid #cf222e; text-decoration: line-through; }}
.diff-unchanged {{ background: #ffffff; color: #24292f; }}
.diff-break {{ height: 10px; }}
</style>
</head><body>
<h1>{html_lib.escape(title)} - Diff 审阅版</h1>
<div class="legend">绿色为新增，红色删除线为删除，白色为未变化内容。切分粒度：句号类标点 + 分段/换行。</div>
{''.join(rows)}
</body></html>"""

@app.route('/api/manual', methods=['GET'])
@require_auth()
def get_manual():
    """Return the full Markdown user manual for frontend rendering."""
    manual_path = os.path.join(CONFIG["base_dir"], "docs", "manual.md")
    if not os.path.exists(manual_path):
        return jsonify({'error': '使用手册不存在'}), 404
    with open(manual_path, 'r', encoding='utf-8') as f:
        content = f.read()
    return Response(content, mimetype='text/markdown; charset=utf-8')

@app.route('/api/register', methods=['POST'])
def register():
    data = request.get_json()
    username = (data.get('username') or '').strip()
    password = (data.get('password') or '').strip()
    security_code = (data.get('security_code') or '').strip()
    
    if not username or not password:
        return jsonify({'success': False, 'error': '用户名和密码不能为空'}), 400
    if security_code != CONFIG['auth_code']:
        return jsonify({'success': False, 'error': '安全码错误'}), 403
    if len(username) < 2 or len(username) > 32:
        return jsonify({'success': False, 'error': '用户名长度需在2-32之间'}), 400
    if len(password) < 4:
        return jsonify({'success': False, 'error': '密码长度不能少于4位'}), 400
    if not re.match(r'^[\w\u4e00-\u9fff]+$', username):
        return jsonify({'success': False, 'error': '用户名只能包含字母、数字、下划线和中文'}), 400
    
    users = load_users()
    if username in users:
        return jsonify({'success': False, 'error': '用户名已存在'}), 409
    
    users[username] = {
        'password_hash': hash_password(password),
        'role': 'user',
        'created_at': datetime.now().isoformat(),
        'display_name': username,
    }
    save_users(users)
    
    # Create user data directories
    os.makedirs(os.path.join(USER_DATA_DIR, username, 'chat_sessions'), exist_ok=True)
    os.makedirs(os.path.join(USER_DATA_DIR, username, 'agent_sessions'), exist_ok=True)
    os.makedirs(os.path.join(USER_DATA_DIR, username, 'papers'), exist_ok=True)
    
    token = generate_jwt(username, 'user')
    return jsonify({'success': True, 'token': token, 'username': username, 'role': 'user'})

@app.route('/api/login', methods=['POST'])
def login():
    data = request.get_json()
    username = (data.get('username') or '').strip()
    password = (data.get('password') or '').strip()
    if not username or not password:
        return jsonify({'success': False, 'error': '请输入用户名和密码'}), 400
    users = load_users()
    user = users.get(username)
    if not user or not check_password(password, user['password_hash']):
        return jsonify({'success': False, 'error': '用户名或密码错误'}), 403
    token = generate_jwt(username, user['role'])
    return jsonify({'success': True, 'token': token, 'username': username, 'role': user['role']})

@app.route('/api/knowledge-bases', methods=['GET'])
@require_auth()
def list_knowledge_bases():
    kb_dir = os.path.join(CONFIG['base_dir'], 'knowledge_bases')
    kbs = []
    if os.path.exists(kb_dir):
        for name in os.listdir(kb_dir):
            p = os.path.join(kb_dir, name)
            if os.path.isdir(p):
                kbs.append(get_kb_info(p, name))
    return jsonify({'knowledge_bases': kbs})

@app.route('/api/query', methods=['POST'])
@require_auth()
def query():
    """[DEPRECATED] 普通查询模式 — 前端已改用 Agent 模式。保留作为兼容。"""
    data = request.get_json()
    query_text = data.get('query', '')
    kb_name = data.get('kb', os.getenv('RAG_KB_NAME', 'papers'))
    top_k = data.get('top_k', 8)
    if not query_text.strip():
        return jsonify({'error': 'Empty query'}), 400
    
    # Query rewriting: convert questions to keywords
    original_query = query_text
    # English question words
    if any(w in query_text.lower() for w in ["what", "how", "why", "which", "does", "is", "are"]):
        query_text = re.sub(r'\b(what|how|why|which|when|where|who|does|do|did|is|are|was|were|can|could|should|would)\b', '', query_text, flags=re.IGNORECASE)
        query_text = re.sub(r'\s+', ' ', query_text).strip()
        query_text = re.sub(r'[?]', '', query_text)
    # Chinese question words: remove common patterns
    query_text = re.sub(r'(是谁|是什么|为什么|怎么样|如何|哪些|哪个|多少|有没有|吗|呢|啊|的)', '', query_text)
    query_text = re.sub(r'\s+', ' ', query_text).strip()

    kb_path = os.path.join(CONFIG['base_dir'], 'knowledge_bases', kb_name)
    if not os.path.exists(kb_path):
        return jsonify({'error': f'KB {kb_name} not found'}), 404

    try:
        resp = requests.post(f"{CONFIG['ollama_url']}/api/embed",
            json={'model': CONFIG['embedding_model'], 'input': query_text}, timeout=120)
        query_emb = resp.json()['embeddings'][0]
    except Exception as e:
        return jsonify({'error': f'Embedding failed: {e}'}), 500

    try:
        results = hybrid_search(kb_path, query_text, query_emb, top_k)
    except Exception as e:
        return jsonify({'error': f'Search failed: {e}'}), 500

    context = '\n\n'.join([r['text'] for r in results])
    prompt = f"""根据以下参考资料回答问题。请仔细阅读所有资料，从中提取相关信息直接回答。如果参考资料中没有相关信息，请说明。

参考资料：
{context}

问题：{original_query}

请用简体中文回答，直接给出答案，不要重复问题："""

    try:
        resp = requests.post(f"{CONFIG['ollama_url']}/api/chat",
            json={'model': CONFIG['chat_model'], 'messages': [{'role': 'user', 'content': prompt}], 'stream': False}, timeout=120)
        answer = resp.json()['message']['content']
    except Exception as e:
        answer = f'LLM failed: {e}\n\nRelevant docs:\n' + '\n---\n'.join([r['text'][:200] for r in results])

    return jsonify({
        'answer': answer,
        'sources': [{'text': r['text'][:200], 'score': r['score']} for r in results],
        'kb': kb_name, 'timestamp': datetime.now().isoformat()
    })


# ========== Chat API (multi-turn with RAG context) ==========

@app.route('/api/chat', methods=['POST'])
@require_auth()
def chat():
    """Multi-turn RAG chat. Accepts messages history, returns streaming response.
    Body: {kb, messages: [{role,content}], model?, base_url?, api_key?}"""
    data = request.get_json()
    kb_name = data.get('kb', os.getenv('RAG_KB_NAME', 'papers'))
    messages = data.get('messages', [])
    top_k = data.get('top_k', 8)

    if not messages:
        return jsonify({'error': 'Empty messages'}), 400

    # Extract last user message for retrieval
    user_messages = [m.get('content', '').strip() for m in messages if m.get('role') == 'user' and m.get('content', '').strip()]
    last_user_msg = user_messages[-1] if user_messages else ''
    if not last_user_msg.strip():
        return jsonify({'error': 'No user message'}), 400

    # Retrieve relevant context
    kb_path = os.path.join(CONFIG['base_dir'], 'knowledge_bases', kb_name)
    if not os.path.exists(kb_path):
        return jsonify({'error': f'KB {kb_name} not found'}), 404

    # ==== Dual-path retrieval: current question + historical topic ====
    # Path A: current question (with stop-word cleanup)
    query_a = last_user_msg
    query_a = re.sub(r'(是谁|是什么|为什么|怎么样|如何|哪些|哪个|多少|有没有|吗|呢|啊)', '', query_a)
    query_a = re.sub(r'\b(what|how|why|which|does|is|are|do|did|can|could)\b', '', query_a, flags=re.IGNORECASE)
    query_a = re.sub(r'\s+', ' ', query_a).strip()

    # Path B: historical topic — extract core entities & keywords from all prior turns
    # Strategy: extract English technical terms + Chinese noun phrases from all messages,
    # then deduplicate into a concise topic string for embedding.
    topic_parts = []
    seen_terms = set()
    for msg in messages:  # scan ALL messages to capture topic keywords
        content = msg.get('content', '')
        # English terms (2+ chars, likely technical keywords)
        eng_terms = re.findall(r'(?<![A-Za-z0-9_\-])[A-Za-z][A-Za-z0-9_\-]{2,}(?![A-Za-z0-9_\-])', content)
        for t in eng_terms:
            tl = t.lower()
            if tl not in seen_terms and tl not in ('the', 'and', 'for', 'are', 'but', 'not', 'you',
                'all', 'can', 'had', 'her', 'was', 'one', 'our', 'out', 'has', 'have', 'been',
                'from', 'this', 'that', 'with', 'they', 'will', 'what', 'when', 'which', 'their',
                'there', 'would', 'about', 'could', 'other', 'into', 'more', 'its', 'than'):
                seen_terms.add(tl)
                topic_parts.append(t)
        # Chinese keywords: extract 2-6 char CJK runs (skip single chars and particles)
        cjk_runs = re.findall(r'[\u4e00-\u9fff\u3400-\u4dbf]{2,6}', content)
        stopwords = {'的是', '在了', '不是', '一个', '我们', '他们', '什么', '怎么', '为什么',
                     '如果', '因为', '所以', '但是', '而且', '或者', '虽然', '可以', '已经',
                     '就是', '还是', '只是', '也是', '这个', '那个', '这些', '那些'}
        for p in cjk_runs:
            if p not in seen_terms and p not in stopwords:
                seen_terms.add(p)
                topic_parts.append(p)

    query_b = ' '.join(topic_parts[:20])  # cap at 20 terms to avoid dilution

    # Decide: single-path vs dual-path
    is_first_turn = len(user_messages) <= 1
    has_topic = len(query_b.strip()) >= 3  # at least some substance
    use_dual = (not is_first_turn) and has_topic

    retrieval_queries = [query_a]
    if use_dual:
        retrieval_queries.append(query_b)

    # Embed all queries in one batch
    try:
        embed_resp = requests.post(f"{CONFIG['ollama_url']}/api/embed",
            json={'model': CONFIG['embedding_model'], 'input': retrieval_queries}, timeout=60)
        all_embs = embed_resp.json()['embeddings']
    except Exception as e:
        return jsonify({'error': f'Embedding failed: {e}'}), 500

    # Run hybrid_search for each query path
    all_path_results = []
    for qi, q_text in enumerate(retrieval_queries):
        try:
            path_results = hybrid_search(kb_path, q_text, all_embs[qi], top_k=top_k)
            all_path_results.append(path_results)
        except Exception as e:
            # If one path fails, just skip it
            pass

    if not all_path_results:
        return jsonify({'error': 'Search failed for all paths'}), 500

    # Fuse results using Reciprocal Rank Fusion (RRF)
    # RRF score = sum(1 / (k + rank)) for each path where doc appears
    # k=60 is the standard parameter
    rrf_k = 60
    fused_scores = {}  # key: text[:100] -> {text, source, rrf_score, best_score}
    for path_idx, path_results in enumerate(all_path_results):
        for rank, r in enumerate(path_results):
            dedup_key = r['text'][:100].strip()
            rrf_contribution = 1.0 / (rrf_k + rank + 1)
            if dedup_key in fused_scores:
                fused_scores[dedup_key]['rrf_score'] += rrf_contribution
                # Keep the best raw score across paths
                if r['score'] > fused_scores[dedup_key]['best_score']:
                    fused_scores[dedup_key]['best_score'] = r['score']
                    fused_scores[dedup_key]['text'] = r['text']
                    fused_scores[dedup_key]['source'] = r.get('source', '')
            else:
                fused_scores[dedup_key] = {
                    'text': r['text'],
                    'source': r.get('source', ''),
                    'rrf_score': rrf_contribution,
                    'best_score': r['score'],
                }

    # Sort by RRF score, use best_score as tiebreaker
    results = sorted(fused_scores.values(),
                     key=lambda x: (x['rrf_score'], x['best_score']),
                     reverse=True)[:top_k]

    # Normalize: use best_score as final display score, capped at 1.0
    for r in results:
        r['score'] = min(r['best_score'], 1.0)

    # Build display retrieval info
    retrieval_display = query_a
    if use_dual:
        retrieval_display += f' [+历史主题: {query_b[:50]}]'

    context = '\n\n'.join([f"[文档{i+1}] {r['text']}" for i, r in enumerate(results)])

    # Determine model config: local or custom
    custom_model = data.get('model', '').strip()
    custom_base_url = data.get('base_url', '').strip()
    custom_api_key = data.get('api_key', '').strip()

    use_custom = bool(custom_model and custom_base_url)

    # Build system prompt with context
    system_prompt = f"""你是一个专业的学术论文研究助手。根据以下检索到的参考资料回答用户的问题。

要求：
1. 基于参考资料回答，引用来源时注明文档编号
2. 如果参考资料不足，坦诚说明并给出你的理解
3. 使用简体中文回答
4. 回答要准确、专业、有条理

检索到的参考资料：
{context}"""

    # Build messages for LLM
    chat_messages = [{'role': 'system', 'content': system_prompt}]
    # Only include last 10 messages for context window management
    for m in messages[-10:]:
        role = m.get('role', 'user')
        if role in ('user', 'assistant'):
            chat_messages.append({'role': role, 'content': m.get('content', '')})

    if use_custom:
        # Call custom OpenAI-compatible API
        try:
            headers = {'Content-Type': 'application/json'}
            if custom_api_key:
                headers['Authorization'] = f'Bearer {custom_api_key}'
            # Ensure base_url ends correctly
            api_url = custom_base_url.rstrip('/')
            if not api_url.endswith('/chat/completions'):
                # DeepSeek uses /chat/completions (no /v1), most others use /v1/chat/completions
                if 'deepseek' in api_url.lower():
                    api_url += '/chat/completions'
                else:
                    api_url += '/v1/chat/completions'
            # Build payload - support DeepSeek thinking mode
            payload = {'model': custom_model, 'messages': chat_messages, 'stream': False}
            if 'deepseek' in (custom_base_url + custom_model).lower():
                payload['thinking'] = {'type': 'enabled'}
                payload['reasoning_effort'] = 'high'
            api_resp = requests.post(api_url,
                headers=headers,
                json=payload,
                timeout=120)
            api_resp.raise_for_status()
            resp_json = api_resp.json()
            msg = resp_json['choices'][0]['message']
            answer = msg.get('content', '') or ''
            # DeepSeek thinking mode: reasoning_content is separate
            reasoning = msg.get('reasoning_content', '')
            if reasoning and not answer:
                answer = reasoning
        except Exception as e:
            return jsonify({'error': f'Custom model call failed: {e}'}), 500
    else:
        # Use local Ollama
        try:
            resp = requests.post(f"{CONFIG['ollama_url']}/api/chat",
                json={'model': CONFIG['chat_model'], 'messages': chat_messages, 'stream': False},
                timeout=180)
            answer = resp.json()['message']['content']
        except Exception as e:
            return jsonify({'error': f'Local model failed: {e}'}), 500

    return jsonify({
        'answer': answer,
        'sources': [{'text': r['text'][:200], 'score': round(r['score'], 4), 'source': r.get('source', '')} for r in results],
        'kb': kb_name,
        'model': custom_model if use_custom else CONFIG['chat_model'],
        'retrieval_query': retrieval_display,
        'timestamp': datetime.now().isoformat()
    })


# ========== Chat Session Persistence ==========

def _sanitize_session_name(name):
    return re.sub(r'[^\w\-\u4e00-\u9fff]+', '_', name).strip('_')[:120]


def _user_chat_dir():
    """Return user-specific chat sessions directory."""
    username = getattr(g, 'user', 'admin')
    d = os.path.join(USER_DATA_DIR, username, 'chat_sessions')
    os.makedirs(d, exist_ok=True)
    return d

def _user_agent_dir():
    """Return user-specific agent sessions directory."""
    username = getattr(g, 'user', 'admin')
    d = os.path.join(USER_DATA_DIR, username, 'agent_sessions')
    os.makedirs(d, exist_ok=True)
    return d

def _session_path(session_id):
    return os.path.join(_user_chat_dir(), f'{session_id}.json')


def _generate_session_title(first_message):
    prefix = (first_message or '新对话').strip().replace('\n', ' ')
    prefix = prefix[:12]
    date_str = datetime.now().strftime('%Y-%m-%d')
    return f"{prefix}_{date_str}"


@app.route('/api/chat-sessions', methods=['GET'])
@require_auth()
def list_chat_sessions():
    sessions = []
    session_dir = _user_chat_dir()
    if os.path.exists(session_dir):
        for fn in os.listdir(session_dir):
            if fn.endswith('.json'):
                path = os.path.join(session_dir, fn)
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    sessions.append({
                        'id': data.get('id', fn[:-5]),
                        'title': data.get('title', fn[:-5]),
                        'kb': data.get('kb', os.getenv('RAG_KB_NAME', 'papers')),
                        'message_count': len(data.get('messages', [])),
                        'updated_at': data.get('updated_at', ''),
                        'created_at': data.get('created_at', ''),
                    })
                except:
                    pass
    sessions.sort(key=lambda x: x.get('updated_at', ''), reverse=True)
    return jsonify({'sessions': sessions})


@app.route('/api/chat-sessions/<session_id>', methods=['GET'])
@require_auth()
def get_chat_session(session_id):
    path = _session_path(session_id)
    if not os.path.exists(path):
        return jsonify({'error': 'Session not found'}), 404
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return jsonify(data)


@app.route('/api/chat-sessions', methods=['POST'])
@require_auth()
def save_chat_session():
    data = request.get_json()
    session_id = (data.get('id') or '').strip() or str(uuid.uuid4())
    messages = data.get('messages', [])
    kb = data.get('kb') or os.getenv('RAG_KB_NAME', 'papers')
    title = (data.get('title') or '').strip()
    if title in ('新对话', 'new_chat', 'untitled'):
        title = ''

    existing = None
    path = _session_path(session_id)
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                existing = json.load(f)
        except:
            existing = None

    if not title:
        first_user = ''
        for m in messages:
            if m.get('role') == 'user' and m.get('content', '').strip():
                first_user = m['content']
                break
        title = _generate_session_title(first_user)

    record = {
        'id': session_id,
        'title': _sanitize_session_name(title),
        'kb': kb,
        'messages': messages,
        'created_at': (existing or {}).get('created_at', datetime.now().isoformat()),
        'updated_at': datetime.now().isoformat(),
    }
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(record, f, ensure_ascii=False, indent=2)
    return jsonify({'success': True, 'id': session_id, 'title': record['title']})


@app.route('/api/chat-sessions/<session_id>', methods=['DELETE'])
@require_auth()
def delete_chat_session(session_id):
    path = _session_path(session_id)
    if os.path.exists(path):
        os.remove(path)
        return jsonify({'success': True})
    return jsonify({'error': 'Session not found'}), 404

@app.route('/api/upload', methods=['POST'])
@require_auth(roles=['admin'])
def upload_document():
    kb_name = request.form.get('kb', os.getenv('RAG_KB_NAME', 'papers'))
    if 'file' not in request.files:
        return jsonify({'error': 'No file'}), 400
    file = request.files['file']
    ext = file.filename.rsplit('.', 1)[-1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        return jsonify({'error': f'Unsupported: {ext}'}), 400
    upload_dir = os.path.join(CONFIG['upload_dir'], kb_name)
    os.makedirs(upload_dir, exist_ok=True)
    filepath = os.path.join(upload_dir, secure_filename(file.filename))
    file.save(filepath)
    text = extract_text(filepath, ext)
    if not text or len(text.strip()) < 20:
        return jsonify({
            'success': False,
            'error': f'PDF 解析失败或文本内容为空（提取到 {len(text.strip())} 个字符）。文件可能为扫描件、图片 PDF 或加密文档。',
            'segments': 0,
            'filename': file.filename
        })
    chunks = split_text(text)
    if not chunks:
        return jsonify({
            'success': False,
            'error': f'文档分块失败：提取到 {len(text)} 个字符，但无法拆分为有效段落。请检查文档格式。',
            'segments': 0,
            'filename': file.filename
        })
    # Generate standard filename from extracted text
    new_filename = generate_standard_filename(text, CONFIG['base_dir'])
    ref_dir = os.path.join(CONFIG['base_dir'], 'reference')
    os.makedirs(ref_dir, exist_ok=True)
    ref_path = os.path.join(ref_dir, new_filename)
    shutil.copy2(filepath, ref_path)

    kb_path = os.path.join(CONFIG['base_dir'], 'knowledge_bases', kb_name)
    os.makedirs(kb_path, exist_ok=True)
    emb_file = os.path.join(kb_path, 'embeddings.json')
    seg_file = os.path.join(kb_path, 'segments.json')

    def _do_embed():
        embs = load_jsonl(emb_file)
        segs = load_jsonl(seg_file)
        count = 0
        batch_size = 5
        for i in range(0, len(chunks), batch_size):
            batch = chunks[i:i+batch_size]
            try:
                r = requests.post(f"{CONFIG['ollama_url']}/api/embed",
                    json={'model': CONFIG['embedding_model'], 'input': batch}, timeout=300)
                batch_embs = r.json()['embeddings']
                for j, (chunk, emb) in enumerate(zip(batch, batch_embs)):
                    embs.append(emb)
                    segs.append({'text': chunk, 'source': new_filename})
                    count += 1
            except Exception as e:
                logger.warning(f"batch embed failed at chunk {i}: {e}")
        save_jsonl(emb_file, embs)
        save_jsonl(seg_file, segs)
        logger.info(f"Upload complete: {new_filename} -> {count} segments")

    import threading
    t = threading.Thread(target=_do_embed, daemon=True)
    t.start()

    return jsonify({'success': True, 'status': 'processing', 'chunks': len(chunks),
                     'filename': file.filename, 'new_filename': new_filename,
                     'message': f'文件已提交，正在后台处理 {len(chunks)} 个段落'})

@app.route('/api/batch-upload', methods=['POST'])
@require_auth(roles=['admin'])
def batch_upload():
    """Batch upload: accepts multiple files or a zip archive.
    Returns streaming JSON progress (one JSON object per file processed)."""
    kb_name = request.form.get('kb', os.getenv('RAG_KB_NAME', 'papers'))
    files = request.files.getlist('files')
    if not files or all(f.filename == '' for f in files):
        return jsonify({'error': 'No files provided'}), 400

    kb_path = os.path.join(CONFIG['base_dir'], 'knowledge_bases', kb_name)
    os.makedirs(kb_path, exist_ok=True)
    upload_dir = os.path.join(CONFIG['upload_dir'], kb_name)
    os.makedirs(upload_dir, exist_ok=True)

    emb_file = os.path.join(kb_path, 'embeddings.json')
    seg_file = os.path.join(kb_path, 'segments.json')

    # Collect all files to process (flatten zip contents)
    file_list = []  # [(filename, filepath, ext)]
    import tempfile, zipfile

    for f in files:
        ext = f.filename.rsplit('.', 1)[-1].lower() if '.' in f.filename else ''
        if ext == 'zip':
            tmp_zip = os.path.join(upload_dir, secure_filename(f.filename))
            f.save(tmp_zip)
            try:
                with zipfile.ZipFile(tmp_zip, 'r') as zf:
                    for name in zf.namelist():
                        if name.startswith('__MACOSX') or name.startswith('.'):
                            continue
                        fext = name.rsplit('.', 1)[-1].lower() if '.' in name else ''
                        if fext in ALLOWED_EXTENSIONS:
                            extracted = os.path.join(upload_dir, secure_filename(os.path.basename(name)))
                            with zf.open(name) as src, open(extracted, 'wb') as dst:
                                dst.write(src.read())
                            file_list.append((os.path.basename(name), extracted, fext))
            except zipfile.BadZipFile:
                pass
            finally:
                os.remove(tmp_zip)
        elif ext in ALLOWED_EXTENSIONS:
            filepath = os.path.join(upload_dir, secure_filename(f.filename))
            f.save(filepath)
            file_list.append((f.filename, filepath, ext))

    if not file_list:
        return jsonify({'error': '没有可处理的文件（支持 PDF/TXT/MD/JSON/CSV/ZIP）'}), 400

    total_files = len(file_list)

    def generate():
        results = []
        total_segments = 0
        total_failed = 0

        for idx, (fname, fpath, fext) in enumerate(file_list):
            result = {'filename': fname, 'index': idx + 1, 'total_files': total_files}
            try:
                text = extract_text(fpath, fext)
                if not text or len(text.strip()) < 20:
                    result['status'] = 'skipped'
                    result['reason'] = f'文本为空或过短（{len(text.strip())}字符）'
                    total_failed += 1
                    results.append(result)
                    yield json.dumps(result) + '\n'
                    continue
                chunks = split_text(text)
                if not chunks:
                    result['status'] = 'skipped'
                    result['reason'] = '分块失败'
                    total_failed += 1
                    results.append(result)
                    yield json.dumps(result) + '\n'
                    continue

                # Generate standard filename from extracted text
                new_filename = generate_standard_filename(text, CONFIG['base_dir'])
                ref_dir = os.path.join(CONFIG['base_dir'], 'reference')
                os.makedirs(ref_dir, exist_ok=True)
                ref_path = os.path.join(ref_dir, new_filename)
                shutil.copy2(fpath, ref_path)

                embs = load_jsonl(emb_file)
                segs = load_jsonl(seg_file)
                count = 0
                chunk_total = len(chunks)
                batch_size = 5
                for ci in range(0, chunk_total, batch_size):
                    batch = chunks[ci:ci+batch_size]
                    try:
                        r = requests.post(f"{CONFIG['ollama_url']}/api/embed",
                            json={'model': CONFIG['embedding_model'], 'input': batch}, timeout=180)
                        batch_embs = r.json()['embeddings']
                        for j, (chunk, emb) in enumerate(zip(batch, batch_embs)):
                            embs.append(emb)
                            segs.append({'text': chunk, 'source': new_filename})
                            count += 1
                    except Exception as e:
                        logger.warning(f"batch embed failed at chunk {ci}: {e}")
                    if count > 0:
                        progress = json.dumps({'file': fname, 'processed': count,
                            'total_chunks': chunk_total, 'percent': round(count / chunk_total * 100, 1)}) + '\n'
                        yield progress
                save_jsonl(emb_file, embs)
                save_jsonl(seg_file, segs)
                result['status'] = 'ok'
                result['segments'] = count
                result['new_filename'] = new_filename
                total_segments += count
            except Exception as e:
                result['status'] = 'error'
                result['reason'] = str(e)
                total_failed += 1
            results.append(result)
            yield json.dumps(result) + '\n'

        final = json.dumps({
            'success': True,
            'total_files': total_files,
            'total_segments': total_segments,
            'total_failed': total_failed,
            'results': results
        }) + '\n'
        yield final

    return Response(generate(), mimetype='text/plain')

@app.route('/api/create', methods=['POST'])
@require_auth(roles=['admin'])
def create_knowledge_base():
    data = request.get_json()
    name = data.get('name', '').strip()
    desc = data.get('desc', '')
    model = data.get('model', 'bge-m3')
    if not name:
        return jsonify({'error': 'Empty name'}), 400
    if not all(c.isalnum() or c in '_-' for c in name):
        return jsonify({'error': 'Invalid name'}), 400
    kb_path = os.path.join(CONFIG['base_dir'], 'knowledge_bases', name)
    if os.path.exists(kb_path):
        return jsonify({'error': 'Already exists'}), 409
    os.makedirs(kb_path)
    meta = {'name': name, 'description': desc, 'model': model, 'created': datetime.now().isoformat(), 'segments': 0}
    with open(os.path.join(kb_path, 'metadata.json'), 'w') as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    open(os.path.join(kb_path, 'embeddings.json'), 'w').close()
    open(os.path.join(kb_path, 'segments.json'), 'w').close()
    return jsonify({'success': True, 'kb': meta})

@app.route('/api/delete-kb', methods=['POST'])
@require_auth(roles=['admin'])
def delete_knowledge_base():
    name = request.get_json().get('name', '')
    p = os.path.join(CONFIG['base_dir'], 'knowledge_bases', name)
    if os.path.exists(p):
        shutil.rmtree(p)
        return jsonify({'success': True})
    return jsonify({'error': 'Not found'}), 404

@app.route('/api/rename-kb', methods=['POST'])
@require_auth(roles=['admin'])
def rename_knowledge_base():
    data = request.get_json()
    old_name = data.get('old_name', '').strip()
    new_name = data.get('new_name', '').strip()
    if not old_name or not new_name:
        return jsonify({'error': 'Missing name'}), 400
    if not all(c.isalnum() or c in '_-' for c in new_name):
        return jsonify({'error': 'Invalid new name (only alphanumeric, underscore, hyphen)'}), 400
    kb_dir = os.path.join(CONFIG['base_dir'], 'knowledge_bases')
    old_path = os.path.join(kb_dir, old_name)
    new_path = os.path.join(kb_dir, new_name)
    if not os.path.exists(old_path):
        return jsonify({'error': 'Source KB not found'}), 404
    if os.path.exists(new_path):
        return jsonify({'error': 'Target name already exists'}), 409
    os.rename(old_path, new_path)
    # Update metadata.json
    meta_file = os.path.join(new_path, 'metadata.json')
    if os.path.exists(meta_file):
        with open(meta_file, 'r', encoding='utf-8') as f:
            meta = json.load(f)
        meta['name'] = new_name
        with open(meta_file, 'w', encoding='utf-8') as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
    return jsonify({'success': True, 'old_name': old_name, 'new_name': new_name})

@app.route('/api/kb-documents', methods=['GET'])
@require_auth()
def kb_documents():
    kb_name = request.args.get('kb', '')
    if not kb_name:
        return jsonify({'error': 'Missing kb parameter'}), 400
    kb_path = os.path.join(CONFIG['base_dir'], 'knowledge_bases', kb_name)
    if not os.path.exists(kb_path):
        return jsonify({'error': 'KB not found'}), 404
    seg_file = os.path.join(kb_path, 'segments.json')
    doc_map = {}  # source -> segment count
    total_segments = 0
    if os.path.exists(seg_file):
        with open(seg_file, 'r', encoding='utf-8', errors='replace') as f:
            for line in f:
                if line.strip():
                    try:
                        seg = json.loads(line)
                        src = seg.get('source', '未知来源')
                        doc_map[src] = doc_map.get(src, 0) + 1
                        total_segments += 1
                    except:
                        pass
    documents = []
    ref_dir = os.path.join(CONFIG['base_dir'], 'reference')
    for src, count in sorted(doc_map.items(), key=lambda x: -x[1]):
        documents.append({
            'source': src,
            'segments': count,
            'has_summary': False,
            'pdf_exists': os.path.exists(os.path.join(ref_dir, src))
        })

    # Check cache status
    cache_path = os.path.join(kb_path, 'doc_details_cache.json')
    cache = {}
    if os.path.exists(cache_path):
        try:
            with open(cache_path, 'r', encoding='utf-8') as f:
                cache = json.load(f)
            for doc in documents:
                key = f"{kb_name}::{doc['source']}"
                if key in cache:
                    if (cache[key].get('summary_zh') or '').strip():
                        doc['has_summary'] = True
                    # Add keywords from cache
                    kws = cache[key].get('keywords', [])
                    doc['keywords'] = kws if isinstance(kws, list) else []
                else:
                    doc['keywords'] = []
        except:
            pass
    else:
        for doc in documents:
            doc['keywords'] = []

    return jsonify({
        'kb': kb_name,
        'total_documents': len(documents),
        'total_segments': total_segments,
        'documents': documents
    })

@app.route('/api/tags', methods=['GET'])
@require_auth()
def get_tags():
    """Get all tags with counts for a knowledge base."""
    kb_name = request.args.get('kb', '')
    if not kb_name:
        return jsonify({'error': 'Missing kb parameter'}), 400
    kb_path = os.path.join(CONFIG['base_dir'], 'knowledge_bases', kb_name)
    if not os.path.exists(kb_path):
        return jsonify({'error': 'KB not found'}), 404

    cache_path = os.path.join(kb_path, 'doc_details_cache.json')
    tag_counts = {}
    if os.path.exists(cache_path):
        try:
            with open(cache_path, 'r', encoding='utf-8') as f:
                cache = json.load(f)
            for key, detail in cache.items():
                kws = detail.get('keywords', [])
                if isinstance(kws, list):
                    for kw in kws:
                        kw = kw.strip()
                        if kw:
                            tag_counts[kw] = tag_counts.get(kw, 0) + 1
        except:
            pass

    tags = [{'name': name, 'count': count} for name, count in sorted(tag_counts.items(), key=lambda x: -x[1])]
    return jsonify({'tags': tags})


@app.route('/api/tags', methods=['PUT'])
@require_auth()
def update_tags():
    """Update keywords/tags for a document."""
    data = request.get_json()
    kb_name = data.get('kb', '')
    source = data.get('source', '')
    keywords = data.get('keywords', [])

    if not kb_name or not source:
        return jsonify({'error': 'Missing kb or source parameter'}), 400
    if not isinstance(keywords, list):
        return jsonify({'error': 'keywords must be a list'}), 400

    kb_path = os.path.join(CONFIG['base_dir'], 'knowledge_bases', kb_name)
    if not os.path.exists(kb_path):
        return jsonify({'error': 'KB not found'}), 404

    cache_path = os.path.join(kb_path, 'doc_details_cache.json')
    cache = {}
    if os.path.exists(cache_path):
        try:
            with open(cache_path, 'r', encoding='utf-8') as f:
                cache = json.load(f)
        except:
            pass

    cache_key = f"{kb_name}::{source}"
    if cache_key not in cache:
        cache[cache_key] = {'source': source}

    # Clean keywords: strip whitespace, remove empties, deduplicate
    cleaned = list(dict.fromkeys(kw.strip() for kw in keywords if isinstance(kw, str) and kw.strip()))
    cache[cache_key]['keywords'] = cleaned

    with open(cache_path, 'w', encoding='utf-8') as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)

    return jsonify({'success': True, 'keywords': cleaned})


@app.route('/api/kb-document-detail', methods=['GET'])
@require_auth()
def kb_document_detail():
    kb_name = request.args.get('kb', '')
    source = request.args.get('source', '')
    if not kb_name or not source:
        return jsonify({'error': 'Missing kb or source parameter'}), 400
    kb_path = os.path.join(CONFIG['base_dir'], 'knowledge_bases', kb_name)
    if not os.path.exists(kb_path):
        return jsonify({'error': 'KB not found'}), 404

    # ---------- Check cache first ----------
    cache_path = os.path.join(kb_path, 'doc_details_cache.json')
    cache_key = f"{kb_name}::{source}"
    if os.path.exists(cache_path):
        try:
            with open(cache_path, 'r', encoding='utf-8') as f:
                cache = json.load(f)
            if cache_key in cache:
                cached = cache[cache_key].copy()
                # 如果旧缓存没有中文摘要，则视为缓存不完整，自动重新生成
                if (cached.get('summary_zh') or '').strip():
                    cached['_cached'] = True
                    return jsonify({'success': True, 'detail': cached})
        except Exception:
            pass  # cache corrupt → regenerate

    # ---------- Cache miss / incomplete cache → call LLM ----------
    seg_file = os.path.join(kb_path, 'segments.json')
    # Collect all segments for this source
    doc_segments = []
    if os.path.exists(seg_file):
        with open(seg_file, 'r', encoding='utf-8', errors='replace') as f:
            for line in f:
                if line.strip():
                    try:
                        seg = json.loads(line)
                        if seg.get('source', '') == source:
                            doc_segments.append(seg.get('text', ''))
                    except:
                        pass
    if not doc_segments:
        return jsonify({'error': 'No segments found for this document'}), 404

    # Use first segments (title/author/abstract are usually at the beginning)
    # Cap at ~6000 chars to avoid overwhelming the LLM
    full_text = '\n\n'.join(doc_segments)[:6000]

    prompt = f"""分析以下从 PDF 提取的文本，提取信息并用 JSON 返回。只返回 JSON，不要其他内容。

文本：
{full_text}

返回格式：
{{"title":"标题","title_zh":"中文标题","authors":["作者1"],"affiliations":["单位1"],"venue":"会议或期刊名","year":"年份","doc_type":"paper或survey或other","summary_zh":"200字中文摘要","keywords":["关键词1"]}}"""

    try:
        raw = call_llm([
            {'role': 'system', 'content': '你是一个文档分析助手。用户会给你从PDF提取的文本，你需要提取标题、作者、单位、会议、年份、摘要、关键词等信息，用JSON格式返回。只返回JSON，不要任何其他文字。'},
            {'role': 'user', 'content': prompt}
        ], timeout=60)
        # Try to parse JSON from response (strip markdown code blocks if present)
        raw = re.sub(r'^```(?:json)?\s*', '', raw)
        raw = re.sub(r'\s*```$', '', raw)
        # Find first { and last } to extract JSON
        start = raw.find('{')
        end = raw.rfind('}')
        if start >= 0 and end > start:
            raw = raw[start:end+1]
            detail = json.loads(raw)
        else:
            # Fallback: parse markdown-style "**Key:** Value" format
            detail = parse_doc_detail_md(raw)
    except json.JSONDecodeError:
        # Fallback: return raw text if JSON parsing fails
        detail = {
            'title': source.replace('.pdf', '').replace('.txt', ''),
            'title_zh': '',
            'authors': [],
            'affiliations': [],
            'venue': '',
            'year': '',
            'doc_type': 'other',
            'summary_zh': raw[:500] if 'raw' in dir() else '摘要生成失败',
            'keywords': [],
            '_raw': raw if 'raw' in dir() else ''
        }
    except Exception as e:
        detail = {
            'title': source.replace('.pdf', '').replace('.txt', ''),
            'title_zh': '',
            'authors': [], 'affiliations': [], 'venue': '', 'year': '',
            'doc_type': 'other',
            'summary_zh': f'摘要生成失败: {e}',
            'keywords': []
        }

    detail['source'] = source
    detail['segment_count'] = len(doc_segments)

    # ---------- Fallback summary generation ----------
    if not (detail.get('summary_zh') or '').strip():
        try:
            summary_prompt = f"""请根据以下论文/文档内容，生成一段简体中文摘要（120-220字）。
要求：
1. 只输出摘要正文，不要标题，不要项目符号，不要解释。
2. 优先概括研究目标、核心方法、实验/效果与主要结论。
3. 如果文本信息不足，就尽量基于已有内容概括，不要留空。

文本：
{full_text[:4000]}
"""
            sresp_text = call_llm([
                {'role': 'system', 'content': '你是一个学术论文摘要助手，擅长把论文内容概括为简洁准确的中文摘要。'},
                {'role': 'user', 'content': summary_prompt}
            ], timeout=60)
            summary_text = sresp_text.strip()
            summary_text = re.sub(r'^```(?:text)?\s*', '', summary_text)
            summary_text = re.sub(r'\s*```$', '', summary_text).strip()
            detail['summary_zh'] = summary_text
        except Exception:
            detail['summary_zh'] = detail.get('summary_zh', '') or ''

    # ---------- Save to cache ----------
    try:
        if os.path.exists(cache_path):
            with open(cache_path, 'r', encoding='utf-8') as f:
                cache = json.load(f)
        else:
            cache = {}
        cache[cache_key] = detail
        with open(cache_path, 'w', encoding='utf-8') as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception:
        pass  # cache write failure is non-fatal

    detail['_cached'] = False
    return jsonify({'success': True, 'detail': detail})


# ========== Prefetch (background summary generation) ==========

# Global state for prefetch progress
_prefetch_state = {'running': False, 'progress': 0, 'total': 0, 'done': 0, 'failed': 0, 'results': [], 'error': None}

def _do_prefetch(kb_name):
    """Background thread: iterate all uncached docs, extract details, save to cache."""
    global _prefetch_state
    import threading

    kb_path = os.path.join(CONFIG['base_dir'], 'knowledge_bases', kb_name)
    seg_file = os.path.join(kb_path, 'segments.json')
    cache_path = os.path.join(kb_path, 'doc_details_cache.json')

    if not os.path.exists(seg_file):
        _prefetch_state['error'] = 'segments.json not found'
        _prefetch_state['running'] = False
        return

    # Collect all unique sources and their segments
    source_segments = {}
    with open(seg_file, 'r', encoding='utf-8', errors='replace') as f:
        for line in f:
            if line.strip():
                try:
                    seg = json.loads(line)
                    src = seg.get('source', '')
                    if src:
                        source_segments.setdefault(src, []).append(seg.get('text', ''))
                except:
                    pass

    # Load existing cache
    cache = {}
    if os.path.exists(cache_path):
        try:
            with open(cache_path, 'r', encoding='utf-8') as f:
                cache = json.load(f)
        except:
            cache = {}

    # Filter: only process docs without cached summary_zh
    todo = []
    for src in sorted(source_segments.keys()):
        key = f"{kb_name}::{src}"
        if key in cache and (cache[key].get('summary_zh') or '').strip():
            continue  # already cached with summary
        todo.append(src)

    _prefetch_state['total'] = len(todo)
    _prefetch_state['done'] = 0
    _prefetch_state['failed'] = 0
    _prefetch_state['results'] = []
    _prefetch_state['progress'] = 0

    if not todo:
        _prefetch_state['running'] = False
        return

    for idx, source in enumerate(todo):
        if not _prefetch_state['running']:
            break  # cancelled
        try:
            cache_key = f"{kb_name}::{source}"
            segments = source_segments[source]
            full_text = '\n\n'.join(segments)[:6000]

            # Call LLM for metadata extraction
            _keyword_taxonomy = [
                "Binary Code Similarity Detection", "Cross-Platform Binary Analysis",
                "Binary Function Matching", "Code Clone Detection", "Code Search & Retrieval",
                "Vulnerability Detection", "Recurring Vulnerability Detection",
                "Vulnerability Verification", "Patch Analysis", "CVE & Exploit Analysis",
                "Static Analysis", "Dynamic Analysis", "Symbolic Execution",
                "Program Slicing", "Control Flow Analysis", "Data Flow Analysis",
                "Abstract Interpretation", "Deep Learning", "Graph Neural Network",
                "Large Language Model", "Representation Learning", "Natural Language Processing",
                "Malware Detection & Analysis", "Software Security",
                "IoT & Firmware Security", "Obfuscation & Deobfuscation",
                "Android Security", "Empirical Study & Benchmark",
                "Software Maintenance & Evolution", "Network Security",
                "Control Systems & Optimization", "Other",
            ]
            _taxonomy_str = "、".join(_keyword_taxonomy)
            prompt = f"""分析以下从 PDF 提取的文本，提取信息并用 JSON 返回。只返回 JSON，不要其他内容。

文本：
{full_text}

返回格式：
{{\"title\":\"标题\",\"title_zh\":\"中文标题\",\"authors\":[\"作者1\"],\"affiliations\":[\"单位1\"],\"venue\":\"会议或期刊名\",\"year\":\"年份\",\"doc_type\":\"paper或survey或other\",\"summary_zh\":\"200字中文摘要\",\"keywords\":[\"关键词1\"]}}

重要：keywords 必须从以下固定标签中选择 2-5 个最相关的，按相关度排序，只能从这些标签中选，不要自己发明新标签：
{_taxonomy_str}"""

            # Use call_llm (DeepSeek cloud preferred, Ollama fallback)
            messages = [
                {'role': 'system', 'content': '你是一个文档分析助手。用户会给你从PDF提取的文本，你需要提取标题、作者、单位、会议、年份、摘要、关键词等信息，用JSON格式返回。只返回JSON，不要任何其他文字。keywords 必须从用户提供的固定标签列表中选择，不要自己发明。'},
                {'role': 'user', 'content': prompt}
            ]
            raw = call_llm(messages, timeout=180, prefer_cloud=True)
            raw = re.sub(r'^```(?:json)?\s*', '', raw)
            raw = re.sub(r'\s*```$', '', raw)
            start = raw.find('{')
            end = raw.rfind('}')
            if start >= 0 and end > start:
                raw = raw[start:end+1]
                detail = json.loads(raw)
            else:
                detail = parse_doc_detail_md(raw)

            detail['source'] = source
            detail['segment_count'] = len(segments)

            # Validate keywords against taxonomy
            _taxonomy_lower = {t.lower(): t for t in _keyword_taxonomy}
            raw_keywords = detail.get('keywords', [])
            validated = []
            for kw in raw_keywords:
                matched = _taxonomy_lower.get(kw.strip().lower())
                if matched and matched not in validated:
                    validated.append(matched)
            if not validated:
                validated = ["Other"]
            detail['keywords'] = validated

            # Fallback summary if missing
            if not (detail.get('summary_zh') or '').strip():
                summary_prompt = f"""请根据以下论文/文档内容，生成一段简体中文摘要（120-220字）。
要求：
1. 只输出摘要正文，不要标题，不要项目符号，不要解释。
2. 优先概括研究目标、核心方法、实验/效果与主要结论。
3. 如果文本信息不足，就尽量基于已有内容概括，不要留空。

文本：
{full_text[:4000]}
"""
                summary_text = call_llm([
                    {'role': 'system', 'content': '你是一个学术论文摘要助手，擅长把论文内容概括为简洁准确的中文摘要。'},
                    {'role': 'user', 'content': summary_prompt}
                ], timeout=120, prefer_cloud=True)
                summary_text = re.sub(r'^```(?:text)?\s*', '', summary_text)
                summary_text = re.sub(r'\s*```$', '', summary_text).strip()
                detail['summary_zh'] = summary_text

            # Save to cache
            cache[cache_key] = detail
            with open(cache_path, 'w', encoding='utf-8') as f:
                json.dump(cache, f, ensure_ascii=False, indent=2)

            _prefetch_state['results'].append({'filename': source, 'status': 'ok', 'title': detail.get('title_zh', detail.get('title', ''))[:40]})
            _prefetch_state['done'] += 1
        except Exception as e:
            _prefetch_state['results'].append({'filename': source, 'status': 'error', 'reason': str(e)[:80]})
            _prefetch_state['failed'] += 1

        _prefetch_state['progress'] = int((idx + 1) / len(todo) * 100)

    _prefetch_state['running'] = False


@app.route('/api/prefetch', methods=['POST'])
@require_auth(roles=['admin'])
def prefetch_details():
    """Start background prefetch of all uncached document details."""
    global _prefetch_state
    data = request.get_json() or {}
    kb_name = data.get('kb', os.getenv('RAG_KB_NAME', 'papers'))

    if _prefetch_state['running']:
        return jsonify({'running': True, 'progress': _prefetch_state['progress'],
                       'done': _prefetch_state['done'], 'total': _prefetch_state['total']})

    _prefetch_state = {'running': True, 'progress': 0, 'total': 0, 'done': 0, 'failed': 0, 'results': [], 'error': None}

    import threading
    t = threading.Thread(target=_do_prefetch, args=(kb_name,), daemon=True)
    t.start()
    return jsonify({'started': True})


@app.route('/api/prefetch', methods=['GET'])
@require_auth()
def prefetch_status():
    """Get current prefetch progress."""
    return jsonify(_prefetch_state)

@app.route('/api/status', methods=['GET'])
@require_auth()
def status():
    ok = False
    models = []
    try:
        r = requests.get(f"{CONFIG['ollama_url']}/api/tags", timeout=5)
        ok = r.status_code == 200
        models = [m['name'] for m in r.json().get('models', [])]
    except: pass
    return jsonify({'ollama': ok, 'models': models, 'base_dir': CONFIG['base_dir']})

# ========== Backend API (for programmatic access) ==========

@app.route('/api/search', methods=['POST'])
@require_auth()
def backend_search():
    """Pure retrieval — returns matched segments without calling LLM. Fast (sub-second)."""
    data = request.get_json() or {}
    query_text = data.get('query', '')
    kb_name = data.get('kb', os.getenv('RAG_KB_NAME', 'papers'))
    top_k = data.get('top_k', 8)
    min_score = data.get('min_score', 0.0)
    return_text = data.get('return_text', True)   # whether to include segment text
    text_max_len = data.get('text_max_len', 500)   # truncate segment text

    if not query_text.strip():
        return jsonify({'error': 'Empty query'}), 400

    kb_path = os.path.join(CONFIG['base_dir'], 'knowledge_bases', kb_name)
    if not os.path.exists(kb_path):
        return jsonify({'error': f'KB {kb_name} not found'}), 404

    # Embed query
    try:
        resp = requests.post(f"{CONFIG['ollama_url']}/api/embed",
            json={'model': CONFIG['embedding_model'], 'input': query_text}, timeout=60)
        query_emb = resp.json()['embeddings'][0]
    except Exception as e:
        return jsonify({'error': f'Embedding failed: {e}'}), 500

    # Query rewriting (same logic as /api/query)
    rewritten = query_text
    if any(w in query_text.lower() for w in ["what", "how", "why", "which", "does", "is", "are"]):
        rewritten = re.sub(r'\b(what|how|why|which|when|where|who|does|do|did|is|are|was|were|can|could|should|would)\b', '', rewritten, flags=re.IGNORECASE)
        rewritten = re.sub(r'\s+', ' ', rewritten).strip()
        rewritten = re.sub(r'[?]', '', rewritten)
    rewritten = re.sub(r'(是谁|是什么|为什么|怎么样|如何|哪些|哪个|多少|有没有|吗|呢|啊|的)', '', rewritten)
    rewritten = re.sub(r'\s+', ' ', rewritten).strip()

    try:
        results = hybrid_search(kb_path, rewritten, query_emb, top_k)
    except Exception as e:
        return jsonify({'error': f'Search failed: {e}'}), 500

    # Filter by min_score
    results = [r for r in results if r['score'] >= min_score]

    # Format output
    items = []
    for r in results:
        item = {'score': r['score'], 'source': r.get('source', '')}
        if return_text:
            item['text'] = r.get('text', '')[:text_max_len]
        items.append(item)

    # Unique sources
    sources = list(dict.fromkeys(r.get('source', '') for r in results if r.get('source')))

    return jsonify({
        'query': query_text,
        'rewritten_query': rewritten,
        'kb': kb_name,
        'total': len(items),
        'results': items,
        'sources': sources,
        'timestamp': datetime.now().isoformat()
    })


@app.route('/api/ask', methods=['POST'])
@require_auth()
def backend_ask():
    """Full RAG Q&A — retrieves relevant segments, then calls LLM to generate answer."""
    data = request.get_json() or {}
    query_text = data.get('query', '')
    kb_name = data.get('kb', os.getenv('RAG_KB_NAME', 'papers'))
    top_k = data.get('top_k', 8)
    system_prompt = data.get('system_prompt', '你是一个专业的学术研究助手。请根据提供的参考资料准确回答问题，使用简体中文。')
    temperature = data.get('temperature', 0.3)
    max_tokens = data.get('max_tokens', 2048)
    return_sources = data.get('return_sources', True)
    return_context = data.get('return_context', False)  # include raw context chunks

    if not query_text.strip():
        return jsonify({'error': 'Empty query'}), 400

    kb_path = os.path.join(CONFIG['base_dir'], 'knowledge_bases', kb_name)
    if not os.path.exists(kb_path):
        return jsonify({'error': f'KB {kb_name} not found'}), 404

    # Embed query
    try:
        resp = requests.post(f"{CONFIG['ollama_url']}/api/embed",
            json={'model': CONFIG['embedding_model'], 'input': query_text}, timeout=60)
        query_emb = resp.json()['embeddings'][0]
    except Exception as e:
        return jsonify({'error': f'Embedding failed: {e}'}), 500

    # Query rewriting
    rewritten = query_text
    if any(w in query_text.lower() for w in ["what", "how", "why", "which", "does", "is", "are"]):
        rewritten = re.sub(r'\b(what|how|why|which|when|where|who|does|do|did|is|are|was|were|can|could|should|would)\b', '', rewritten, flags=re.IGNORECASE)
        rewritten = re.sub(r'\s+', ' ', rewritten).strip()
        rewritten = re.sub(r'[?]', '', rewritten)
    rewritten = re.sub(r'(是谁|是什么|为什么|怎么样|如何|哪些|哪个|多少|有没有|吗|呢|啊|的)', '', rewritten)
    rewritten = re.sub(r'\s+', ' ', rewritten).strip()

    # Search
    try:
        results = hybrid_search(kb_path, rewritten, query_emb, top_k)
    except Exception as e:
        return jsonify({'error': f'Search failed: {e}'}), 500

    context = '\n\n'.join([r['text'] for r in results])

    # Build prompt
    prompt = f"""{system_prompt}

参考资料：
{context}

问题：{query_text}

请根据参考资料直接回答，使用简体中文。如果参考资料中没有相关信息，请明确说明。"""

    # Call LLM
    try:
        resp = requests.post(f"{CONFIG['ollama_url']}/api/chat",
            json={'model': CONFIG['chat_model'],
                  'messages': [
                      {'role': 'system', 'content': system_prompt},
                      {'role': 'user', 'content': prompt}
                  ],
                  'stream': False,
                  'options': {'temperature': temperature, 'num_predict': max_tokens}},
            timeout=180)
        answer = resp.json()['message']['content']
    except Exception as e:
        return jsonify({'error': f'LLM failed: {e}'}), 500

    # Build response
    response = {
        'answer': answer,
        'query': query_text,
        'rewritten_query': rewritten,
        'kb': kb_name,
        'timestamp': datetime.now().isoformat()
    }

    if return_sources:
        sources = list(dict.fromkeys(r.get('source', '') for r in results if r.get('source')))
        response['sources'] = [{'source': r.get('source', ''), 'score': r['score']} for r in results]
        response['unique_sources'] = sources

    if return_context:
        response['context'] = [r.get('text', '') for r in results]

    return jsonify(response)


@app.route('/api/v1/chat/completions', methods=['POST'])
@require_auth()
def openai_compatible():
    """OpenAI-compatible chat completions endpoint with RAG augmentation.
    
    Supports:
    - Standard OpenAI messages format
    - Auto RAG augmentation when messages contain questions
    - Optional 'kb' field in request body to specify knowledge base
    """
    data = request.get_json() or {}
    messages = data.get('messages', [])
    kb_name = data.get('kb', os.getenv('RAG_KB_NAME', 'papers'))
    top_k = data.get('top_k', 8)
    temperature = data.get('temperature', 0.3)
    max_tokens = data.get('max_tokens', 2048)
    stream = data.get('stream', False)
    rag_enabled = data.get('rag', True)  # allow disabling RAG

    if not messages:
        return jsonify({'error': 'No messages provided'}), 400

    # Extract last user message as query
    last_user_msg = ''
    for msg in reversed(messages):
        if msg.get('role') == 'user':
            last_user_msg = msg.get('content', '')
            break

    context_text = ''
    if rag_enabled and last_user_msg.strip():
        kb_path = os.path.join(CONFIG['base_dir'], 'knowledge_bases', kb_name)
        if os.path.exists(kb_path):
            try:
                resp = requests.post(f"{CONFIG['ollama_url']}/api/embed",
                    json={'model': CONFIG['embedding_model'], 'input': last_user_msg}, timeout=60)
                query_emb = resp.json()['embeddings'][0]

                # Query rewriting
                rewritten = last_user_msg
                if any(w in last_user_msg.lower() for w in ["what", "how", "why", "which", "does", "is", "are"]):
                    rewritten = re.sub(r'\b(what|how|why|which|when|where|who|does|do|did|is|are|was|were|can|could|should|would)\b', '', rewritten, flags=re.IGNORECASE)
                    rewritten = re.sub(r'\s+', ' ', rewritten).strip()
                    rewritten = re.sub(r'[?]', '', rewritten)
                rewritten = re.sub(r'(是谁|是什么|为什么|怎么样|如何|哪些|哪个|多少|有没有|吗|呢|啊|的)', '', rewritten)
                rewritten = re.sub(r'\s+', ' ', rewritten).strip()

                results = hybrid_search(kb_path, rewritten, query_emb, top_k)
                if results:
                    context_text = '\n\n'.join([r['text'] for r in results])
            except Exception:
                pass  # RAG failure → fall back to pure chat

    # Build augmented messages
    augmented = list(messages)
    if context_text:
        # Inject RAG context as system message
        rag_system = {'role': 'system', 'content': f'以下是检索到的参考资料，请据此回答用户问题，使用简体中文：\n\n{context_text}'}
        # Insert after any existing system messages
        inserted = False
        for i, msg in enumerate(augmented):
            if msg.get('role') != 'system':
                augmented.insert(i, rag_system)
                inserted = True
                break
        if not inserted:
            augmented.append(rag_system)

    # Call Ollama
    try:
        resp = requests.post(f"{CONFIG['ollama_url']}/api/chat",
            json={'model': CONFIG['chat_model'],
                  'messages': augmented,
                  'stream': False,
                  'options': {'temperature': temperature, 'num_predict': max_tokens}},
            timeout=180)
        content = resp.json()['message']['content']
    except Exception as e:
        return jsonify({'error': f'LLM failed: {e}'}), 500

    # OpenAI-compatible response format
    response = {
        'id': f'chatcmpl-{uuid.uuid4().hex[:12]}',
        'object': 'chat.completion',
        'created': int(datetime.now().timestamp()),
        'model': CONFIG['chat_model'],
        'choices': [{
            'index': 0,
            'message': {'role': 'assistant', 'content': content},
            'finish_reason': 'stop'
        }],
        'usage': {
            'prompt_tokens': -1,
            'completion_tokens': -1,
            'total_tokens': -1
        }
    }

    return jsonify(response)

# ========== Utility Functions ==========

def parse_doc_detail_md(raw):
    """Parse structured document detail from LLM markdown output.
    Handles formats like: **标题:** xxx  or  标题: xxx"""
    detail = {'title': '', 'title_zh': '', 'authors': [], 'affiliations': [],
              'venue': '', 'year': '', 'doc_type': 'other', 'summary_zh': '', 'keywords': []}
    # Mapping: possible LLM labels -> our field names
    field_map = {
        'title': ['title', '标题', '论文名称', '文档标题'],
        'title_zh': ['title_zh', '中文标题', '中文译名'],
        'authors': ['authors', 'author', '作者'],
        'affiliations': ['affiliations', 'affiliation', '单位', '机构', '所属单位'],
        'venue': ['venue', '会议', '期刊', '会议或期刊名', '发表会议', '发表期刊'],
        'year': ['year', '年份', '发表年份', '出版年份'],
        'doc_type': ['doc_type', '文献类型', '文档类型', '类型'],
        'summary_zh': ['summary_zh', '摘要', '中文摘要'],
        'keywords': ['keywords', '关键词', '关键字'],
    }
    for line in raw.split('\n'):
        line = line.strip()
        if not line:
            continue
        # Strip leading ** and ***
        clean = re.sub(r'^\*+\s*', '', line).strip()
        clean = re.sub(r'\s*\*+$', '', clean).strip()
        # Find "key: value" or "key：value" pattern
        m = re.match(r'(.+?)\s*[:：]\s*(.+)', clean)
        if not m:
            continue
        key, val = m.group(1).strip().lower(), m.group(2).strip()
        # Match to field
        for field, aliases in field_map.items():
            if any(a in key for a in aliases):
                if field in ('authors', 'affiliations', 'keywords'):
                    # Parse list: ["a","b"] or [a, b] or a, b, c
                    val_clean = re.sub(r'[\[\]()"\'"]', '', val)
                    items = [x.strip() for x in val_clean.split(',') if x.strip()]
                    # Remove "et al." style artifacts
                    items = [re.sub(r'\s*(et\s+al\.?|\u7b49)\s*$', '', x).strip() for x in items]
                    # Clean markdown bold markers
                    items = [re.sub(r'^\*+\s*', '', x).strip() for x in items]
                    items = [re.sub(r'\s*\*+$', '', x).strip() for x in items]
                    items = [x for x in items if len(x) > 0]
                    detail[field] = items
                else:
                    # Remove surrounding quotes/markdown
                    val = re.sub(r'^\*+', '', val).strip()
                    val = re.sub(r'\*+$', '', val).strip()
                    val = val.strip('"\'')
                    detail[field] = val
                break
    return detail

def cosine_similarity(a, b):
    dot = sum(x*y for x,y in zip(a,b))
    na = math.sqrt(sum(x*x for x in a))
    nb = math.sqrt(sum(x*x for x in b))
    return dot/(na*nb) if na and nb else 0

def get_kb_info(kb_path, name):
    meta_file = os.path.join(kb_path, 'metadata.json')
    if os.path.exists(meta_file):
        with open(meta_file) as f:
            meta = json.load(f)
        if not isinstance(meta, dict):
            meta = {'name': name}
    else:
        meta = {'name': name}
    meta.setdefault('name', name)
    meta.setdefault('description', '')
    meta.setdefault('model', 'unknown')
    seg_file = os.path.join(kb_path, 'segments.json')
    seg_count = 0
    if os.path.exists(seg_file):
        with open(seg_file) as f:
            seg_count = sum(1 for l in f if l.strip())
    meta['segments'] = seg_count
    meta['path'] = kb_path
    return meta

def hybrid_search(kb_path, query_text, query_embedding, top_k=5):
    segments_file = os.path.join(kb_path, "segments.json")
    embeddings_file = os.path.join(kb_path, "embeddings.json")
    segments = []
    with open(segments_file, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            if line.strip():
                try: segments.append(json.loads(line))
                except: pass
    embeddings = []
    with open(embeddings_file) as f:
        for line in f:
            if line.strip():
                try: embeddings.append(json.loads(line))
                except: pass
    if not segments or not embeddings:
        return []

    query_lower = query_text.lower()
    # English keywords (2+ chars)
    eng_words = set(re.findall(r"[a-zA-Z]{2,}", query_lower))
    # Chinese keywords: extract meaningful segments (2-4 char sliding window)
    cjk_chars = re.findall(r"[\u4e00-\u9fff\u3400-\u4dbf]", query_text)
    cjk_words = set()
    if len(cjk_chars) >= 2:
        cjk_str = ''.join(cjk_chars)
        for length in (2, 3, 4):
            for i in range(len(cjk_str) - length + 1):
                cjk_words.add(cjk_str[i:i+length])
    # Combine: English words are primary, CJK ngrams are supplementary
    # Only add English split tokens if they look like real words (not Chinese fragments)
    split_tokens = set()
    for t in query_lower.split():
        if len(t) >= 2 and not re.match(r'^[\u4e00-\u9fff]', t):
            split_tokens.add(t)
    query_words = eng_words | cjk_words | split_tokens
    query_words = {w for w in query_words if len(w) >= 2}
    # Deduplicate: remove CJK ngrams that are substrings of longer ones
    cjk_final = set()
    for w in sorted(cjk_words, key=len, reverse=True):
        if not any(w != lw and w in lw for lw in cjk_final):
            cjk_final.add(w)
    query_words = eng_words | cjk_final | split_tokens

    n = min(len(segments), len(embeddings))
    scored = []
    seen_texts = set()  # deduplicate results
    for i in range(n):
        text = segments[i].get("text", "") if isinstance(segments[i], dict) else str(segments[i])
        # Deduplicate: skip segments with identical first 100 chars
        text_key = text[:100].strip()
        if text_key in seen_texts:
            continue
        seen_texts.add(text_key)

        text_lower = text.lower()
        src = segments[i].get("source", "") if isinstance(segments[i], dict) else ""
        src_lower = src.lower()
        emb = embeddings[i]
        vec_score = cosine_similarity(query_embedding, emb) if emb else 0

        # Keyword scoring
        eng_hits = sum(1.0 for w in eng_words if w in text_lower)
        cjk_hits = sum(1.0 for w in cjk_final if w in text_lower)
        src_hits = sum(1.0 for w in eng_words if w in src_lower)

        # Normalize to [0,1]
        eng_ratio = eng_hits / max(len(eng_words), 1)
        cjk_ratio = cjk_hits / max(len(cjk_final), 1) if cjk_final else 0
        src_ratio = min(src_hits / max(len(eng_words), 1), 1.0)

        # Combined keyword score: English words weighted higher than CJK ngrams
        kw_ratio = max(eng_ratio, cjk_ratio * 0.5)

        # Final scoring with guaranteed [0,1] range
        if src_hits > 0 and kw_ratio > 0:
            final_score = 0.3 * vec_score + 0.4 * kw_ratio + 0.3 * src_ratio
        elif kw_ratio > 0:
            final_score = 0.4 * vec_score + 0.6 * kw_ratio
        else:
            final_score = vec_score

        final_score = min(final_score, 1.0)  # hard cap at 100%
        scored.append({"text": text[:500], "score": round(final_score, 4), "index": i, "source": src})

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:top_k]

def load_jsonl(filepath):
    items = []
    if not os.path.exists(filepath): return items
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                try: items.append(json.loads(line))
                except: pass
    return items

def save_jsonl(filepath, items):
    with open(filepath, "w", encoding="utf-8") as f:
        for item in items:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

def generate_standard_filename(text, base_dir):
    """Generate a standard filename: [3-digit ID]_[Title]_[Venue]_[Year].pdf

    Args:
        text: Extracted PDF text (uses first 500 chars for metadata)
        base_dir: Project base dir; reference/ under it is scanned for existing IDs

    Returns:
        New filename string, e.g. '038_Some Title_IEEE Access_2024.pdf'
    """
    ref_dir = os.path.join(base_dir, 'reference')
    os.makedirs(ref_dir, exist_ok=True)

    # --- Determine next ID by scanning existing files in reference/ ---
    max_id = 0
    if os.path.exists(ref_dir):
        for fn in os.listdir(ref_dir):
            m = re.match(r'^(\d{3})_', fn)
            if m:
                max_id = max(max_id, int(m.group(1)))
    next_id = max_id + 1

    # --- Extract metadata from first 500 chars ---
    head = (text or '')[:500]
    lines = [l.strip() for l in head.split('\n') if l.strip()]

    # Title: look for "Title" line, otherwise use first non-trivial line
    title = ''
    for line in lines:
        low = line.lower()
        if low.startswith('title') and ':' in line:
            title = line.split(':', 1)[1].strip()
            break
    if not title and lines:
        # Skip very short lines (likely headers/footers) and common noise
        for line in lines:
            if len(line) > 10 and not re.match(r'^(page|vol|doi|http|www|\d+$)', line.lower()):
                title = line
                break
    if not title:
        title = 'Untitled'
    # Truncate title if too long
    if len(title) > 120:
        title = title[:120]

    # Venue: look for keywords
    venue = ''
    venue_patterns = [
        r'(?:Conference|Proceedings|Journal|IEEE|ACM|USENIX|arXiv'
        r'|Transactions|Symposium|Workshop|International'
        r'|Magazine|Letters|Review|Forum|Archive'
        r'|\u4f1a\u8bae|\u671f\u520a|\u5b66\u62a5|\u5b66\u4f1a'
        r')[^\n]*',
    ]
    for line in lines:
        for pat in venue_patterns:
            m = re.search(pat, line, re.IGNORECASE)
            if m:
                candidate = m.group(0).strip()
                if len(candidate) > 3:
                    venue = candidate
                    break
        if venue:
            break
    if not venue:
        venue = 'Conference or Journal Name'

    # Year: find 20xx pattern
    year = ''
    year_matches = re.findall(r'\b(20\d{2})\b', head)
    if year_matches:
        year = year_matches[0]
    if not year:
        year = str(datetime.now().year)

    # --- Clean filename components ---
    def clean_part(s):
        # Keep Chinese, letters, digits, spaces, hyphens, dots
        s = re.sub(r'[^\w\s\-\u4e00-\u9fff\u3400-\u4dbf.]', '', s)
        s = re.sub(r'\s+', ' ', s).strip()
        s = s.strip('.')
        return s

    title_clean = clean_part(title)
    venue_clean = clean_part(venue)
    year_clean = clean_part(year)

    filename = f"{next_id:03d}_{title_clean}_{venue_clean}_{year_clean}.pdf"
    return filename


def extract_text(filepath, ext):
    if ext in ("txt", "md"):
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f: return f.read()
    elif ext == "pdf":
        try:
            import fitz
            doc = fitz.open(filepath)
            text = "".join(page.get_text() for page in doc)
            doc.close()
            return text.encode("utf-8", errors="replace").decode("utf-8")
        except:
            pass
        try:
            import PyPDF2
            text = ""
            with open(filepath, "rb") as f:
                for page in PyPDF2.PdfReader(f).pages:
                    text += (page.extract_text() or "") + "\n"
            return text
        except: return ""
    elif ext == "json":
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            return json.dumps(json.load(f), ensure_ascii=False, indent=2)
    elif ext == "csv":
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f: return f.read()
    return ""

def split_text(text, max_length=800, overlap=0, max_chunks=300):
    """Split text into chunks. If chunks exceed max_chunks, auto-enlarge max_length proportionally."""
    def _do_split(t, ml):
        chunks, cur = [], ""
        paragraphs = t.split("\n\n")
        if len(paragraphs) < 5:
            paragraphs = [p.strip() for p in t.split("\n") if p.strip()]
        for p in paragraphs:
            p = p.strip()
            if not p: continue
            while len(p) > ml:
                cut = ml
                for sep in ['。', '？', '！', '. ', '? ', '! ', '；', '; ', '\n']:
                    idx = p.rfind(sep, 0, ml)
                    if idx > ml // 4:
                        cut = idx + len(sep)
                        break
                chunk = p[:cut].strip()
                if len(chunk) > 30:
                    chunks.append(chunk)
                p = p[cut:].strip()
            if len(p) > ml:
                if len(p) > 30:
                    chunks.append(p)
            elif len(cur) + len(p) > ml:
                if cur and len(cur.strip()) > 30:
                    chunks.append(cur.strip())
                cur = p
            else:
                cur += "\n\n" + p
        if cur.strip() and len(cur.strip()) > 30:
            chunks.append(cur.strip())
        return chunks

    chunks = _do_split(text, max_length)
    # Auto-enlarge max_length if too many chunks
    if max_chunks > 0 and len(chunks) > max_chunks:
        scale = len(chunks) / max_chunks
        new_max_length = int(max_length * scale) + 1
        logger.warning(f"split_text: {len(chunks)} chunks exceeds max_chunks={max_chunks}, "
                       f"re-splitting with max_length={new_max_length}")
        chunks = _do_split(text, new_max_length)
    # Hard truncate if still over limit
    if max_chunks > 0 and len(chunks) > max_chunks:
        logger.warning(f"split_text: still {len(chunks)} chunks after resize, truncating to {max_chunks}")
        chunks = chunks[:max_chunks]
    return chunks


# ============================================================
# Agent Mode — Claude Code integration
# ============================================================
import subprocess, threading, uuid as _uuid, queue, time

AGENT_SESSIONS_DIR = os.path.join(CONFIG["base_dir"], "agent_sessions")
os.makedirs(AGENT_SESSIONS_DIR, exist_ok=True)

# In-memory session registry: {session_id: {"process": Popen, "queue": Queue, "status": str, "created_at": str}}
_agent_sessions = {}
_agent_lock = threading.Lock()


def _mark_claude_registered(session_id):
    """Mark a session as successfully registered with Claude Code."""
    # This function is called from background threads where g.user may not be available.
    # It uses the original AGENT_SESSIONS_DIR for backward compatibility with _run_claude.
    session_file = os.path.join(AGENT_SESSIONS_DIR, f"{session_id}.json")
    # Also try user_data dirs
    if not os.path.exists(session_file):
        for uname in os.listdir(USER_DATA_DIR):
            candidate = os.path.join(USER_DATA_DIR, uname, 'agent_sessions', f"{session_id}.json")
            if os.path.exists(candidate):
                session_file = candidate
                break
    try:
        if os.path.exists(session_file):
            data = json.loads(open(session_file, encoding="utf-8").read())
            data["claude_registered"] = True
            with open(session_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"[Agent] Failed to mark claude_registered: {e}")


def _run_claude(session_id, user_prompt, out_queue, resume=False, username=None):
    """Run claude CLI in subprocess, parse stream-json, push events to out_queue."""
    claude_bin = os.environ.get("CLAUDE_BIN", "/usr/local/nodejs/bin/claude")
    cmd = [
        claude_bin, "-p",
        "--output-format", "stream-json",
        "--verbose",
        "--dangerously-skip-permissions",
        "--fallback-model", "deepseek-v4-pro",
        "--max-turns", "8",
        "--allowed-tools", "Bash,Read,Write,Edit,Glob,Grep",
    ]
    if resume and session_id:
        cmd += ["--resume", session_id]
    else:
        cmd += ["--session-id", session_id]

    cwd = CONFIG["base_dir"]
    logger.info(f"[Agent] Starting claude session={session_id} resume={resume}")

    # 生成内部 JWT token 供 agent_tools 调用 API
    _agent_user = username or 'admin'
    _rag_token = generate_jwt(_agent_user, 'admin', expires_hours=2)
    env = dict(os.environ)
    env['RAG_TOKEN'] = _rag_token

    try:
        proc = subprocess.Popen(
            cmd, cwd=cwd, env=env,
            stdin=subprocess.PIPE,  # pass prompt via stdin to avoid ARG_MAX
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1
        )
        # Write prompt to stdin and close it — avoids [Errno 7] Argument list too long
        proc.stdin.write(user_prompt)
        proc.stdin.close()
        with _agent_lock:
            if session_id in _agent_sessions:
                _agent_sessions[session_id]["process"] = proc
                _agent_sessions[session_id]["status"] = "running"

        got_first_event = False
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            # Mark session as claude_registered on first successful stream event
            if not got_first_event:
                got_first_event = True
                _mark_claude_registered(session_id)
            out_queue.put(line)

        proc.wait()
        stderr_out = proc.stderr.read()
        if proc.returncode != 0:
            logger.error(f"[Agent] claude exited with code {proc.returncode}: {stderr_out[:500]}")
            out_queue.put(json.dumps({"type": "error", "message": f"claude exited with code {proc.returncode}", "stderr": stderr_out[:500]}))
    except Exception as e:
        logger.error(f"[Agent] Exception in _run_claude: {e}")
        out_queue.put(json.dumps({"type": "error", "message": str(e)}))
    finally:
        out_queue.put(json.dumps({"type": "done", "session_id": session_id}))
        with _agent_lock:
            if session_id in _agent_sessions:
                _agent_sessions[session_id]["status"] = "idle"
                _agent_sessions[session_id]["process"] = None


def _parse_stream_events(raw_lines):
    """Parse stream-json lines into structured events for SSE."""
    events = []
    assistant_text = ""
    tool_calls = []
    final_result = None

    for line in raw_lines:
        try:
            obj = json.loads(line)
        except:
            continue
        t = obj.get("type", "")

        if t == "assistant":
            msg = obj.get("message", {})
            for c in msg.get("content", []):
                if c.get("type") == "text":
                    assistant_text += c.get("text", "")
                elif c.get("type") == "tool_use":
                    tool_calls.append({"name": c.get("name"), "input": c.get("input", {})})
                elif c.get("type") == "tool_result":
                    tool_calls.append({"name": "_result", "content": str(c.get("content", ""))[:500]})
        elif t == "result":
            final_result = obj

    return {"text": assistant_text, "tool_calls": tool_calls, "result": final_result}


def _agent_session_key(session_id):
    """Build user-qualified key for _agent_sessions dict."""
    username = getattr(g, 'user', 'admin')
    return f"{username}/{session_id}"

def _agent_session_key_for(username, session_id):
    return f"{username}/{session_id}"

@app.route('/api/agent/sessions', methods=['GET'])
@require_auth()
def agent_list_sessions():
    """List agent sessions."""
    sessions = []
    agent_dir = _user_agent_dir()
    for f in sorted(Path(agent_dir).glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            akey = _agent_session_key(data.get("id", ""))
            with _agent_lock:
                runtime_status = _agent_sessions.get(akey, {}).get("status", "idle")
            sessions.append({
                "id": data.get("id", ""),
                "title": data.get("title", "新 Agent 会话"),
                "kb": data.get("kb", os.getenv("RAG_KB_NAME", "papers")),
                "status": runtime_status,
                "message_count": len(data.get("messages", [])),
                "created_at": data.get("created_at", ""),
                "updated_at": data.get("updated_at", ""),
            })
        except:
            pass
    return jsonify({"sessions": sessions})


@app.route('/api/agent/sessions', methods=['POST'])
@require_auth()
def agent_create_session():
    """Create a new agent session."""
    data = request.get_json(force=True)
    session_id = data.get("id") or str(_uuid.uuid4())
    kb = data.get("kb", os.getenv("RAG_KB_NAME", "papers"))
    title = data.get("title", "新 Agent 会话")

    session_file = os.path.join(_user_agent_dir(), f"{session_id}.json")
    akey = _agent_session_key(session_id)
    if os.path.exists(session_file):
        # Update existing
        existing = json.loads(open(session_file, encoding="utf-8").read())
        if data.get("messages"):
            existing["messages"] = data["messages"]
        if title and title not in ("新 Agent 会话", "new_chat", "untitled"):
            existing["title"] = title
        existing["updated_at"] = datetime.now().isoformat()
        with open(session_file, "w", encoding="utf-8") as f:
            json.dump(existing, f, ensure_ascii=False, indent=2)
        return jsonify({"success": True, "id": existing["id"], "title": existing["title"]})

    # New session
    now = datetime.now().isoformat()
    session_data = {
        "id": session_id,
        "title": title,
        "kb": kb,
        "messages": data.get("messages", []),
        "created_at": now,
        "updated_at": now,
    }
    with open(session_file, "w", encoding="utf-8") as f:
        json.dump(session_data, f, ensure_ascii=False, indent=2)

    with _agent_lock:
        _agent_sessions[akey] = {"process": None, "queue": None, "status": "idle", "created_at": now}

    return jsonify({"success": True, "id": session_id, "title": title})


@app.route('/api/agent/sessions/<session_id>', methods=['GET'])
@require_auth()
def agent_get_session(session_id):
    """Get agent session detail."""
    session_file = os.path.join(_user_agent_dir(), f"{session_id}.json")
    if not os.path.exists(session_file):
        return jsonify({"error": "Session not found"}), 404
    data = json.loads(open(session_file, encoding="utf-8").read())
    akey = _agent_session_key(session_id)
    with _agent_lock:
        data["status"] = _agent_sessions.get(akey, {}).get("status", "idle")
    return jsonify(data)


@app.route('/api/agent/sessions/<session_id>', methods=['DELETE'])
@require_auth()
def agent_delete_session(session_id):
    """Delete an agent session."""
    session_file = os.path.join(_user_agent_dir(), f"{session_id}.json")
    if not os.path.exists(session_file):
        return jsonify({"error": "Session not found"}), 404
    akey = _agent_session_key(session_id)
    # Kill running process if any
    with _agent_lock:
        sess = _agent_sessions.get(akey)
        if sess and sess.get("process"):
            try:
                sess["process"].terminate()
            except:
                pass
        _agent_sessions.pop(akey, None)
    os.remove(session_file)
    return jsonify({"success": True})


@app.route('/api/agent/chat/<session_id>', methods=['GET'])
def agent_chat_stream(session_id):
    """SSE endpoint: stream claude code output for a session. Auth via query param or header."""
    # Auth: support both header and query param for EventSource compatibility
    token = request.args.get("token", "")
    if not token:
        auth_header = request.headers.get("Authorization", "")
        token = auth_header.replace("Bearer ", "") if auth_header.startswith("Bearer ") else ""
    
    # Try JWT first, then legacy auth_code
    payload = verify_jwt(token)
    username = 'admin'
    if payload:
        username = payload['username']
    elif token != CONFIG["auth_code"]:
        return jsonify({"error": "Unauthorized"}), 401
    
    akey = _agent_session_key_for(username, session_id)

    # Check if there's an active queue for this session
    with _agent_lock:
        sess = _agent_sessions.get(akey)
    if not sess or not sess.get("queue"):
        return jsonify({"error": "No active stream for this session"}), 404

    q = sess["queue"]

    def generate():
        while True:
            try:
                item = q.get(timeout=120)
            except queue.Empty:
                yield f"data: {json.dumps({'type': 'heartbeat'})}\n\n"
                continue
            yield f"data: {item}\n\n"
            try:
                parsed = json.loads(item)
                if parsed.get("type") == "done":
                    break
            except:
                pass

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route('/api/agent/chat', methods=['POST'])
@require_auth()
def agent_chat_send():
    """Send a message to the agent — spawns/resumes claude code session."""
    data = request.get_json(force=True)
    username = getattr(g, 'user', 'admin')
    session_id = data.get("session_id", "")
    message = data.get("message", "").strip()
    kb = data.get("kb", os.getenv("RAG_KB_NAME", "papers"))

    if not message:
        return jsonify({"error": "message is required"}), 400

    akey = _agent_session_key(session_id)

    # Auto-create session if needed
    if not session_id:
        session_id = str(_uuid.uuid4())
        akey = _agent_session_key(session_id)
        session_file = os.path.join(_user_agent_dir(), f"{session_id}.json")
        now = datetime.now().isoformat()
        title = message[:12] + "_" + datetime.now().strftime("%Y-%m-%d")
        with open(session_file, "w", encoding="utf-8") as f:
            json.dump({"id": session_id, "title": title, "kb": kb, "messages": [], "claude_registered": False, "created_at": now, "updated_at": now}, f, ensure_ascii=False, indent=2)
        with _agent_lock:
            _agent_sessions[akey] = {"process": None, "queue": None, "status": "idle", "created_at": now}

    # Check if Claude Code has ever used this session (registered = ran at least once)
    session_file = os.path.join(_user_agent_dir(), f"{session_id}.json")
    has_history = False
    if os.path.exists(session_file):
        try:
            existing = json.loads(open(session_file, encoding="utf-8").read())
            has_history = existing.get("claude_registered", False)
        except:
            has_history = False

    # Create output queue
    out_queue = queue.Queue()
    with _agent_lock:
        if akey not in _agent_sessions:
            _agent_sessions[akey] = {"process": None, "queue": None, "status": "idle"}
        _agent_sessions[akey]["queue"] = out_queue
        _agent_sessions[akey]["status"] = "running"

    # Build prompt — 直接传递用户输入，由 Agent 自主决定是否查询 RAG
    prompt = message
    if not has_history:
        prompt = f"[当前知识库: {kb}]\n\n{message}"

    # Start claude in background thread
    t = threading.Thread(target=_run_claude, args=(session_id, prompt, out_queue, has_history, username), daemon=True)
    t.start()

    return jsonify({"success": True, "session_id": session_id})


@app.route('/api/agent/parse-result', methods=['POST'])
@require_auth()
def agent_parse_result():
    """Parse accumulated stream events into final result for saving."""
    data = request.get_json(force=True)
    raw_lines = data.get("raw_events", [])
    parsed = _parse_stream_events(raw_lines)
    return jsonify(parsed)


# ============================================================
# Deep Read — 论文精读报告生成
# ============================================================

_deep_read_lock = threading.Lock()
_deep_read_tasks = {}  # {report_id: {"status": str, "phase": str, "progress": str, "chars": int, "queue": Queue}}


def _extract_pdf_text(source, base_dir):
    """Extract full text from a PDF using pdftotext (max 30 pages)."""
    pdf_path = os.path.join(base_dir, 'reference', source)
    if not os.path.exists(pdf_path):
        logger.error(f"[DeepRead] PDF not found: {pdf_path}")
        return None
    try:
        cmd = ['pdftotext', '-enc', 'UTF-8', '-l', '30', pdf_path, '-']
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            logger.error(f"[DeepRead] pdftotext failed: {result.stderr[:500]}")
            return None
        text = result.stdout
        if not text or not text.strip():
            logger.error(f"[DeepRead] pdftotext returned empty text for {source}")
            return None
        return text
    except Exception as e:
        logger.error(f"[DeepRead] _extract_pdf_text error: {e}")
        return None


def _run_deep_read(report_id, source, kb, out_queue):
    """Background thread: run Claude Code to generate deep read report."""
    temp_file_path = os.path.join(DEEP_READS_DIR, f"temp_{report_id}.txt")
    report_file = os.path.join(DEEP_READS_DIR, f"{report_id}.md")
    meta_file = os.path.join(DEEP_READS_DIR, f"{report_id}.json")

    full_text = ""
    try:
        # 1. Extract PDF text
        out_queue.put(json.dumps({"type": "text", "content": "📄 正在提取 PDF 全文..."}))
        with _deep_read_lock:
            if report_id in _deep_read_tasks:
                _deep_read_tasks[report_id].update({"phase": "extracting", "progress": "正在提取 PDF 全文..."})
        pdf_text = _extract_pdf_text(source, CONFIG['base_dir'])
        if not pdf_text:
            out_queue.put(json.dumps({"type": "error", "message": "PDF 文本提取失败，请确认文件存在且可读"}))
            with _deep_read_lock:
                if report_id in _deep_read_tasks:
                    _deep_read_tasks[report_id].update({"phase": "error", "progress": "PDF 文本提取失败"})
            return

        # Save to temp file
        with open(temp_file_path, 'w', encoding='utf-8') as f:
            f.write(pdf_text)

        out_queue.put(json.dumps({"type": "text", "content": f"✅ 已提取 {len(pdf_text)} 字符，开始生成精读报告...\n\n"}))
        with _deep_read_lock:
            if report_id in _deep_read_tasks:
                _deep_read_tasks[report_id].update({"phase": "generating", "progress": f"已提取 {len(pdf_text)} 字符，Claude Code 正在分析论文..."})

        # 2. Build prompt
        prompt = f"""请阅读文件 {temp_file_path}，这是一篇学术论文的全文。请严格按照以下7个方面撰写精读报告，每个方面用二级标题（##）分隔，每个方面都要详实具体，引用论文中的关键数据和细节：

1. 研究问题 — 该论文用于解决什么问题？
2. 现有方法的局限性 — 当前方法存在哪些不足和局限？
3. 核心挑战与解决方案 — 论文解决了哪些关键技术挑战？如何解决？
4. 主要方法 — 论文的核心方法、技术路线、模型架构、关键算法
5. 实验设计 — 数据集、baseline方法、评估指标、实验设置
6. 实验结果与结论 — 实验效果如何？得出了哪些重要结论？
7. 不足与改进方向 — 该论文存在哪些不足？可能的改进方向？

要求：用中文撰写，使用 Markdown 格式，不要编造论文中没有的信息。直接输出报告内容，不要有其他废话。"""

        # 3. Run Claude Code CLI
        claude_bin = os.environ.get("CLAUDE_BIN", "/usr/local/nodejs/bin/claude")
        cmd = [
            claude_bin, "-p", prompt,
            "--output-format", "stream-json",
            "--verbose",
            "--dangerously-skip-permissions",
            "--fallback-model", "deepseek-v4-pro",
    ]

        proc = subprocess.Popen(
            cmd, cwd=CONFIG['base_dir'],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1
        )

        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue

            t = obj.get("type", "")

            if t == "assistant":
                msg = obj.get("message", {})
                for c in msg.get("content", []):
                    if c.get("type") == "text":
                        text_chunk = c.get("text", "")
                        if text_chunk:
                            full_text += text_chunk
                            out_queue.put(json.dumps({"type": "text", "content": text_chunk}))
                            with _deep_read_lock:
                                if report_id in _deep_read_tasks:
                                    _deep_read_tasks[report_id]["chars"] = len(full_text)
                                    _deep_read_tasks[report_id]["progress"] = f"正在生成精读报告... ({len(full_text)} 字符)"
            elif t == "result":
                result_text = obj.get("result", "")
                if result_text and not full_text:
                    full_text = result_text
                    out_queue.put(json.dumps({"type": "text", "content": result_text}))

        proc.wait()
        stderr_out = proc.stderr.read()
        if proc.returncode != 0:
            logger.error(f"[DeepRead] claude exited with code {proc.returncode}: {stderr_out[:500]}")
            if not full_text:
                # Fallback: try DeepSeek via call_llm
                out_queue.put(json.dumps({"type": "text", "content": "⚠️ Claude Code 不可用，切换到 DeepSeek 继续...\n\n"}))
                with _deep_read_lock:
                    if report_id in _deep_read_tasks:
                        _deep_read_tasks[report_id].update({"phase": "fallback-generating", "progress": "Claude Code 不可用，正在使用 DeepSeek 生成..."})
                try:
                    # Build fallback prompt with text inline (DeepSeek can't read local files)
                    fb_prompt = f"""以下是一篇学术论文的全文，请严格按照以下7个方面撰写精读报告，每个方面用二级标题（##）分隔，每个方面都要详实具体，引用论文中的关键数据和细节：

1. 研究问题 — 该论文用于解决什么问题？
2. 现有方法的局限性 — 当前方法存在哪些不足和局限？
3. 核心挑战与解决方案 — 论文解决了哪些关键技术挑战？如何解决？
4. 主要方法 — 论文的核心方法、技术路线、模型架构、关键算法
5. 实验设计 — 数据集、baseline方法、评估指标、实验设置
6. 实验结果与结论 — 实验效果如何？得出了哪些重要结论？
7. 不足与改进方向 — 该论文存在哪些不足？可能的改进方向？

要求：用中文撰写，使用 Markdown 格式，不要编造论文中没有的信息。直接输出报告内容，不要有其他废话。

论文全文：
{pdf_text[:60000]}"""
                    fb_messages = [
                        {"role": "system", "content": "你是一个论文精读分析助手。"},
                        {"role": "user", "content": fb_prompt}
                    ]
                    fb_text = call_llm(fb_messages, max_tokens=8192)
                    if fb_text:
                        full_text = fb_text
                        out_queue.put(json.dumps({"type": "text", "content": fb_text}))
                    else:
                        out_queue.put(json.dumps({"type": "error", "message": f"Claude Code 执行失败 (code {proc.returncode}) 且 DeepSeek fallback 也失败"}))
                        return
                except Exception as fb_e:
                    logger.error(f"[DeepRead] Fallback call_llm also failed: {fb_e}")
                    out_queue.put(json.dumps({"type": "error", "message": f"Claude Code 失败且 fallback 异常: {str(fb_e)}"}))
                    return
            else:
                return

        # 4. Save report and metadata on success
        if full_text.strip():
            with open(report_file, 'w', encoding='utf-8') as f:
                f.write(full_text)
            meta = {
                "source": source,
                "kb": kb,
                "created_at": datetime.now().isoformat(),
                "status": "done"
            }
            with open(meta_file, 'w', encoding='utf-8') as f:
                json.dump(meta, f, ensure_ascii=False, indent=2)
            logger.info(f"[DeepRead] Report saved: {report_file}")

    except Exception as e:
        logger.error(f"[DeepRead] Exception in _run_deep_read: {e}")
        out_queue.put(json.dumps({"type": "error", "message": f"生成失败: {str(e)}"}))
        with _deep_read_lock:
            if report_id in _deep_read_tasks:
                _deep_read_tasks[report_id].update({"phase": "error", "progress": f"生成失败: {str(e)}"})
    finally:
        # Clean up temp file
        if os.path.exists(temp_file_path):
            try:
                os.remove(temp_file_path)
            except:
                pass
        out_queue.put(json.dumps({"type": "done", "report_id": report_id}))
        with _deep_read_lock:
            if report_id in _deep_read_tasks:
                _deep_read_tasks[report_id].update({"status": "done", "phase": "done", "progress": "精读报告生成完成"})


@app.route('/api/deep-read', methods=['POST'])
@require_auth()
def start_deep_read():
    """Start a deep read report generation task."""
    data = request.get_json(force=True)
    source = data.get("source", "")
    kb = data.get("kb", os.getenv("RAG_KB_NAME", "papers"))

    if not source:
        return jsonify({"error": "source is required"}), 400

    pdf_path = os.path.join(CONFIG['base_dir'], 'reference', source)
    if not os.path.exists(pdf_path):
        return jsonify({
            "error": "PDF file not found in reference directory",
            "detail": "该文档的 segments 已存在，但原始 PDF 文件缺失，请重新上传 PDF 后再生成精读报告",
            "source": source
        }), 404

    report_id = source.split("_")[0]

    # Check if report already exists
    report_file = os.path.join(DEEP_READS_DIR, f"{report_id}.md")
    if os.path.exists(report_file) and os.path.getsize(report_file) > 0:
        return jsonify({"status": "done", "report_id": report_id})

    # Check if already running
    with _deep_read_lock:
        task = _deep_read_tasks.get(report_id)
        if task and task.get("status") == "running":
            return jsonify({"status": "running", "report_id": report_id})

        # Start new task
        out_queue = queue.Queue()
        _deep_read_tasks[report_id] = {"status": "running", "phase": "starting", "progress": "任务已启动，等待处理...", "chars": 0, "queue": out_queue}

    t = threading.Thread(target=_run_deep_read, args=(report_id, source, kb, out_queue), daemon=True)
    t.start()

    return jsonify({"status": "started", "report_id": report_id})


@app.route('/api/deep-read/<report_id>/stream', methods=['GET'])
def deep_read_stream(report_id):
    """SSE endpoint: stream deep read report generation progress."""
    token = request.args.get("token", "")
    if not token:
        auth_header = request.headers.get("Authorization", "")
        token = auth_header.replace("Bearer ", "") if auth_header.startswith("Bearer ") else ""
    if token != CONFIG["auth_code"]:
        return jsonify({"error": "Unauthorized"}), 401

    with _deep_read_lock:
        task = _deep_read_tasks.get(report_id)
    if not task or not task.get("queue"):
        return jsonify({"error": "No active stream for this report"}), 404

    q = task["queue"]

    def generate():
        while True:
            try:
                item = q.get(timeout=120)
            except queue.Empty:
                yield f"data: {json.dumps({'type': 'heartbeat'})}\n\n"
                continue
            yield f"data: {item}\n\n"
            try:
                parsed = json.loads(item)
                if parsed.get("type") == "done":
                    break
            except:
                pass

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route('/api/deep-read/<report_id>', methods=['GET'])
@require_auth()
def get_deep_read_report(report_id):
    """Get a completed deep read report."""
    report_file = os.path.join(DEEP_READS_DIR, f"{report_id}.md")
    meta_file = os.path.join(DEEP_READS_DIR, f"{report_id}.json")

    if not os.path.exists(report_file):
        return jsonify({"error": "Report not found"}), 404

    content = ""
    with open(report_file, 'r', encoding='utf-8') as f:
        content = f.read()

    meta = {}
    if os.path.exists(meta_file):
        try:
            with open(meta_file, 'r', encoding='utf-8') as f:
                meta = json.load(f)
        except:
            pass

    return jsonify({
        "report_id": report_id,
        "source": meta.get("source", ""),
        "content": content,
        "created_at": meta.get("created_at", ""),
        "status": "done"
    })


@app.route('/api/deep-read/<report_id>/status', methods=['GET'])
@require_auth()
def deep_read_status(report_id):
    """Get the current status/progress of a deep read task."""
    # Check task in memory first
    with _deep_read_lock:
        task = _deep_read_tasks.get(report_id)

    if task:
        return jsonify({
            "report_id": report_id,
            "status": task.get("status", "unknown"),
            "phase": task.get("phase", ""),
            "progress": task.get("progress", ""),
            "chars": task.get("chars", 0)
        })

    # Check if report file exists (completed before restart)
    report_file = os.path.join(DEEP_READS_DIR, f"{report_id}.md")
    if os.path.exists(report_file) and os.path.getsize(report_file) > 0:
        meta_file = os.path.join(DEEP_READS_DIR, f"{report_id}.json")
        meta = {}
        if os.path.exists(meta_file):
            try:
                with open(meta_file, 'r', encoding='utf-8') as f:
                    meta = json.load(f)
            except:
                pass
        return jsonify({
            "report_id": report_id,
            "status": "done",
            "phase": "done",
            "progress": "精读报告已生成",
            "chars": os.path.getsize(report_file),
            "source": meta.get("source", ""),
            "created_at": meta.get("created_at", "")
        })

    return jsonify({"report_id": report_id, "status": "not_found", "phase": "", "progress": "", "chars": 0}), 404


@app.route('/api/deep-reads', methods=['GET'])
@require_auth()
def list_deep_reads():
    """List all deep read reports."""
    reports = []
    for f in sorted(Path(DEEP_READS_DIR).glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            with open(f, 'r', encoding='utf-8') as fh:
                meta = json.load(fh)
            meta["report_id"] = f.stem
            reports.append(meta)
        except:
            pass
    return jsonify({"reports": reports})


@app.route('/api/deep-read/<report_id>/export', methods=['GET'])
def export_deep_read(report_id):
    """对外 API：通过 api_key 认证获取精读报告内容。"""
    api_key = request.args.get('api_key', '')
    expected_key = CONFIG.get('export_api_key') or CONFIG['auth_code']
    if api_key != expected_key:
        return jsonify({'error': 'Unauthorized: invalid api_key'}), 401
    # 防止路径遍历
    if '..' in report_id or '/' in report_id:
        return jsonify({'error': 'Invalid report_id'}), 400
    report_file = os.path.join(DEEP_READS_DIR, f"{report_id}.md")
    meta_file = os.path.join(DEEP_READS_DIR, f"{report_id}.json")
    if not os.path.exists(report_file):
        return jsonify({'error': 'Report not found'}), 404
    content = ''
    with open(report_file, 'r', encoding='utf-8') as f:
        content = f.read()
    meta = {}
    if os.path.exists(meta_file):
        try:
            with open(meta_file, 'r', encoding='utf-8') as f:
                meta = json.load(f)
        except Exception:
            pass
    return jsonify({
        'report_id': report_id,
        'source': meta.get('source', ''),
        'content': content,
        'created_at': meta.get('created_at', ''),
        'kb': meta.get('kb', ''),
    })


@app.route('/api/deep-reads/export', methods=['GET'])
def export_deep_reads_list():
    """对外 API：通过 api_key 认证获取所有精读报告列表（不含正文）。"""
    api_key = request.args.get('api_key', '')
    expected_key = CONFIG.get('export_api_key') or CONFIG['auth_code']
    if api_key != expected_key:
        return jsonify({'error': 'Unauthorized: invalid api_key'}), 401
    reports = []
    for f in sorted(Path(DEEP_READS_DIR).glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            with open(f, 'r', encoding='utf-8') as fh:
                meta = json.load(fh)
            report_file = os.path.join(DEEP_READS_DIR, f"{f.stem}.md")
            reports.append({
                'report_id': f.stem,
                'source': meta.get('source', ''),
                'kb': meta.get('kb', ''),
                'created_at': meta.get('created_at', ''),
                'has_content': os.path.exists(report_file) and os.path.getsize(report_file) > 0,
            })
        except Exception:
            pass
    return jsonify({'reports': reports})


@app.route('/api/deep-read/<report_id>', methods=['DELETE'])
@require_auth()
def delete_deep_read(report_id):
    """Delete a deep read report and its metadata."""
    # Sanitize report_id to prevent path traversal
    if '..' in report_id or '/' in report_id:
        return jsonify({'error': 'Invalid report_id'}), 400
    report_file = os.path.join(DEEP_READS_DIR, f"{report_id}.md")
    meta_file = os.path.join(DEEP_READS_DIR, f"{report_id}.json")
    deleted = []
    for f in [report_file, meta_file]:
        if os.path.exists(f):
            os.remove(f)
            deleted.append(os.path.basename(f))
    if not deleted:
        return jsonify({'error': 'Report not found'}), 404
    # Also remove from running tasks
    with _deep_read_lock:
        _deep_read_tasks.pop(report_id, None)
    return jsonify({'success': True, 'deleted': deleted})


@app.route('/api/me', methods=['GET'])
@require_auth()
def get_me():
    """Return current user info."""
    users = load_users()
    user = users.get(g.user, {})
    return jsonify({
        'username': g.user,
        'role': g.role,
        'display_name': user.get('display_name', g.user),
    })


@app.route('/api/change-password', methods=['PUT'])
@require_auth()
def change_password():
    data = request.get_json() or {}
    old_password = (data.get('old_password') or '').strip()
    new_password = (data.get('new_password') or '').strip()
    if not old_password or not new_password:
        return jsonify({'error': '请输入旧密码和新密码'}), 400
    if len(new_password) < 4:
        return jsonify({'error': '新密码至少4位'}), 400
    users = load_users()
    user = users.get(g.user)
    if not user or not check_password(old_password, user['password_hash']):
        return jsonify({'error': '旧密码错误'}), 403
    user['password_hash'] = hash_password(new_password)
    save_users(users)
    return jsonify({'success': True, 'message': '密码修改成功'})


# ============================================================
# Paper Writing APIs
# ============================================================

PAPER_GUIDE_SYSTEM = (
    "你是一个学术论文撰写助手。通过提问逐步收集以下信息："
    "1. 研究领域和具体问题；2. 主要贡献和创新点；3. 目标会议或期刊；"
    "4. 相关工作和baseline；5. 实验设计和预期结果。"
    "信息充分后自动生成大纲。每次只问一个问题，用中文回复。"
)

@app.route('/api/papers', methods=['POST'])
@require_auth()
def create_paper():
    data = request.get_json() or {}
    title = (data.get('title') or '').strip()
    if not title:
        return jsonify({'error': '标题不能为空'}), 400
    paper_id = data.get('id') or str(uuid.uuid4())[:8]
    papers_dir = get_papers_dir()
    if os.path.exists(os.path.join(papers_dir, paper_id, 'meta.json')):
        return jsonify({'error': '项目ID已存在'}), 409
    # Support importing from agent session
    agent_session_id = data.get('agent_session_id')
    guide_messages = [
        {'role': 'assistant', 'content': f'你好！我来帮你撰写论文「{title}」。首先，请告诉我这篇论文的研究领域是什么？比如：计算机科学、医学、社会科学、经济学、教育学、自然语言处理等。'}
    ]
    if agent_session_id:
        session_file = os.path.join(_user_agent_dir(), f'{agent_session_id}.json')
        if os.path.exists(session_file):
            with open(session_file, 'r', encoding='utf-8') as sf:
                session_data = json.load(sf)
            guide_messages = session_data.get('messages', [])

    now = datetime.now().isoformat()
    meta = {
        'id': paper_id,
        'title': title,
        'description': (data.get('description') or '').strip(),
        'status': 'draft',
        'outline': '',
        'guide_messages': guide_messages,
        'agent_session_id': agent_session_id or '',
        'created_at': now,
        'updated_at': now,
    }
    save_paper(paper_id, meta)
    return jsonify(meta)

@app.route('/api/papers', methods=['GET'])
@require_auth()
def list_papers():
    papers_dir = get_papers_dir()
    result = []
    if os.path.isdir(papers_dir):
        for d in os.listdir(papers_dir):
            mp = os.path.join(papers_dir, d, 'meta.json')
            if os.path.exists(mp):
                with open(mp, 'r', encoding='utf-8') as f:
                    result.append(json.load(f))
    result.sort(key=lambda x: x.get('updated_at', ''), reverse=True)
    return jsonify(result)

@app.route('/api/papers/<paper_id>', methods=['GET'])
@require_auth()
def get_paper(paper_id):
    meta = load_paper(paper_id)
    if not meta:
        return jsonify({'error': '论文项目不存在'}), 404
    return jsonify(meta)

@app.route('/api/papers/<paper_id>', methods=['PUT'])
@require_auth()
def update_paper(paper_id):
    meta = load_paper(paper_id)
    if not meta:
        return jsonify({'error': '论文项目不存在'}), 404
    data = request.get_json() or {}
    for k in ('title', 'description', 'status', 'outline', 'sections'):
        if k in data:
            meta[k] = data[k]
    meta['updated_at'] = datetime.now().isoformat()
    save_paper(paper_id, meta)
    return jsonify(meta)

@app.route('/api/papers/<paper_id>', methods=['DELETE'])
@require_auth()
def delete_paper(paper_id):
    p = get_paper_path(paper_id)
    if not os.path.exists(p):
        return jsonify({'error': '论文项目不存在'}), 404
    shutil.rmtree(os.path.join(get_papers_dir(), paper_id))
    return jsonify({'success': True})

@app.route('/api/papers/<paper_id>/outline', methods=['POST'])
@require_auth()
def generate_paper_outline(paper_id):
    meta = load_paper(paper_id)
    if not meta:
        return jsonify({'error': '论文项目不存在'}), 404
    title = meta.get('title', '')
    desc = meta.get('description', '')
    msgs = meta.get('guide_messages', [])
    # Build context from guide messages
    context_parts = []
    for m in msgs:
        if m['role'] == 'user':
            context_parts.append(f"用户: {m['content']}")
        else:
            context_parts.append(f"助手: {m['content']}")
    context_str = '\n'.join(context_parts) if context_parts else '暂无'
    prompt = (
        f"请为以下论文生成一个详细的章节大纲：\n"
        f"标题: {title}\n"
        f"描述: {desc or '无'}\n"
        f"用户提供的上下文信息:\n{context_str}\n\n"
        "请生成包含以下部分的详细大纲（每部分用二级标题 ## 标记）：\n"
        "1. 摘要 (Abstract)\n2. 引言 (Introduction)\n3. 相关工作 (Related Work)\n"
        "4. 方法 (Methodology)\n5. 实验 (Experiments)\n6. 讨论 (Discussion)\n"
        "7. 结论 (Conclusion)\n\n"
        "每个部分请给出3-5个要点。用中文回复。"
    )
    messages = [
        {'role': 'system', 'content': '你是一个学术论文撰写助手，擅长生成论文大纲。用中文回复。'},
        {'role': 'user', 'content': prompt},
    ]
    try:
        outline = call_llm(messages, timeout=90, prefer_cloud=True)
    except Exception as e:
        return jsonify({'error': f'生成大纲失败: {str(e)}'}), 500
    meta['outline'] = outline
    meta['updated_at'] = datetime.now().isoformat()
    save_paper(paper_id, meta)
    return jsonify({'outline': outline})

@app.route('/api/papers/<paper_id>/guide', methods=['POST'])
@require_auth()
def paper_guide(paper_id):
    meta = load_paper(paper_id)
    if not meta:
        return jsonify({'error': '论文项目不存在'}), 404
    data = request.get_json() or {}
    user_msg = (data.get('message') or '').strip()
    if not user_msg:
        return jsonify({'error': '消息不能为空'}), 400
    msgs = meta.get('guide_messages', [])
    msgs.append({'role': 'user', 'content': user_msg})
    # Build LLM messages
    llm_msgs = [{'role': 'system', 'content': PAPER_GUIDE_SYSTEM}]
    for m in msgs:
        llm_msgs.append({'role': m['role'], 'content': m['content']})
    # Auto-suggest outline after enough messages
    if len([m for m in msgs if m['role'] == 'user']) >= 5:
        llm_msgs.append({
            'role': 'system',
            'content': (
                '用户已提供了较多信息。请在回答后附带一段大纲建议，'
                '用 <OUTLINE>...</OUTLINE> 标签包裹。'
            )
        })
    try:
        reply = call_llm(llm_msgs, timeout=90, prefer_cloud=True)
    except Exception as e:
        return jsonify({'error': f'AI回复失败: {str(e)}'}), 500
    # Extract auto-outline if present
    auto_outline = ''
    if '<OUTLINE>' in reply and '</OUTLINE>' in reply:
        import re as _re
        m = _re.search(r'<OUTLINE>(.*?)</OUTLINE>', reply, _re.DOTALL)
        if m:
            auto_outline = m.group(1).strip()
            reply = reply[:m.start()] + reply[m.end():]
            reply = reply.strip()
    msgs.append({'role': 'assistant', 'content': reply})
    meta['guide_messages'] = msgs
    meta['updated_at'] = datetime.now().isoformat()
    if auto_outline:
        meta['outline'] = auto_outline
    save_paper(paper_id, meta)
    return jsonify({'reply': reply, 'outline': auto_outline, 'messages': msgs})


@app.route('/api/papers/<paper_id>/parse-outline', methods=['POST'])
@require_auth()
def parse_paper_outline(paper_id):
    """解析大纲，返回章节列表"""
    meta = load_paper(paper_id)
    if not meta:
        return jsonify({'error': '论文项目不存在'}), 404
    outline = meta.get('outline', '')
    if not outline:
        return jsonify({'error': '大纲为空'}), 400
    # Parse markdown headings (## and ### level)
    sections = []
    for line in outline.split('\n'):
        stripped = line.strip()
        if stripped.startswith('## ') and not stripped.startswith('### '):
            sections.append({
                'index': len(sections),
                'title': stripped[3:].strip(),
                'level': 2
            })
        elif stripped.startswith('### '):
            sections.append({
                'index': len(sections),
                'title': stripped[4:].strip(),
                'level': 3
            })
    return jsonify({'sections': sections})


@app.route('/api/papers/<paper_id>/generate-section', methods=['POST'])
@require_auth()
def generate_paper_section(paper_id):
    """[DEPRECATED] 论文章节生成 — 前端已改用 Agent 模式。保留作为兼容。"""
    """生成指定章节内容"""
    meta = load_paper(paper_id)
    if not meta:
        return jsonify({'error': '论文项目不存在'}), 404
    data = request.get_json() or {}
    section_title = (data.get('section_title') or '').strip()
    section_index = data.get('section_index', 0)
    outline = meta.get('outline', '')
    if not outline:
        return jsonify({'error': '请先生成大纲'}), 400

    # Build context
    title = meta.get('title', '')
    desc = meta.get('description', '')
    guide_context = ''
    for m in meta.get('guide_messages', []):
        if m['role'] == 'user':
            guide_context += f"用户: {m['content']}\n"

    # Get previously generated sections for context
    sections = meta.get('sections', {})
    prev_sections = ''
    for key in sorted(sections.keys()):
        s = sections[key]
        if s.get('content'):
            prev_sections += f"\n### {s['title']}\n{s['content'][:500]}...\n"

    prompt = (
        f"你正在帮用户撰写学术论文「{title}」。\n"
        f"描述: {desc or '无'}\n"
        f"完整的论文大纲:\n{outline}\n\n"
        f"{'已生成的前序章节摘要:' + prev_sections if prev_sections else ''}\n"
        f"{'用户提供的上下文:' + guide_context if guide_context else ''}\n"
        f"请撰写以下章节的完整内容:\n**{section_title}**\n\n"
        f"要求:\n"
        f"1. 学术论文风格，用中文撰写\n"
        f"2. 内容详细充实，800-1500字\n"
        f"3. 与大纲其他部分保持连贯\n"
        f"4. 如有相关研究可以引用"
    )

    messages = [
        {'role': 'system', 'content': '你是一个学术论文撰写助手，擅长撰写高质量的学术论文各章节。用中文回复。'},
        {'role': 'user', 'content': prompt}
    ]

    try:
        content = call_llm(messages, timeout=120, prefer_cloud=True)
    except Exception as e:
        return jsonify({'error': f'生成失败: {str(e)}'}), 500

    # Save generated section
    _safe_title = re.sub(r'[^a-zA-Z0-9\u4e00-\u9fff]', '_', section_title)[:30]
    section_key = f"{section_index}-{_safe_title}"
    if 'sections' not in meta:
        meta['sections'] = {}
    meta['sections'][section_key] = {
        'title': section_title,
        'content': content,
        'status': 'draft',
        'generated_at': datetime.now().isoformat()
    }
    meta['updated_at'] = datetime.now().isoformat()
    save_paper(paper_id, meta)

    return jsonify({
        'section_key': section_key,
        'title': section_title,
        'content': content,
        'sections': meta['sections']
    })


# ============================================================
# 文档修改模块 (DocMod)
# ============================================================
DOCMOD_DIR = os.path.join(CONFIG["base_dir"], "docmod")
os.makedirs(DOCMOD_DIR, exist_ok=True)

DOCMOD_ALLOWED_EXT = {'md', 'pdf', 'doc', 'docx'}

# 文档修改相关的 in-memory 会话注册（使用独立前缀避免与 Agent 会话冲突）
_docmod_sessions = {}
_docmod_lock = threading.Lock()


def _get_docmod_user_dir():
    """获取当前用户的文档修改目录"""
    username = getattr(g, 'user', 'admin')
    d = os.path.join(DOCMOD_DIR, username)
    os.makedirs(d, exist_ok=True)
    return d


def _get_docmod_doc_dir(doc_id):
    """获取指定文档的目录"""
    d = os.path.join(_get_docmod_user_dir(), doc_id)
    return d


def _parse_doc_file(filepath, ext):
    """解析文档为纯文本"""
    if ext == 'md':
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            return f.read()
    elif ext == 'pdf':
        try:
            import fitz
            doc = fitz.open(filepath)
            text = "".join(page.get_text() for page in doc)
            doc.close()
            return text.encode("utf-8", errors="replace").decode("utf-8")
        except Exception as e:
            logger.error(f"[DocMod] PDF parse failed: {e}")
            return ""
    elif ext in ('doc', 'docx'):
        try:
            import tempfile
            tmp_dir = tempfile.mkdtemp()
            result = subprocess.run(
                ['libreoffice', '--headless', '--convert-to', 'txt:Text', filepath],
                cwd=tmp_dir, timeout=60, capture_output=True, text=True
            )
            txt_file = os.path.join(tmp_dir, os.path.splitext(os.path.basename(filepath))[0] + '.txt')
            text = ""
            if os.path.exists(txt_file):
                with open(txt_file, 'r', encoding='utf-8', errors='ignore') as f:
                    text = f.read()
            shutil.rmtree(tmp_dir, ignore_errors=True)
            return text
        except Exception as e:
            logger.error(f"[DocMod] DOC/DOCX parse failed: {e}")
            return ""
    return ""


@app.route('/api/docmod/upload', methods=['POST'])
@require_auth()
def docmod_upload():
    """上传文档用于修改"""
    if 'file' not in request.files:
        return jsonify({'error': '未提供文件'}), 400
    file = request.files['file']
    if not file.filename:
        return jsonify({'error': '文件名为空'}), 400

    ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
    if ext not in DOCMOD_ALLOWED_EXT:
        return jsonify({'error': f'不支持的文件格式: {ext}，仅支持 {", ".join(DOCMOD_ALLOWED_EXT)}'}), 400

    doc_id = str(uuid.uuid4())[:8]
    doc_dir = _get_docmod_doc_dir(doc_id)
    os.makedirs(doc_dir, exist_ok=True)

    # 保存原始文件
    original_path = os.path.join(doc_dir, f'original.{ext}')
    file.save(original_path)

    # 解析为文本
    text = _parse_doc_file(original_path, ext)
    if not text or len(text.strip()) < 5:
        shutil.rmtree(doc_dir, ignore_errors=True)
        return jsonify({'error': '文档解析失败或内容为空'}), 400

    # 保存解析后的文本
    content_path = os.path.join(doc_dir, 'content.md')
    with open(content_path, 'w', encoding='utf-8') as f:
        f.write(text)

    # 创建元数据
    now = datetime.now().isoformat()
    meta = {
        'id': doc_id,
        'filename': file.filename,
        'ext': ext,
        'status': '已上传',
        'upload_time': now,
        'updated_time': now
    }
    meta_path = os.path.join(doc_dir, 'meta.json')
    with open(meta_path, 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    # 创建空的消息历史
    messages_path = os.path.join(doc_dir, 'messages.json')
    with open(messages_path, 'w', encoding='utf-8') as f:
        json.dump([], f, ensure_ascii=False)

    return jsonify({
        'doc_id': doc_id,
        'filename': file.filename,
        'status': meta['status'],
        'text_length': len(text)
    })


@app.route('/api/docmod/list', methods=['GET'])
@require_auth()
def docmod_list():
    """获取文档修改项目列表"""
    user_dir = _get_docmod_user_dir()
    docs = []
    if os.path.exists(user_dir):
        for name in os.listdir(user_dir):
            doc_dir = os.path.join(user_dir, name)
            meta_path = os.path.join(doc_dir, 'meta.json')
            if os.path.isdir(doc_dir) and os.path.exists(meta_path):
                try:
                    with open(meta_path, 'r', encoding='utf-8') as f:
                        meta = json.load(f)
                    docs.append(meta)
                except:
                    pass
    docs.sort(key=lambda x: x.get('updated_time', ''), reverse=True)
    return jsonify(docs)


@app.route('/api/docmod/<doc_id>', methods=['GET'])
@require_auth()
def docmod_get(doc_id):
    """获取文档详情：元数据、原始内容、修改后内容、对话历史"""
    doc_dir = _get_docmod_doc_dir(doc_id)
    meta_path = os.path.join(doc_dir, 'meta.json')
    if not os.path.exists(meta_path):
        return jsonify({'error': '文档不存在'}), 404

    with open(meta_path, 'r', encoding='utf-8') as f:
        meta = json.load(f)

    content_path = os.path.join(doc_dir, 'content.md')
    content = ''
    if os.path.exists(content_path):
        with open(content_path, 'r', encoding='utf-8') as f:
            content = f.read()

    modified_path = os.path.join(doc_dir, 'modified.md')
    modified_content = ''
    if os.path.exists(modified_path):
        with open(modified_path, 'r', encoding='utf-8') as f:
            modified_content = f.read()

    messages_path = os.path.join(doc_dir, 'messages.json')
    messages = []
    if os.path.exists(messages_path):
        with open(messages_path, 'r', encoding='utf-8') as f:
            messages = json.load(f)

    return jsonify({
        'meta': meta,
        'content': content,
        'modified_content': modified_content,
        'messages': messages
    })


@app.route('/api/docmod/<doc_id>', methods=['DELETE'])
@require_auth()
def docmod_delete(doc_id):
    """删除文档修改项目"""
    doc_dir = _get_docmod_doc_dir(doc_id)
    if not os.path.exists(doc_dir):
        return jsonify({'error': '文档不存在'}), 404
    shutil.rmtree(doc_dir)
    return jsonify({'success': True})


@app.route('/api/docmod/<doc_id>/chat', methods=['POST'])
@require_auth()
def docmod_chat(doc_id):
    """文档修改交互对话 - 启动 Claude Code 子进程处理修改需求"""
    doc_dir = _get_docmod_doc_dir(doc_id)
    meta_path = os.path.join(doc_dir, 'meta.json')
    if not os.path.exists(meta_path):
        return jsonify({'error': '文档不存在'}), 404

    data = request.get_json(force=True)
    message = (data.get('message') or '').strip()
    kb = data.get('kb', os.getenv('RAG_KB_NAME', 'papers'))
    if not message:
        return jsonify({'error': '消息不能为空'}), 400

    # 读取当前文档内容（优先修改后版本）
    modified_path = os.path.join(doc_dir, 'modified.md')
    content_path = os.path.join(doc_dir, 'content.md')
    current_content = ''
    if os.path.exists(modified_path):
        with open(modified_path, 'r', encoding='utf-8') as f:
            current_content = f.read()
    elif os.path.exists(content_path):
        with open(content_path, 'r', encoding='utf-8') as f:
            current_content = f.read()

    # 保存用户消息到历史
    messages_path = os.path.join(doc_dir, 'messages.json')
    messages = []
    if os.path.exists(messages_path):
        with open(messages_path, 'r', encoding='utf-8') as f:
            messages = json.load(f)
    messages.append({
        'role': 'user',
        'content': message,
        'time': datetime.now().isoformat()
    })
    with open(messages_path, 'w', encoding='utf-8') as f:
        json.dump(messages, f, ensure_ascii=False, indent=2)

    # 更新状态
    with open(meta_path, 'r', encoding='utf-8') as f:
        meta = json.load(f)
    meta['status'] = '修改中'
    meta['updated_time'] = datetime.now().isoformat()
    with open(meta_path, 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    # 构建 Claude Code session id（必须是合法 UUID，用 docmod 前缀 + doc_id 补齐为 UUID v4 格式）
    # doc_id 是 uuid[:8]，补齐为完整 UUID: docmodxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx
    _d = doc_id.replace('-', '')
    session_id = f"{_d[:8]}-d0c0-4d0c-{_d[4:8].ljust(4,'0')}-{_d.ljust(12,'0')}"

    # 检查是否已有历史会话
    session_file = os.path.join(_user_agent_dir(), f"{session_id}.json")
    has_history = os.path.exists(session_file)
    try:
        if has_history:
            existing = json.loads(open(session_file, encoding="utf-8").read())
            has_history = existing.get("claude_registered", False)
    except:
        has_history = False

    # 创建输出队列
    out_queue = queue.Queue()
    akey = _agent_session_key(session_id)
    with _agent_lock:
        if akey not in _agent_sessions:
            _agent_sessions[akey] = {"process": None, "queue": None, "status": "idle"}
        _agent_sessions[akey]["queue"] = out_queue
        _agent_sessions[akey]["status"] = "running"

    # 构建提示词 — 直接给 Agent 用户输入和文档内容，Agent 自主决定是否查询 RAG
    doc_context = (
        f"当前文档内容（修改后版本）：\n"
        f"---BEGIN_DOC---\n{current_content}\n---END_DOC---\n\n"
    )
    task_instruction = (
        f"用户的修改需求：{message}\n\n"
        f"修改完成后，请将完整的修改后文档放在 <MODIFIED_DOC>...</MODIFIED_DOC> 标签中。\n"
        f"同时在标签外给出修改说明。\n\n"
        f"你可以自主决定是否需要查询 RAG 知识库来辅助修改（如需要引用相关论文或技术资料时）。"
    )
    if not has_history:
        prompt = f"[当前知识库: {kb}]\n\n{doc_context}{task_instruction}"
    else:
        prompt = f"{doc_context}{task_instruction}"

    # 启动 Claude Code 子进程
    _dm_user = getattr(g, 'user', 'admin')
    t = threading.Thread(target=_run_claude, args=(session_id, prompt, out_queue, has_history, _dm_user), daemon=True)
    t.start()

    return jsonify({'success': True, 'session_id': session_id})


@app.route('/api/docmod/<doc_id>/stream/<session_id>', methods=['GET'])
def docmod_stream(doc_id, session_id):
    """文档修改 SSE 流式端点"""
    # 认证：支持 query param 和 header
    token = request.args.get("token", "")
    if not token:
        auth_header = request.headers.get("Authorization", "")
        token = auth_header.replace("Bearer ", "") if auth_header.startswith("Bearer ") else ""

    payload = verify_jwt(token)
    if payload:
        username = payload['username']
    elif token == CONFIG["auth_code"]:
        username = 'admin'
    else:
        return jsonify({"error": "Unauthorized"}), 401

    akey = _agent_session_key_for(username, session_id)

    with _agent_lock:
        sess = _agent_sessions.get(akey)
    if not sess or not sess.get("queue"):
        return jsonify({"error": "No active stream"}), 404

    q = sess["queue"]

    def generate():
        doc_dir = os.path.join(DOCMOD_DIR, username, doc_id)
        assistant_text = ""
        while True:
            try:
                item = q.get(timeout=120)
            except queue.Empty:
                yield f"data: {json.dumps({'type': 'heartbeat'})}\n\n"
                continue
            yield f"data: {item}\n\n"

            try:
                parsed = json.loads(item)
                ptype = parsed.get("type", "")

                # 收集 assistant 文本
                if ptype == "assistant":
                    msg = parsed.get("message", {})
                    for c in (msg.get("content") or []):
                        if c.get("type") == "text":
                            assistant_text += c.get("text", "")

                if ptype in ("result", "done"):
                    # 尝试提取 <MODIFIED_DOC> 标签内容
                    final_text = parsed.get("result", "") or assistant_text
                    mod_match = re.search(r'<MODIFIED_DOC>(.*?)</MODIFIED_DOC>', final_text, re.DOTALL)
                    if mod_match:
                        modified_content = mod_match.group(1).strip()
                        modified_path = os.path.join(doc_dir, 'modified.md')
                        with open(modified_path, 'w', encoding='utf-8') as f:
                            f.write(modified_content)

                        # 保存 assistant 消息到历史
                        messages_path = os.path.join(doc_dir, 'messages.json')
                        messages = []
                        if os.path.exists(messages_path):
                            with open(messages_path, 'r', encoding='utf-8') as f:
                                messages = json.load(f)
                        # 提取修改说明（标签外内容）
                        explanation = re.sub(r'<MODIFIED_DOC>.*?</MODIFIED_DOC>', '', final_text, flags=re.DOTALL).strip()
                        messages.append({
                            'role': 'assistant',
                            'content': explanation or final_text,
                            'time': datetime.now().isoformat(),
                            'modified': True
                        })
                        with open(messages_path, 'w', encoding='utf-8') as f:
                            json.dump(messages, f, ensure_ascii=False, indent=2)

                        # 更新元数据状态
                        meta_path = os.path.join(doc_dir, 'meta.json')
                        if os.path.exists(meta_path):
                            with open(meta_path, 'r', encoding='utf-8') as f:
                                meta = json.load(f)
                            meta['status'] = '已修改'
                            meta['updated_time'] = datetime.now().isoformat()
                            with open(meta_path, 'w', encoding='utf-8') as f:
                                json.dump(meta, f, ensure_ascii=False, indent=2)

                        # 通知前端文档已更新
                        yield f"data: {json.dumps({'type': 'doc_updated', 'doc_id': doc_id})}\n\n"

                    if ptype == "done":
                        break

                if ptype == "error":
                    break
            except Exception as e:
                logger.error(f"[DocMod] stream parse error: {e}")

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route('/api/docmod/<doc_id>/export', methods=['GET'])
def docmod_export(doc_id):
    """导出修改后的文档。Supports Authorization header and ?token= for window.open downloads."""
    token = request.args.get('token', '')
    if not token:
        auth_header = request.headers.get('Authorization', '')
        token = auth_header[7:] if auth_header.startswith('Bearer ') else ''
    payload = verify_jwt(token)
    if not payload:
        return jsonify({'error': 'Unauthorized'}), 401
    g.user = payload['username']
    g.role = payload['role']

    doc_dir = _get_docmod_doc_dir(doc_id)
    meta_path = os.path.join(doc_dir, 'meta.json')
    if not os.path.exists(meta_path):
        return jsonify({'error': '文档不存在'}), 404

    fmt = request.args.get('format', 'md')
    modified_path = os.path.join(doc_dir, 'modified.md')
    content_path = os.path.join(doc_dir, 'content.md')

    # 优先导出修改后版本
    export_path = modified_path if os.path.exists(modified_path) else content_path
    if not os.path.exists(export_path):
        return jsonify({'error': '无内容可导出'}), 404

    with open(meta_path, 'r', encoding='utf-8') as f:
        meta = json.load(f)
    filename = meta.get('filename', doc_id)
    with open(content_path, 'r', encoding='utf-8') as f:
        original_content = f.read()
    with open(export_path, 'r', encoding='utf-8') as f:
        modified_content = f.read()
    diff_actions = _compute_docmod_diff(original_content, modified_content)
    base_name = os.path.splitext(filename)[0]

    if fmt == 'md':
        content = _docmod_diff_to_markdown(diff_actions, base_name)
        download_name = f"{base_name}_diff.md"
        return Response(
            content,
            mimetype='text/markdown; charset=utf-8',
            headers=_download_headers(download_name)
        )
    elif fmt == 'pdf':
        # Diff HTML -> PDF, preserving green additions and red strikethrough deletions.
        try:
            html_full = _docmod_diff_to_html(diff_actions, base_name)

            import tempfile
            tmp_dir = tempfile.mkdtemp(prefix='docmod_export_')
            tmp_html = os.path.join(tmp_dir, 'docmod_export.html')
            tmp_pdf = os.path.join(tmp_dir, 'docmod_export.pdf')
            with open(tmp_html, 'w', encoding='utf-8') as f:
                f.write(html_full)
            result = subprocess.run(
                ['libreoffice', '--headless', '--convert-to', 'pdf', '--outdir', tmp_dir, tmp_html],
                timeout=60, capture_output=True, text=True
            )
            if os.path.exists(tmp_pdf):
                with open(tmp_pdf, 'rb') as f:
                    pdf_data = f.read()
                shutil.rmtree(tmp_dir, ignore_errors=True)
                download_name = f"{base_name}_diff.pdf"
                return Response(
                    pdf_data,
                    mimetype='application/pdf',
                    headers=_download_headers(download_name)
                )
            else:
                err = (result.stderr or result.stdout or 'PDF 转换未生成输出文件').strip()
                shutil.rmtree(tmp_dir, ignore_errors=True)
                return jsonify({'error': f'PDF 转换失败: {err}'}), 500
        except Exception as e:
            return jsonify({'error': f'导出 PDF 失败: {str(e)}'}), 500
    else:
        return jsonify({'error': f'不支持的格式: {fmt}'}), 400


# ---- Admin: Usage Stats ----
@app.route('/api/admin/usage-stats', methods=['GET'])
@require_auth(roles=['admin'])
def get_usage_stats():
    """Get usage statistics for all users. Admin only."""
    _save_usage()
    # Compute per-category summaries per user
    user_category_summary = {}
    for user, endpoints in _usage_data.items():
        user_category_summary[user] = {}
        for cat_name, cat_endpoints in ENDPOINT_CATEGORIES.items():
            total = sum(endpoints.get(ep, 0) for ep in cat_endpoints)
            user_category_summary[user][cat_name] = total
    return jsonify({
        'success': True,
        'usage': _usage_data,
        'users': list(_usage_data.keys()),
        'total_requests': sum(sum(v.values()) for v in _usage_data.values()),
        'categories': ENDPOINT_CATEGORIES,
        'user_category_summary': user_category_summary,
    })

@app.route('/api/admin/usage-stats/reset', methods=['POST'])
@require_auth(roles=['admin'])
def reset_usage_stats():
    """Reset all usage statistics. Admin only."""
    global _usage_data
    with _usage_lock:
        _usage_data = {}
        _save_usage()
    return jsonify({'success': True, 'message': '统计数据已重置'})


if __name__ == "__main__":
    os.makedirs(CONFIG["upload_dir"], exist_ok=True)
    
    # ---- Data migration ----
    # Migrate old chat_sessions/ and agent_sessions/ to user_data/admin/
    admin_chat_dir = os.path.join(USER_DATA_DIR, 'admin', 'chat_sessions')
    admin_agent_dir = os.path.join(USER_DATA_DIR, 'admin', 'agent_sessions')
    os.makedirs(admin_chat_dir, exist_ok=True)
    os.makedirs(admin_agent_dir, exist_ok=True)
    os.makedirs(os.path.join(USER_DATA_DIR, 'admin', 'papers'), exist_ok=True)
    
    old_chat_dir = CONFIG['session_dir']
    if os.path.exists(old_chat_dir) and os.path.isdir(old_chat_dir):
        for fn in os.listdir(old_chat_dir):
            if fn.endswith('.json'):
                src = os.path.join(old_chat_dir, fn)
                dst = os.path.join(admin_chat_dir, fn)
                if not os.path.exists(dst):
                    shutil.move(src, dst)
                    logger.info(f"[Migration] Moved {fn} -> user_data/admin/chat_sessions/")
    
    old_agent_dir = AGENT_SESSIONS_DIR
    if os.path.exists(old_agent_dir) and os.path.isdir(old_agent_dir):
        for fn in os.listdir(old_agent_dir):
            if fn.endswith('.json'):
                src = os.path.join(old_agent_dir, fn)
                dst = os.path.join(admin_agent_dir, fn)
                if not os.path.exists(dst):
                    shutil.move(src, dst)
                    logger.info(f"[Migration] Moved {fn} -> user_data/admin/agent_sessions/")
    
    # Ensure users.json exists with default admin
    load_users()

    # Save usage stats on exit
    atexit.register(_save_usage)

    print(f"RAG Web UI | Embedding: {CONFIG['embedding_model']} | Chat: {CONFIG['chat_model']}")
    app.run(host=os.getenv('RAG_HOST', '0.0.0.0'), port=int(os.getenv('RAG_PORT', '10663')), debug=os.getenv('RAG_DEBUG', '0') == '1')


