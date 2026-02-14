"""
Haber Takip Pro - Google News Tarayıcı
Flask tabanlı haber takip sistemi.
Anahtar kelimeleri Google News'te tarar ve yeni haberleri listeler.
"""

from flask import Flask, jsonify, render_template, request
from apscheduler.schedulers.background import BackgroundScheduler
import feedparser
import urllib.par
import time
import json
import os
from datetime import datetime, timedelta
from threading import Lock

app = Flask(__name__)

# ==================== VERİ DEPOSU ====================
DATA_FILE = 'data.json'
data_lock = Lock()

def default_data():
    return {
        'keywords': [
            'kimdir', 'ne zaman', 'neden', 'sevgilisi', 'hamile',
            'yeni sezon', 'serveti', 'nerede', 'nedir', 'deprem',
            'ayrıldı', 'temettü', 'hisse', 'çekiliş', 'babası',
            'annesi', 'yorumlar', 'toki', 'tatil'
        ],
        'news': [],
        'saved_ids': [],
        'scan_count': 0,
        'last_scan_time': None,
        'auto_scan': True,
        'interval_minutes': 5,
        'seen_urls': []
    }

def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    return default_data()

def save_data(data):
    with data_lock:
        # Haberleri 1000 ile sınırla
        data['news'] = data['news'][:1000]
        data['seen_urls'] = data['seen_urls'][-5000:]
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

# ==================== GOOGLE NEWS TARAMA ====================

def scan_keyword(keyword, seen_urls):
    """Tek bir anahtar kelimeyi Google News RSS'ten tara"""
    url = f'https://news.google.com/rss/search?q={urllib.parse.quote(keyword)}&hl=tr&gl=TR&ceid=TR:tr'
    try:
        feed = feedparser.parse(url)
        results = []
        for entry in feed.entries[:50]:
            link = entry.get('link', '')
            if not link or link in seen_urls:
                continue

            # Başlıktan kaynak adını ayır
            title_full = entry.get('title', '')
            parts = title_full.rsplit(' - ', 1)
            title = parts[0].strip() if parts else title_full
            source = parts[1].strip() if len(parts) > 1 else 'Bilinmeyen'

            # Yayın tarihi
            pub_date = entry.get('published', '')
            try:
                pub_struct = entry.get('published_parsed')
                if pub_struct:
                    pub_timestamp = time.mktime(pub_struct)
                else:
                    pub_timestamp = time.time()
            except:
                pub_timestamp = time.time()

            results.append({
                'id': f'{hash(link)}_{int(time.time()*1000)}',
                'title': title,
                'url': link,
                'source': source,
                'pub_date': pub_date,
                'pub_timestamp': pub_timestamp,
                'keyword': keyword,
                'is_new': True,
                'found_at': datetime.now().isoformat()
            })
        return results
    except Exception as e:
        print(f'[HATA] "{keyword}" taraması başarısız: {e}')
        return []

def run_scan():
    """Tüm anahtar kelimeleri tara"""
    data = load_data()
    seen_urls = set(data.get('seen_urls', []))

    # Eski haberlerin "new" işaretini kaldır
    for n in data['news']:
        n['is_new'] = False

    all_new = []
    for keyword in data['keywords']:
        results = scan_keyword(keyword, seen_urls)
        all_new.extend(results)
        time.sleep(0.5)  # Rate limiting

    # Yeni haberleri tarihe göre sırala (en yeni en üstte)
    all_new.sort(key=lambda x: x.get('pub_timestamp', 0), reverse=True)

    # Yeni URL'leri ekle
    for n in all_new:
        seen_urls.add(n['url'])

    # Haberleri güncelle
    data['news'] = all_new + data['news']
    data['news'] = data['news'][:1000]
    data['seen_urls'] = list(seen_urls)
    data['scan_count'] = data.get('scan_count', 0) + 1
    data['last_scan_time'] = datetime.now().isoformat()
    save_data(data)

    print(f'[TARAMA] {len(all_new)} yeni haber bulundu. Toplam: {len(data["news"])}')
    return len(all_new)

# ==================== ZAMANLAYICI ====================
scheduler = BackgroundScheduler()

def setup_scheduler():
    data = load_data()
    interval = data.get('interval_minutes', 10)
    # Mevcut job'ları temizle
    scheduler.remove_all_jobs()
    if data.get('auto_scan', True):
        scheduler.add_job(
            run_scan,
            'interval',
            minutes=interval,
            id='auto_scan',
            replace_existing=True
        )
        print(f'[ZAMANLAYICI] Otomatik tarama aktif: her {interval} dakikada bir')
    if not scheduler.running:
        scheduler.start()

# ==================== API ROUTES ====================

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/status')
def get_status():
    data = load_data()
    new_count = sum(1 for n in data['news'] if n.get('is_new'))
    return jsonify({
        'total_news': len(data['news']),
        'new_count': new_count,
        'scan_count': data.get('scan_count', 0),
        'saved_count': len(data.get('saved_ids', [])),
        'keyword_count': len(data['keywords']),
        'last_scan_time': data.get('last_scan_time'),
        'auto_scan': data.get('auto_scan', False),
        'interval_minutes': data.get('interval_minutes', 10),
        'is_scanning': False
    })

@app.route('/api/news')
def get_news():
    data = load_data()
    filter_type = request.args.get('filter', 'all')
    keyword_filter = request.args.get('keyword', '')
    limit = int(request.args.get('limit', 100))

    news = data['news']

    if filter_type == 'new':
        news = [n for n in news if n.get('is_new')]
    elif filter_type == 'saved':
        saved = set(data.get('saved_ids', []))
        news = [n for n in news if n['id'] in saved]

    if keyword_filter:
        news = [n for n in news if n.get('keyword') == keyword_filter]

    return jsonify({
        'news': news[:limit],
        'total': len(news)
    })

@app.route('/api/keywords')
def get_keywords():
    data = load_data()
    # Her kelime için haber sayısı
    counts = {}
    for n in data['news']:
        kw = n.get('keyword', '')
        counts[kw] = counts.get(kw, 0) + 1

    keywords = [{'name': kw, 'count': counts.get(kw, 0)} for kw in data['keywords']]
    return jsonify({'keywords': keywords})

@app.route('/api/keywords', methods=['POST'])
def add_keyword():
    kw = request.json.get('keyword', '').strip().lower()
    if not kw:
        return jsonify({'error': 'Kelime boş olamaz'}), 400
    data = load_data()
    if kw in data['keywords']:
        return jsonify({'error': 'Bu kelime zaten ekli'}), 400
    data['keywords'].append(kw)
    save_data(data)
    return jsonify({'success': True, 'keyword': kw})

@app.route('/api/keywords/<keyword>', methods=['DELETE'])
def remove_keyword(keyword):
    data = load_data()
    data['keywords'] = [k for k in data['keywords'] if k != keyword]
    save_data(data)
    return jsonify({'success': True})

@app.route('/api/scan', methods=['POST'])
def trigger_scan():
    count = run_scan()
    return jsonify({'success': True, 'new_count': count})

@app.route('/api/save/<news_id>', methods=['POST'])
def toggle_save(news_id):
    data = load_data()
    saved = set(data.get('saved_ids', []))
    if news_id in saved:
        saved.discard(news_id)
        action = 'removed'
    else:
        saved.add(news_id)
        action = 'saved'
    data['saved_ids'] = list(saved)
    save_data(data)
    return jsonify({'success': True, 'action': action})

@app.route('/api/settings', methods=['POST'])
def update_settings():
    data = load_data()
    body = request.json
    if 'auto_scan' in body:
        data['auto_scan'] = body['auto_scan']
    if 'interval_minutes' in body:
        data['interval_minutes'] = body['interval_minutes']
    save_data(data)
    setup_scheduler()
    return jsonify({'success': True})

# ==================== BAŞLAT ====================
# Gunicorn ve dogrudan calistirma icin baslat
if not os.path.exists(DATA_FILE):
    save_data(default_data())

setup_scheduler()

if __name__ == '__main__':
    app.run(debug=True, port=5000, use_reloader=False)
