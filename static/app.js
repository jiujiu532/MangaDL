/* MangaDL v3 — Frontend */

const $ = s => document.querySelector(s);
const $$ = s => document.querySelectorAll(s);
let currentManga = null, sortAsc = true, chapterFilter = 'all', dlPoll = null;

// Nav
let _navHistory = ['search'];   // 导航历史栈
$$('.nav-btn').forEach(b => b.onclick = () => navigate(b.dataset.page));
function navigate(p, skipPush) {
    $$('.nav-btn').forEach(b => b.classList.toggle('active', b.dataset.page === p));
    $$('.page').forEach(pg => pg.classList.toggle('active', pg.id === `page-${p}`));
    if (p === 'favorites') loadFavorites();
    if (p === 'popular') loadPopular();
    if (p === 'latest') loadLatest();
    if (p === 'downloads') startPoll(); else stopPoll();
    if (p === 'settings') loadConfig();
    if (!skipPush) {
        _navHistory.push(p);
        history.pushState({ page: p }, '', '#' + p);
    }
}
// 鼠标侧键 / 浏览器后退
window.addEventListener('popstate', () => {
    _navHistory.pop();
    const prev = _navHistory[_navHistory.length - 1] || 'search';
    navigate(prev, true);
});
// 页面加载时恢复hash对应的页面
(function restoreFromHash() {
    const hash = location.hash.replace('#', '');
    const validPages = ['search', 'popular', 'latest', 'favorites', 'downloads', 'settings'];
    if (hash && validPages.includes(hash)) {
        _navHistory = [hash];
        navigate(hash, true);
    } else if (hash === 'detail') {
        // 恢复详情页
        try {
            const saved = sessionStorage.getItem('lastDetailManga');
            if (saved) {
                const m = JSON.parse(saved);
                const readerState = sessionStorage.getItem('lastReaderChapter');
                // 如果之前在阅读器里, 立刻显示阅读器overlay, 避免闪烁详情页
                if (readerState) {
                    $('#readerOverlay').style.display = 'flex';
                    document.body.style.overflow = 'hidden';
                }
                openDetail(m).then(() => {
                    if (readerState) {
                        const rs = JSON.parse(readerState);
                        if (rs.url) openReader(rs.url, rs.title);
                    }
                });
            }
        } catch (e) { /* ignore */ }
    }
})();

// Custom Dropdown helper
function initDropdown(containerId, items, onSelect) {
    const wrap = $('#' + containerId);
    const trigger = wrap.querySelector('.dropdown-trigger');
    const menu = wrap.querySelector('.dropdown-menu');
    // Build items
    const allItem = { value: '', label: '全部来源' };
    const allItems = [allItem, ...items.map(s => ({ value: s.name, label: s.name }))];
    menu.innerHTML = allItems.map(it =>
        `<button type="button" class="dropdown-item${it.value === '' ? ' active' : ''}" data-value="${it.value}">${it.label}</button>`
    ).join('');
    // Toggle
    trigger.onclick = (e) => {
        e.stopPropagation();
        // Close all other dropdowns first
        $$('.dropdown.open').forEach(d => { if (d !== wrap) d.classList.remove('open'); });
        wrap.classList.toggle('open');
    };
    // Select item
    menu.querySelectorAll('.dropdown-item').forEach(btn => {
        btn.onclick = (e) => {
            e.stopPropagation();
            trigger.textContent = btn.textContent;
            trigger.dataset.value = btn.dataset.value;
            menu.querySelectorAll('.dropdown-item').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            wrap.classList.remove('open');
            if (onSelect) onSelect(btn.dataset.value);
        };
    });
    // Return getter
    return () => trigger.dataset.value;
}

// Close dropdowns on outside click
document.addEventListener('click', () => $$('.dropdown.open').forEach(d => d.classList.remove('open')));

let getSourceFilter, getPopularFilter, getLatestFilter;

// Init
(async () => {
    try {
        const src = await api('/api/sources');
        getSourceFilter = initDropdown('sourceFilterDropdown', src);
        getPopularFilter = initDropdown('popularSourceFilterDropdown', src, () => { _popularCache = {}; _popularPage = 1; loadPopular(1); });
        getLatestFilter = initDropdown('latestSourceFilterDropdown', src, () => { _latestCache = {}; _latestPage = 1; loadLatest(1); });
    } catch (e) {
        getSourceFilter = () => '';
        getPopularFilter = () => '';
        getLatestFilter = () => '';
    }
    try {
        const c = await api('/api/config');
        if (c.theme === 'dark') document.body.setAttribute('data-theme', 'dark');
        renderHistory(c.search_history || []);
    } catch (e) { }
    loadStats();
})();

async function loadStats() {
    try {
        const s = await api('/api/stats');
        const size = s.total_size_mb >= 1024 ? (s.total_size_mb / 1024).toFixed(1) + 'GB' : s.total_size_mb + 'MB';
        $('#navStats').textContent = `${s.manga_count} 漫画 · ${size} · ${s.favorites_count} 收藏`;
    } catch (e) { }
}
async function api(url, opts) { return (await fetch(url, opts)).json(); }

// ═══ SEARCH ═══
$('#searchBtn').onclick = doSearch;
$('#searchInput').onkeydown = e => { if (e.key === 'Enter') doSearch(); };

async function doSearch() {
    const kw = $('#searchInput').value.trim();
    if (!kw) return;
    $('#searchLoading').style.display = 'flex';
    $('#searchResults').innerHTML = '';
    try {
        const r = await api(`/api/search?q=${encodeURIComponent(kw)}&source=${encodeURIComponent(getSourceFilter ? getSourceFilter() : '')}`);
        renderResults(r);
        renderHistory((await api('/api/config')).search_history || []);
    } catch (e) { $('#searchResults').innerHTML = '<div class="empty"><p>搜索失败</p></div>'; }
    $('#searchLoading').style.display = 'none';
}

function renderHistory(items) {
    const el = $('#searchHistory'); el.innerHTML = '';
    items.slice(0, 8).forEach(h => {
        const b = document.createElement('button'); b.className = 'history-tag'; b.textContent = h;
        b.onclick = () => { $('#searchInput').value = h; doSearch(); }; el.appendChild(b);
    });
}

function proxyUrl(url) {
    if (!url || url.startsWith('data:') || url.startsWith('/')) return url;
    // Same-origin or localhost — no proxy needed
    if (url.startsWith(location.origin)) return url;
    // Always proxy (these CDNs block direct browser access)
    return `/api/img-proxy?url=${encodeURIComponent(url)}`;
}

function renderResults(results) {
    const g = $('#searchResults');
    if (!results.length) { g.innerHTML = '<div class="empty"><p>没有找到结果</p></div>'; return; }
    const placeholder = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 3 4'%3E%3Crect fill='%23f1f5f9' width='3' height='4'/%3E%3Ctext x='1.5' y='2.3' text-anchor='middle' font-size='.4' fill='%2394a3b8'%3EManga%3C/text%3E%3C/svg%3E";
    g.innerHTML = results.map((r, i) => `
    <div class="manga-card" data-i="${i}">
      <img src="${proxyUrl(r.cover) || placeholder}" alt="" loading="lazy" onerror="this.src='${placeholder}'">
      <div class="card-body">
        <div class="card-title">${esc(r.title)}</div>
        <span class="badge badge-source card-source">${esc(r._source || '')}</span>
      </div>
    </div>`).join('');
    g.querySelectorAll('.manga-card').forEach((c, i) => { c.onclick = () => openDetail(results[i]); });
}

function renderCardsTo(gridSel, results) {
    const g = $(gridSel);
    if (!results.length) { g.innerHTML = '<div class="empty"><p>没有找到结果</p></div>'; return; }
    const placeholder = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 3 4'%3E%3Crect fill='%23f1f5f9' width='3' height='4'/%3E%3Ctext x='1.5' y='2.3' text-anchor='middle' font-size='.4' fill='%2394a3b8'%3EManga%3C/text%3E%3C/svg%3E";
    g.innerHTML = results.map((r, i) => `
    <div class="manga-card" data-i="${i}">
      <img src="${proxyUrl(r.cover) || placeholder}" alt="" loading="lazy" onerror="this.src='${placeholder}'">
      <div class="card-body">
        <div class="card-title">${esc(r.title)}</div>
        <span class="badge badge-source card-source">${esc(r._source || '')}</span>
      </div>
    </div>`).join('');
    g.querySelectorAll('.manga-card').forEach((c, i) => { c.onclick = () => openDetail(results[i]); });
}

// ═══ POPULAR / LATEST (paginated) ═══
let _popularPage = 1, _latestPage = 1;
let _popularCache = {}, _latestCache = {};
let _popularTs = {}, _latestTs = {};
const _FRONT_CACHE_TTL = 300000;

async function loadPopular(page) {
    if (page !== undefined) _popularPage = page;
    const p = _popularPage;
    const now = Date.now();
    const src = getPopularFilter ? getPopularFilter() : '';
    const cacheKey = `${src}:${p}`;
    if (_popularCache[cacheKey] && (now - (_popularTs[cacheKey] || 0)) < _FRONT_CACHE_TTL) {
        renderCardsTo('#popularGrid', _popularCache[cacheKey].items);
        renderPager('popularPager', _popularCache[cacheKey], loadPopular);
        return;
    }
    $('#popularLoading').style.display = 'flex';
    $('#popularGrid').innerHTML = '';
    $('#popularPager').innerHTML = '';
    try {
        const r = await api(`/api/popular?source=${encodeURIComponent(src)}&page=${p}`);
        // 空页自动回退到最后有数据的页
        if ((!r.items || !r.items.length) && p > 1 && r.total_pages < p) {
            _popularPage = r.total_pages;
            loadPopular(_popularPage);
            return;
        }
        _popularCache[cacheKey] = r;
        _popularTs[cacheKey] = now;
        renderCardsTo('#popularGrid', r.items || []);
        renderPager('popularPager', r, loadPopular);
    } catch (e) { $('#popularGrid').innerHTML = '<div class="empty"><p>加载失败</p></div>'; }
    $('#popularLoading').style.display = 'none';
}

async function loadLatest(page) {
    if (page !== undefined) _latestPage = page;
    const p = _latestPage;
    const now = Date.now();
    const src = getLatestFilter ? getLatestFilter() : '';
    const cacheKey = `${src}:${p}`;
    if (_latestCache[cacheKey] && (now - (_latestTs[cacheKey] || 0)) < _FRONT_CACHE_TTL) {
        renderCardsTo('#latestGrid', _latestCache[cacheKey].items);
        renderPager('latestPager', _latestCache[cacheKey], loadLatest);
        return;
    }
    $('#latestLoading').style.display = 'flex';
    $('#latestGrid').innerHTML = '';
    $('#latestPager').innerHTML = '';
    try {
        const r = await api(`/api/latest?source=${encodeURIComponent(src)}&page=${p}`);
        // 空页自动回退到最后有数据的页
        if ((!r.items || !r.items.length) && p > 1 && r.total_pages < p) {
            _latestPage = r.total_pages;
            loadLatest(_latestPage);
            return;
        }
        _latestCache[cacheKey] = r;
        _latestTs[cacheKey] = now;
        renderCardsTo('#latestGrid', r.items || []);
        renderPager('latestPager', r, loadLatest);
    } catch (e) { $('#latestGrid').innerHTML = '<div class="empty"><p>加载失败</p></div>'; }
    $('#latestLoading').style.display = 'none';
}

function renderPager(containerId, data, loadFn) {
    const el = document.getElementById(containerId);
    if (!el) return;
    const cur = data.page || 1;
    const total = data.total_pages || 1;
    const hasNext = data.has_next;
    if (total <= 1 && !hasNext) { el.innerHTML = ''; return; }

    const totalLabel = hasNext && cur >= total ? `${total}+` : `${total}`;
    let html = `<span class="page-info">第 ${cur}/${totalLabel} 页</span>`;

    // Prev
    html += `<span class="page-btn${cur <= 1 ? ' disabled' : ''}" data-p="${cur - 1}">«</span>`;

    // Smart page numbers
    const pages = new Set();
    pages.add(1);
    pages.add(total);
    for (let i = Math.max(2, cur - 2); i <= Math.min(total - 1, cur + 2); i++) pages.add(i);
    const sorted = [...pages].sort((a, b) => a - b);

    let prev = 0;
    for (const p of sorted) {
        if (p - prev > 1) html += '<span class="page-dots">…</span>';
        html += `<span class="page-btn${p === cur ? ' active' : ''}" data-p="${p}">${p}</span>`;
        prev = p;
    }

    // Next — use has_next, not total
    html += `<span class="page-btn${!hasNext ? ' disabled' : ''}" data-p="${cur + 1}">»</span>`;

    // Jump
    html += `<span class="page-jump">跳转 <input type="number" min="1" value="${cur}"> 页 <button>GO</button></span>`;

    el.innerHTML = html;

    el.querySelectorAll('.page-btn').forEach(btn => {
        btn.onclick = () => {
            if (btn.classList.contains('disabled') || btn.classList.contains('active')) return;
            const p = parseInt(btn.dataset.p);
            if (p >= 1) { window.scrollTo({ top: 0, behavior: 'smooth' }); loadFn(p); }
        };
    });

    const jumpInput = el.querySelector('.page-jump input');
    const jumpBtn = el.querySelector('.page-jump button');
    const doJump = () => {
        let p = parseInt(jumpInput.value);
        if (p < 1) p = 1;
        if (!hasNext && p > total) p = total;
        if (p !== cur) { window.scrollTo({ top: 0, behavior: 'smooth' }); loadFn(p); }
    };
    jumpBtn.onclick = doJump;
    jumpInput.onkeydown = e => { if (e.key === 'Enter') doJump(); };
}

// ═══ DETAIL ═══
$('#backBtn').onclick = () => navigate('search');

async function openDetail(m) {
    const alreadyOnDetail = $('#page-detail').classList.contains('active');
    $$('.page').forEach(p => p.classList.remove('active'));
    $('#page-detail').classList.add('active');
    $$('.nav-btn').forEach(b => b.classList.remove('active'));
    if (alreadyOnDetail) {
        // 切换源: 替换当前历史，不新增
        history.replaceState({ page: 'detail' }, '', '#detail');
    } else {
        // 首次进入详情
        _navHistory.push('detail');
        history.pushState({ page: 'detail' }, '', '#detail');
    }
    $('#detailTitle').textContent = m.title;
    $('#detailCover').src = proxyUrl(m.cover) || '';
    $('#detailMeta').textContent = '加载中...';
    $('#chaptersGrid').innerHTML = '';
    $('#detailLoading').style.display = 'flex';
    chapterFilter = 'all';
    $$('.chapter-toolbar .toolbar-group:first-child .pill').forEach(p => p.classList.remove('active'));
    $('#filterAll').classList.add('active');
    try {
        const d = await api(`/api/detail?url=${encodeURIComponent(m.url)}&source=${encodeURIComponent(m._source || '')}`);
        currentManga = d;
        currentManga._url = m.url;
        currentManga._sourceObj = m;
        // 保存到sessionStorage以支持刷新恢复
        try { sessionStorage.setItem('lastDetailManga', JSON.stringify({ title: m.title, url: m.url, cover: m.cover, _source: m._source })); } catch (e) { }
        const info = d.info;
        let meta = [];
        if (info.author) meta.push('作者: ' + info.author);
        if (info.status) meta.push('状态: ' + info.status);
        if (info.genres) meta.push('标签: ' + info.genres);
        if (info.description) meta.push(info.description.substring(0, 200));
        $('#detailMeta').textContent = meta.join(' · ') || '暂无信息';
        renderChapters(d.chapters);
        const fav = await api(`/api/favorites/check?url=${encodeURIComponent(m.url)}`);
        $('#favBtn').textContent = fav.favorited ? '取消收藏' : '+ 收藏';
        $('#favBtn').onclick = () => toggleFav(m, fav.favorited);
        // 源站跳转按钮
        const srcBtn = $('#viewSourceBtn');
        srcBtn.href = m.url;
        srcBtn.textContent = `🔗 ${m._source || '源站'} ↗`;
        srcBtn.style.display = '';
        // 异步启动跨源检测 (章节数去重: RAW+翻译同章号只算一次)
        const uniqueChNums = new Set((d.chapters || []).map(c => { const m = c.title?.match(/(\d+(?:\.\d+)?)/); return m ? m[1] : c.title; }));
        loadCrossSource(m.title || d.info.title || '', d.source, uniqueChNums.size);
    } catch (e) { $('#detailMeta').textContent = '加载失败'; }
    $('#detailLoading').style.display = 'none';
}

function renderChapters(chapters) {
    let list = [...chapters];
    if (chapterFilter === 'translated') list = list.filter(c => !isRaw(c));
    else if (chapterFilter === 'raw') list = list.filter(c => isRaw(c));
    if (!sortAsc) list = list.reverse();
    const g = $('#chaptersGrid');
    $('#chapterCount').textContent = `${list.length} 章节`;
    g.innerHTML = list.map((ch, i) => {
        const raw = isRaw(ch);
        const num = parseNum(ch.title);
        const hasNum = ch.title.match(/\d/);
        const label = hasNum ? `#${String(Math.floor(num)).padStart(2, '0')}${num % 1 !== 0 ? '.' + String(num).split('.')[1] : ''}` : esc(ch.title);
        return `<div class="ch-item" data-i="${i}">
      <input type="checkbox" data-url="${escA(ch.url)}" data-title="${escA(ch.title)}">
      <span class="ch-label">${label}</span>
      ${raw ? '<span class="badge badge-raw">RAW</span>' : ''}
      <button class="ch-read-btn" data-url="${escA(ch.url)}" data-title="${escA(ch.title)}" title="在线阅读">📖</button>
    </div>`;
    }).join('');
    g.querySelectorAll('.ch-item').forEach(item => {
        item.onclick = e => { if (e.target.tagName === 'INPUT') return; const cb = item.querySelector('input'); cb.checked = !cb.checked; item.classList.toggle('selected', cb.checked); };
        item.querySelector('input').onchange = function () { item.classList.toggle('selected', this.checked); };
        const rb = item.querySelector('.ch-read-btn');
        if (rb) rb.onclick = e => { e.stopPropagation(); openReader(rb.dataset.url, rb.dataset.title); };
    });
}

function isRaw(ch) { return (ch.title || '').toLowerCase().includes('raw'); }
function parseNum(t) { const m = t.match(/(\d+(?:\.\d+)?)/); return m ? parseFloat(m[1]) : 0; }

$('#filterAll').onclick = () => setFilter('all');
$('#filterTranslated').onclick = () => setFilter('translated');
$('#filterRaw').onclick = () => setFilter('raw');
function setFilter(f) {
    chapterFilter = f;
    $$('.chapter-toolbar .toolbar-group:first-child .pill').forEach(p => p.classList.remove('active'));
    $({ all: '#filterAll', translated: '#filterTranslated', raw: '#filterRaw' }[f]).classList.add('active');
    if (currentManga) renderChapters(currentManga.chapters);
}
$('#sortToggle').onclick = () => { sortAsc = !sortAsc; $('#sortToggle').textContent = sortAsc ? '排序 ↑' : '排序 ↓'; if (currentManga) renderChapters(currentManga.chapters); };
$('#selectAll').onclick = () => checkAll(true);
$('#deselectAll').onclick = () => checkAll(false);
$('#invertSelect').onclick = () => { $$('#chaptersGrid input[type="checkbox"]').forEach(cb => { cb.checked = !cb.checked; cb.closest('.ch-item').classList.toggle('selected', cb.checked); }); };
$('#rangeSelect').onclick = () => {
    const f = parseInt(prompt('起始编号:')), t = parseInt(prompt('结束编号:'));
    if (isNaN(f) || isNaN(t)) return;
    $$('#chaptersGrid .ch-item').forEach(item => { const n = parseNum(item.querySelector('input').dataset.title); const s = n >= f && n <= t; item.querySelector('input').checked = s; item.classList.toggle('selected', s); });
};
function checkAll(v) { $$('#chaptersGrid input[type="checkbox"]').forEach(cb => { cb.checked = v; cb.closest('.ch-item').classList.toggle('selected', v); }); }

$('#downloadSelectedBtn').onclick = async () => {
    if (!currentManga) return;
    const sel = []; $$('#chaptersGrid input:checked').forEach(cb => sel.push({ url: cb.dataset.url, title: cb.dataset.title }));
    if (!sel.length) { alert('请先选择章节'); return; }
    await api('/api/download', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ chapters: sel, title: currentManga.info.title || 'Unknown', source: currentManga.source }) });
    navigate('downloads');
};

// ═══ 浏览器下载 (流式ZIP) ═══
$('#browserDownloadBtn').onclick = async () => {
    if (!currentManga) return;
    const sel = [];
    $$('#chaptersGrid input:checked').forEach(cb => sel.push({ url: cb.dataset.url, title: cb.dataset.title }));
    if (!sel.length) { alert('请先选择章节'); return; }

    const btn = $('#browserDownloadBtn');
    const origText = btn.textContent;
    btn.disabled = true;
    btn.textContent = '⏳ 打包中...';
    btn.classList.add('downloading');

    try {
        const resp = await fetch('/api/download/zip', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                chapters: sel,
                title: currentManga.info.title || 'Unknown',
                source: currentManga.source,
                manga_url: currentManga._url || ''
            })
        });

        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            throw new Error(err.error || `HTTP ${resp.status}`);
        }

        // 读取流式响应
        const reader = resp.body.getReader();
        const chunks = [];
        let received = 0;

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            chunks.push(value);
            received += value.length;
            const mb = (received / 1024 / 1024).toFixed(1);
            btn.textContent = `⏳ 已接收 ${mb} MB`;
        }

        // 合并chunks → blob → 触发下载
        const blob = new Blob(chunks, { type: 'application/zip' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = (currentManga.info.title || 'manga').replace(/[\\/:*?"<>|]/g, '_') + '.zip';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);

        btn.textContent = '✅ 下载完成';
        setTimeout(() => { btn.textContent = origText; btn.classList.remove('downloading'); }, 3000);
    } catch (e) {
        alert('下载失败: ' + e.message);
        btn.textContent = origText;
        btn.classList.remove('downloading');
    } finally {
        btn.disabled = false;
    }
};

async function toggleFav(m, isFav) {
    if (isFav) { await api('/api/favorites/remove', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ url: m.url }) }); $('#favBtn').textContent = '+ 收藏'; }
    else { await api('/api/favorites/add', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title: m.title, url: m.url, cover: m.cover || '', source: m._source || '' }) }); $('#favBtn').textContent = '取消收藏'; }
    loadStats();
}

// ═══ FAVORITES + 一键追更 ═══
let _favChecked = new Set();
let _favItems = [];
let _updatePreferRaw = null;  // null=未选, true=raw, false=翻译
let _lastUpdateResults = null;

async function loadFavorites() {
    const group = $('#favGroup').value;
    try {
        const d = await api(`/api/favorites?group=${encodeURIComponent(group)}`);
        const sel = $('#favGroup'); const cur = sel.value;
        sel.innerHTML = '<option value="All">全部</option>';
        (d.groups || []).forEach(g => { const o = document.createElement('option'); o.value = g; o.textContent = g; sel.appendChild(o); }); sel.value = cur || 'All';
        _favItems = d.items || [];
        const grid = $('#favGrid');
        if (!_favItems.length) { grid.innerHTML = '<div class="empty"><div class="empty-icon">❤</div><p>暂无收藏</p></div>'; return; }
        grid.innerHTML = _favItems.map(f => {
            const hist = f.download_history;
            const hasHist = hist && hist.chapters && hist.chapters.length > 0;
            const statusHtml = hasHist
                ? `<span class="fav-dl-status has-history">已下载到 ${esc(hist.last_chapter)} 章</span>`
                : `<span class="fav-dl-status no-history">未下载过</span>`;
            const checked = _favChecked.has(f.url) ? 'checked' : '';
            return `<div class="manga-card result-card" data-url="${escA(f.url)}" data-source="${escA(f.source)}">
                <input type="checkbox" class="fav-card-check" data-fav-url="${escA(f.url)}" ${checked}>
                <img src="${proxyUrl(f.cover)}" alt="" loading="lazy">
                <div class="card-body">
                    <div class="card-title">${esc(f.title)}</div>
                    <span class="badge badge-source">${esc(f.source)}</span>
                </div>
                ${statusHtml}
            </div>`;
        }).join('');

        // Card click → open detail (not on checkbox)
        grid.querySelectorAll('.manga-card').forEach(c => {
            c.addEventListener('click', (e) => {
                if (e.target.classList.contains('fav-card-check')) return;
                openDetail({ title: c.querySelector('.card-title').textContent, url: c.dataset.url, cover: c.querySelector('img').src, _source: c.dataset.source });
            });
        });

        // Checkbox change
        grid.querySelectorAll('.fav-card-check').forEach(cb => {
            cb.onchange = () => {
                if (cb.checked) _favChecked.add(cb.dataset.favUrl);
                else _favChecked.delete(cb.dataset.favUrl);
                _updateSelectedCount();
            };
        });

        // Load timeline
        loadUpdateTimeline();
    } catch (e) { }
}
$('#favGroup').onchange = loadFavorites;

function _updateSelectedCount() {
    const btn = $('#updateSelectedBtn');
    btn.textContent = `追更选中 (${_favChecked.size})`;
    btn.disabled = !_updatePreferRaw === null && _updatePreferRaw === null || _favChecked.size === 0;
    const unfavBtn = $('#unfavSelectedBtn');
    unfavBtn.textContent = `取消收藏 (${_favChecked.size})`;
    unfavBtn.disabled = _favChecked.size === 0;
    _syncUpdateBtns();
}

function _syncUpdateBtns() {
    const versionPicked = _updatePreferRaw !== null;
    $('#updateSelectedBtn').disabled = !versionPicked || _favChecked.size === 0;
    $('#updateAllBtn').disabled = !versionPicked;
}

// Version toggle
$('#verRawBtn').onclick = () => {
    _updatePreferRaw = true;
    $('#verRawBtn').classList.add('active');
    $('#verTransBtn').classList.remove('active');
    _syncUpdateBtns();
};
$('#verTransBtn').onclick = () => {
    _updatePreferRaw = false;
    $('#verTransBtn').classList.add('active');
    $('#verRawBtn').classList.remove('active');
    _syncUpdateBtns();
};

// Check all
$('#favCheckAll').onchange = () => {
    const checked = $('#favCheckAll').checked;
    _favChecked.clear();
    document.querySelectorAll('.fav-card-check').forEach(cb => {
        cb.checked = checked;
        if (checked) _favChecked.add(cb.dataset.favUrl);
    });
    _updateSelectedCount();
};

// Batch update buttons
$('#updateSelectedBtn').onclick = () => doBatchUpdate([..._favChecked]);
$('#updateAllBtn').onclick = () => doBatchUpdate([]);
$('#unfavSelectedBtn').onclick = async () => {
    const urls = [..._favChecked];
    if (!urls.length) return;
    if (!confirm(`确定要取消收藏这 ${urls.length} 部漫画吗？`)) return;
    for (const url of urls) {
        await api('/api/favorites/remove', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ url }) });
    }
    _favChecked.clear();
    loadFavorites();
    loadStats();
};

async function doBatchUpdate(urls) {
    if (_updatePreferRaw === null) { alert('请先选择版本：Raw版 或 翻译版'); return; }

    const btn = urls.length ? $('#updateSelectedBtn') : $('#updateAllBtn');
    const origText = btn.textContent;
    btn.textContent = '检测中...';
    btn.disabled = true;

    try {
        // First scan history to backfill
        await api('/api/favorites/scan-history', { method: 'POST' });

        const data = await api('/api/favorites/batch-update', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ urls, prefer_raw: _updatePreferRaw })
        });

        _lastUpdateResults = data;
        showUpdateModal(data);
    } catch (e) {
        alert('追更检测失败: ' + (e.message || e));
    } finally {
        btn.textContent = origText;
        _syncUpdateBtns();
    }
}

function showUpdateModal(data) {
    const modal = $('#updateModal');
    const verLabel = _updatePreferRaw ? 'Raw版' : '翻译版';
    $('#updateModalTitle').textContent = `📊 追更检测完成 (${verLabel})`;

    const body = $('#updateModalBody');
    body.innerHTML = (data.results || []).map(r => {
        if (r.status === 'has_updates') {
            return `<div class="update-modal-item has-new">
                <span class="um-icon">📥</span>
                <span class="um-title">${esc(r.title)}</span>
                <span class="um-info">${r.new_chapters.length} 个新章节</span>
            </div>`;
        } else if (r.status === 'up_to_date') {
            return `<div class="update-modal-item">
                <span class="um-icon">✅</span>
                <span class="um-title">${esc(r.title)}</span>
                <span class="um-info">已是最新 (${esc(r.last_chapter || '')}章)</span>
            </div>`;
        } else {
            return `<div class="update-modal-item is-error">
                <span class="um-icon">❌</span>
                <span class="um-title">${esc(r.title)}</span>
                <span class="um-info">${esc(r.message || '错误')}</span>
            </div>`;
        }
    }).join('');

    const s = data.summary || {};
    const hasNew = s.has_updates || 0;
    const totalNew = s.new_chapters || 0;
    $('#updateModalSummary').textContent = hasNew > 0
        ? `共 ${hasNew} 部需更新，${totalNew} 个新章节`
        : '所有漫画均已是最新';
    $('#updateModalConfirm').style.display = hasNew > 0 ? '' : 'none';
    $('#updateModalBrowserDl').style.display = hasNew > 0 ? '' : 'none';
    modal.style.display = 'flex';
}

$('#updateModalCancel').onclick = () => { $('#updateModal').style.display = 'none'; };
$('#updateModal').onclick = (e) => { if (e.target === $('#updateModal')) $('#updateModal').style.display = 'none'; };

$('#updateModalConfirm').onclick = async () => {
    if (!_lastUpdateResults) return;
    const items = (_lastUpdateResults.results || [])
        .filter(r => r.status === 'has_updates' && r.new_chapters.length > 0)
        .map(r => ({
            title: r.title,
            url: r.url,
            source: r.source,
            chapters: r.new_chapters
        }));

    if (!items.length) return;
    try {
        await api('/api/favorites/start-update', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ items })
        });
        $('#updateModal').style.display = 'none';
        navigate('downloads');
    } catch (e) { alert('启动下载失败: ' + (e.message || e)); }
};

// ═══ 浏览器追更下载 (流式ZIP) ═══
$('#updateModalBrowserDl').onclick = async () => {
    if (!_lastUpdateResults) return;
    const items = (_lastUpdateResults.results || [])
        .filter(r => r.status === 'has_updates' && r.new_chapters.length > 0)
        .map(r => ({
            title: r.title,
            url: r.url,
            source: r.source,
            chapters: r.new_chapters
        }));

    if (!items.length) return;

    const btn = $('#updateModalBrowserDl');
    const origText = btn.textContent;
    btn.disabled = true;
    btn.textContent = '⏳ 打包中...';
    btn.classList.add('downloading');

    try {
        const resp = await fetch('/api/favorites/start-update-zip', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ items })
        });

        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            throw new Error(err.error || `HTTP ${resp.status}`);
        }

        const reader = resp.body.getReader();
        const chunks = [];
        let received = 0;

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            chunks.push(value);
            received += value.length;
            const mb = (received / 1024 / 1024).toFixed(1);
            btn.textContent = `⏳ 已接收 ${mb} MB`;
        }

        const blob = new Blob(chunks, { type: 'application/zip' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        const today = new Date().toISOString().slice(0, 10);
        a.download = `追更_${today}.zip`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);

        btn.textContent = '✅ 下载完成';
        setTimeout(() => {
            btn.textContent = origText;
            btn.classList.remove('downloading');
        }, 3000);
        $('#updateModal').style.display = 'none';
    } catch (e) {
        alert('浏览器下载失败: ' + e.message);
        btn.textContent = origText;
        btn.classList.remove('downloading');
    } finally {
        btn.disabled = false;
    }
};

// Update timeline
async function loadUpdateTimeline() {
    try {
        const log = await api('/api/favorites/update-log');
        const container = $('#updateTimeline');
        const list = $('#updateTimelineList');
        if (!log || !log.length) { container.style.display = 'none'; return; }
        container.style.display = '';
        const SHOW_N = 3;
        const allHtml = log.slice(0, 20).map((e, idx) => {
            let detailsHtml = '';
            if (e.chapter_details && e.chapter_details.length) {
                detailsHtml = '<div class="timeline-details">' + e.chapter_details.map(d => {
                    let rangeText;
                    if (d.count === 1) {
                        rangeText = `\u4e0b\u8f7d\u4e86\u7b2c${esc(d.from)}\u8bdd (1\u7ae0)`;
                    } else {
                        rangeText = `\u7b2c${esc(d.from)}\u8bdd \u2192 \u7b2c${esc(d.to)}\u8bdd (${d.count}\u7ae0)`;
                    }
                    return `<div class="timeline-detail-item">
                        <span class="timeline-detail-title">${esc(d.title)}</span>
                        <span class="timeline-detail-range">${rangeText}</span>
                    </div>`;
                }).join('') + '</div>';
            } else {
                const titles = (e.titles || []).map(t => `<b>${esc(t)}</b>`).join('\u3001');
                detailsHtml = `<span class="timeline-info-legacy">\u2014 ${titles || '\u672a\u77e5'}</span>`;
            }
            const hidden = idx >= SHOW_N ? ' style="display:none"' : '';
            return `<div class="timeline-item" data-collapse-item${hidden}>
                <div class="timeline-row">
                    <span class="timeline-time">${esc(e.time)}</span>
                    <span class="timeline-info">\u8ffd\u66f4 ${e.manga_count} \u90e8\uff0c\u5171 ${e.chapter_count} \u7ae0</span>
                </div>
                ${detailsHtml}
            </div>`;
        }).join('');
        const toggleBtn = log.length > SHOW_N ? `<div class="collapse-toggle" id="timelineToggle">\u5c55\u5f00\u5168\u90e8 (${log.length}\u6761)</div>` : '';
        list.innerHTML = allHtml + toggleBtn;
        const toggle = document.getElementById('timelineToggle');
        if (toggle) {
            let expanded = false;
            toggle.onclick = () => {
                expanded = !expanded;
                list.querySelectorAll('[data-collapse-item]').forEach((el, i) => {
                    if (i >= SHOW_N) el.style.display = expanded ? '' : 'none';
                });
                toggle.textContent = expanded ? '\u6536\u8d77' : `\u5c55\u5f00\u5168\u90e8 (${log.length}\u6761)`;
            };
        }
    } catch (e) { }
}

// Nav badge — check on startup
(async () => {
    try {
        const d = await api('/api/favorites/check-new');
        const badge = $('#favBadge');
        if (d.count > 0) {
            badge.textContent = d.count;
            badge.style.display = '';
        } else {
            badge.style.display = 'none';
        }
    } catch (e) { }
})();

// ═══ DOWNLOADS ═══
function startPoll() { stopPoll(); poll(); loadDownloadHistory(); dlPoll = setInterval(poll, 1200); }
function stopPoll() { if (dlPoll) { clearInterval(dlPoll); dlPoll = null; } }
const SL = { Waiting: '等待', Downloading: '下载中', Completed: '完成', Failed: '失败', Paused: '暂停', Cancelled: '取消' };
async function poll() {
    try {
        const d = await api('/api/download/status');
        const el = $('#dlTaskList');
        if (!d.tasks?.length) { el.innerHTML = '<div class="empty"><div class="empty-icon">📥</div><p>暂无下载任务</p></div>'; return; }
        el.innerHTML = d.tasks.map((t, i) => {
            const pct = t.total > 0 ? Math.round(t.progress / t.total * 100) : 0;
            const spd = t.speed > 1024 ? (t.speed / 1024).toFixed(1) + ' MB/s' : (t.speed > 0 ? Math.round(t.speed) + ' KB/s' : '');
            return `<div class="dl-item"><span class="dl-name">${esc(t.title)}</span><span class="dl-speed">${spd}</span><div class="dl-bar-wrap"><div class="dl-bar" style="width:${pct}%"></div></div><span class="dl-status st-${t.status}">${SL[t.status] || t.status}</span><div class="dl-actions">${t.status === 'Downloading' ? `<button onclick="pauseTask(${i})">⏸</button>` : ''}${t.status === 'Paused' ? `<button onclick="resumeTask(${i})">▶</button>` : ''}${['Waiting', 'Downloading', 'Paused'].includes(t.status) ? `<button onclick="cancelTask(${i})">✕</button>` : ''}</div></div>`;
        }).join('');
        const logs = await api('/api/download/logs');
        const le = $('#dlLog'); le.innerHTML = logs.map(l => `<div>${esc(l)}</div>`).join(''); le.scrollTop = le.scrollHeight;
        if (d.total > 0 && d.done >= d.total) { stopPoll(); dlPoll = setInterval(poll, 5000); }
    } catch (e) { }
}
async function pauseTask(i) { await api(`/api/download/pause/${i}`, { method: 'POST' }); }
async function resumeTask(i) { await api(`/api/download/resume/${i}`, { method: 'POST' }); }
async function cancelTask(i) { await api(`/api/download/cancel/${i}`, { method: 'POST' }); }
$('#cancelAllBtn').onclick = async () => { if (confirm('取消全部？')) await api('/api/download/cancel_all', { method: 'POST' }); };

// 下载历史
async function loadDownloadHistory() {
    try {
        const log = await api('/api/download/history');
        const container = $('#downloadHistory');
        const list = $('#dlHistoryList');
        if (!log || !log.length) { container.style.display = 'none'; return; }
        container.style.display = '';
        const SHOW_N = 5;
        let lastDate = '';
        let idx = 0;
        const allHtml = log.map(e => {
            const dateStr = e.time ? e.time.split(' ')[0] : '';
            const timeStr = e.time ? e.time.split(' ')[1] || '' : '';
            let dateSep = '';
            if (dateStr !== lastDate) {
                lastDate = dateStr;
                dateSep = `<div class="dl-history-date">${esc(dateStr)}</div>`;
            }
            let rangeText;
            if (e.count === 1) {
                rangeText = `\u4e0b\u8f7d\u4e86\u7b2c${esc(e.from_chapter)}\u8bdd (1\u7ae0)`;
            } else {
                rangeText = `\u7b2c${esc(e.from_chapter)}\u8bdd \u2192 \u7b2c${esc(e.to_chapter)}\u8bdd (${e.count}\u7ae0)`;
            }
            const typeCls = e.type === 'update' ? 'dl-type-update' : 'dl-type-manual';
            const typeLabel = e.type === 'update' ? '\u8ffd\u66f4' : '\u624b\u52a8';
            const curIdx = idx++;
            const hidden = curIdx >= SHOW_N ? ' style="display:none"' : '';
            return `${dateSep}<div class="dl-history-item" data-collapse-item${hidden}>
                <div class="dl-history-row1">
                    <span class="dl-history-time">${esc(timeStr)}</span>
                    <span class="dl-history-title">${esc(e.manga_title || '')}</span>
                    <span class="dl-history-source">${esc(e.source || '')}</span>
                </div>
                <div class="dl-history-row2">
                    <span class="dl-history-range">${rangeText}</span>
                    <span class="dl-history-type ${typeCls}">${typeLabel}</span>
                </div>
            </div>`;
        }).join('');
        const toggleBtn = log.length > SHOW_N ? `<div class="collapse-toggle" id="dlHistoryToggle">\u5c55\u5f00\u5168\u90e8 (${log.length}\u6761)</div>` : '';
        list.innerHTML = allHtml + toggleBtn;
        const toggle = document.getElementById('dlHistoryToggle');
        if (toggle) {
            let expanded = false;
            toggle.onclick = () => {
                expanded = !expanded;
                list.querySelectorAll('[data-collapse-item]').forEach((el, i) => {
                    if (i >= SHOW_N) el.style.display = expanded ? '' : 'none';
                });
                toggle.textContent = expanded ? '\u6536\u8d77' : `\u5c55\u5f00\u5168\u90e8 (${log.length}\u6761)`;
            };
        }
    } catch (e) { }
}
$('#clearHistoryBtn').onclick = async () => {
    if (!confirm('\u786e\u5b9a\u6e05\u7a7a\u6240\u6709\u4e0b\u8f7d\u5386\u53f2\uff1f')) return;
    await api('/api/download/history/clear', { method: 'POST' });
    loadDownloadHistory();
};

// ═══ SETTINGS ═══
async function loadConfig() { try { const c = await api('/api/config'); $('#cfgDir').value = c.download_dir || ''; $('#cfgChConc').value = c.chapter_concurrency || 2; $('#cfgImgConc').value = c.image_concurrency || 4; $('#cfgProxyMode').value = c.proxy_mode || 'none'; $('#cfgProxyHost').value = c.proxy_host || ''; $('#cfgProxyPort').value = c.proxy_port || ''; } catch (e) { } }
$('#saveConfig').onclick = async () => {
    await api('/api/config', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ download_dir: $('#cfgDir').value, chapter_concurrency: parseInt($('#cfgChConc').value) || 2, image_concurrency: parseInt($('#cfgImgConc').value) || 4, proxy_mode: $('#cfgProxyMode').value, proxy_host: $('#cfgProxyHost').value, proxy_port: $('#cfgProxyPort').value }) });
    alert('已保存');
};
$('#themeDark').onclick = () => setTheme('dark');
$('#themeLight').onclick = () => setTheme('light');
async function setTheme(t) {
    if (t === 'dark') document.body.setAttribute('data-theme', 'dark'); else document.body.removeAttribute('data-theme');
    $('#themeDark').classList.toggle('active', t === 'dark');
    $('#themeLight').classList.toggle('active', t === 'light');
    await api('/api/config', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ theme: t }) });
}
$('#refreshHealthBtn').onclick = async () => {
    $('#healthList').innerHTML = '<div class="loading"><div class="spinner"></div><span>检测中...</span></div>';
    try {
        const d = await api('/api/source-health');
        $('#healthList').innerHTML = d.map(r => {
            const dot = r.status === 'online' ? 'online' : 'offline';
            let label, badge;
            if (r.status !== 'online') {
                label = '离线'; badge = '<span style="color:#ef4444;font-weight:600">❌ 离线</span>';
            } else if (r.grade === 'fast') {
                label = `${r.latency_ms}ms`; badge = '<span style="color:#10b981;font-weight:600">⚡快</span>';
            } else if (r.grade === 'medium') {
                label = `${r.latency_ms}ms`; badge = '<span style="color:#f59e0b;font-weight:600">🔶中</span>';
            } else {
                label = `${r.latency_ms}ms`; badge = '<span style="color:#ef4444;font-weight:600">🐢慢</span>';
            }
            return `<div class="health-row"><span class="health-dot ${dot}"></span><span class="health-name">${r.icon} ${esc(r.source)}</span>${badge}<span class="health-ms">${label}</span></div>`;
        }).join('');
    } catch (e) { $('#healthList').innerHTML = '<div>检测失败</div>'; }
};

// ═══ CROSS-SOURCE ═══
async function loadCrossSource(title, currentSource, currentChCount) {
    const panel = $('#sourcePanel');
    const list = $('#sourceList');
    const status = $('#sourcePanelStatus');
    const fab = $('#sourceFab');
    const badge = $('#sourceFabBadge');

    // 显示悬浮球, 检测动画, 面板隐藏
    fab.style.display = '';
    fab.classList.add('detecting');
    fab.classList.remove('active');
    panel.style.display = 'none';
    badge.textContent = '···';
    status.textContent = '检测中...';
    list.innerHTML = `<div class="source-row"><span class="source-icon">⭐</span><span class="source-name">${esc(currentSource)}</span><span class="source-tag tag-current">当前源</span><span class="source-chapters">${currentChCount}章</span><span></span><span></span></div>`;

    try {
        const d = await api(`/api/cross-source?title=${encodeURIComponent(title)}&current_source=${encodeURIComponent(currentSource)}`);
        const rows = d.results || [];
        const matched = rows.filter(r => r.match);
        const unmatched = rows.filter(r => !r.match);

        // 推荐源: 章节最多 > 延迟最低
        let recommended = null;
        if (matched.length > 0) {
            recommended = matched.reduce((a, b) => {
                if (b.chapter_count > a.chapter_count) return b;
                if (b.chapter_count === a.chapter_count && b.latency_ms < a.latency_ms) return b;
                return a;
            });
        }

        // 6-column grid: icon | name | speed | chapters | button | link
        let html = `<div class="source-row"><span class="source-icon">⭐</span><span class="source-name">${esc(currentSource)}</span><span class="source-tag tag-current">当前源</span><span class="source-chapters">${currentChCount}章</span><span></span><span></span></div>`;

        // 匹配到的源
        matched.forEach(r => {
            const speedClass = r.latency_ms < 1000 ? 'speed-fast' : r.latency_ms < 3000 ? 'speed-mid' : 'speed-slow';
            html += `<div class="source-row">`;
            html += `<span class="source-icon">${r.icon || '📕'}</span>`;
            html += `<span class="source-name">${esc(r.source)}</span>`;
            html += `<span class="source-speed ${speedClass}">${r.latency_ms}ms</span>`;
            html += `<span class="source-chapters">${r.chapter_count ? r.chapter_count + '章' : ''}</span>`;
            html += `<button class="source-btn-switch" data-url="${escA(r.match.url)}" data-source="${escA(r.source)}" data-cover="${escA(r.match.cover)}" data-title="${escA(r.match.title)}">切换到此源</button>`;
            html += `<a class="source-btn-link" href="${escA(r.match.url)}" target="_blank" rel="noopener" title="在${esc(r.source)}查看">↗</a>`;
            html += `</div>`;
        });

        // 未匹配的源 — 竖列展示
        if (unmatched.length > 0) {
            html += `<div class="source-unmatched">`;
            unmatched.forEach(r => {
                const st = r.status === 'offline' ? '离线' : r.status === 'error' ? `❌${r.latency_ms}ms` : '未找到';
                html += `<a class="source-search-link" data-source="${escA(r.source)}" data-title="${escA(title)}">${r.icon || ''} ${esc(r.source)} <small>(${st})</small></a>`;
            });
            html += `</div>`;
        }

        // 章节补全提示
        matched.forEach(r => {
            if (r.chapter_count > currentChCount) {
                const diff = r.chapter_count - currentChCount;
                html += `<div class="source-gap-alert">⚡ ${esc(r.source)} 比当前源多 ${diff} 章</div>`;
            }
        });

        // 最优源下载按钮
        if (recommended) {
            html += `<button class="source-best-btn" id="bestSourceBtn" data-url="${escA(recommended.match.url)}" data-source="${escA(recommended.source)}" data-cover="${escA(recommended.match.cover)}" data-title="${escA(recommended.match.title)}">🚀 使用最优源下载 (${esc(recommended.source)})</button>`;
        }

        list.innerHTML = html;
        const matchInfo = `${matched.length + 1}/${rows.length + 1}`;
        status.textContent = `${matchInfo} 个源可用`;
        badge.textContent = matchInfo;
        fab.classList.remove('detecting');

        // 绑定切换按钮
        list.querySelectorAll('.source-btn-switch').forEach(btn => {
            btn.onclick = () => openDetail({ title: btn.dataset.title, url: btn.dataset.url, cover: btn.dataset.cover, _source: btn.dataset.source });
        });

        // 绑定最优源按钮
        const bestBtn = list.querySelector('#bestSourceBtn');
        if (bestBtn) {
            bestBtn.onclick = () => openDetail({ title: bestBtn.dataset.title, url: bestBtn.dataset.url, cover: bestBtn.dataset.cover, _source: bestBtn.dataset.source });
        }

        // 绑定未匹配源搜索链接
        list.querySelectorAll('.source-search-link').forEach(a => {
            a.onclick = () => {
                const srcName = a.dataset.source;
                const t = a.dataset.title;
                // 切换到搜索页, 填入标题, 选中源
                navigate('search');
                $('#searchInput').value = t;
                const trigger = document.querySelector('#sourceFilterDropdown .dropdown-trigger');
                if (trigger) { trigger.dataset.value = srcName; trigger.textContent = srcName; }
                doSearch();
            };
        });
    } catch (e) {
        status.textContent = '检测失败';
        badge.textContent = '✖';
        fab.classList.remove('detecting');
    }
}

// 悬浮球点击切换
$('#sourceFab').onclick = (e) => {
    e.stopPropagation();
    const panel = $('#sourcePanel');
    const fab = $('#sourceFab');
    const isOpen = panel.style.display !== 'none';
    panel.style.display = isOpen ? 'none' : '';
    fab.classList.toggle('active', !isOpen);
};

// 点击外部关闭弹窗
document.addEventListener('click', (e) => {
    const panel = $('#sourcePanel');
    const fab = $('#sourceFab');
    if (panel.style.display !== 'none' && !panel.contains(e.target) && !fab.contains(e.target)) {
        panel.style.display = 'none';
        fab.classList.remove('active');
    }
});

function esc(s) { const d = document.createElement('div'); d.textContent = s || ''; return d.innerHTML; }
function escA(s) { return (s || '').replace(/"/g, '&quot;').replace(/'/g, '&#39;'); }
document.onkeydown = e => {
    const readerOpen = $('#readerOverlay').style.display !== 'none';
    if (readerOpen) {
        if (e.key === 'Escape') { closeReader(); return; }
        if (e.key === 'ArrowLeft') { e.preventDefault(); $('#readerPrev').click(); return; }
        if (e.key === 'ArrowRight') { e.preventDefault(); $('#readerNext').click(); return; }
        if (e.key === 'Home') { e.preventDefault(); $('#readerImages').scrollTo({ top: 0, behavior: 'smooth' }); return; }
        if (e.key === 'End') { e.preventDefault(); $('#readerImages').scrollTo({ top: $('#readerImages').scrollHeight, behavior: 'smooth' }); return; }
        if (e.key === ' ') { e.preventDefault(); $('#readerImages').scrollBy({ top: window.innerHeight * 0.8, behavior: 'smooth' }); return; }
    }
    if (e.ctrlKey && e.key === 'f') { e.preventDefault(); navigate('search'); $('#searchInput').focus(); }
};

// ═══ ONLINE READER ═══
let _readerChapterIdx = -1;
let _nextChapterCache = null;  // { url, images }

function _readProgressKey() {
    if (!currentManga || !currentManga._url) return null;
    return 'readProgress:' + currentManga._url;
}

function _saveReadProgress(chapterUrl) {
    const key = _readProgressKey();
    if (key) localStorage.setItem(key, chapterUrl);
}

function _getReadProgress() {
    const key = _readProgressKey();
    return key ? localStorage.getItem(key) : null;
}

async function openReader(chapterUrl, chapterTitle) {
    const overlay = $('#readerOverlay');
    const container = $('#readerImages');
    const loading = $('#readerLoading');
    const progress = $('#readerProgress');

    overlay.style.display = 'flex';
    document.body.style.overflow = 'hidden';
    container.innerHTML = '';
    container.appendChild(loading);
    loading.style.display = 'block';
    loading.textContent = '\u52a0\u8f7d\u4e2d...';
    progress.style.setProperty('--progress', '0%');
    $('#readerPageIndicator').textContent = '';
    $('#readerScrollTop').classList.remove('visible');
    $('#readerScrollBottom').classList.remove('visible');

    // Find index in chapters
    if (currentManga && currentManga.chapters) {
        _readerChapterIdx = currentManga.chapters.findIndex(c => c.url === chapterUrl);
    }
    _updateReaderNav();
    _populateChapterSelect();

    // Save progress
    _saveReadProgress(chapterUrl);
    // 保存阅读器状态以支持刷新恢复
    try { sessionStorage.setItem('lastReaderChapter', JSON.stringify({ url: chapterUrl, title: chapterTitle })); } catch (e) { }

    // Close picker if open
    const picker = document.getElementById('chPickerPopover');
    if (picker) picker.classList.remove('open');

    try {
        let images;
        // Check if we have preloaded next chapter cache
        if (_nextChapterCache && _nextChapterCache.url === chapterUrl) {
            images = _nextChapterCache.images;
            _nextChapterCache = null;
        } else {
            const src = currentManga ? currentManga.source : '';
            const data = await api(`/api/chapter-images?url=${encodeURIComponent(chapterUrl)}&source=${encodeURIComponent(src)}`);
            images = data.images;
        }
        if (!images || !images.length) {
            loading.textContent = '\u672a\u627e\u5230\u56fe\u7247';
            return;
        }
        loading.style.display = 'none';
        const total = images.length;
        let loaded = 0;

        // Build all img elements without loading (data-src only)
        const fragment = document.createDocumentFragment();
        images.forEach((imgUrl, i) => {
            const img = document.createElement('img');
            img.alt = `Page ${i + 1}`;
            img.dataset.src = proxyUrl(imgUrl);
            img.style.minHeight = '300px';
            img.style.background = 'var(--card, #1a1a2e)';
            fragment.appendChild(img);
        });
        container.appendChild(fragment);

        // IntersectionObserver: load images only when near viewport
        const observer = new IntersectionObserver((entries) => {
            entries.forEach(entry => {
                if (entry.isIntersecting) {
                    const img = entry.target;
                    if (img.dataset.src) {
                        const origSrc = img.dataset.src;
                        let retries = 0;
                        const maxRetries = 3;
                        const tryLoad = () => {
                            img.src = origSrc + (retries > 0 ? `&_r=${retries}` : '');
                        };
                        delete img.dataset.src;
                        img.onload = () => {
                            loaded++;
                            img.style.minHeight = '';
                            img.style.background = '';
                            progress.style.setProperty('--progress', `${(loaded / total * 100).toFixed(0)}%`);
                        };
                        img.onerror = () => {
                            retries++;
                            if (retries < maxRetries) {
                                setTimeout(tryLoad, 1000 * retries);
                            } else {
                                loaded++;
                                img.alt = `Page ${parseInt(img.alt.match(/\d+/)) || '?'} (\u52a0\u8f7d\u5931\u8d25)`;
                                img.style.minHeight = '60px';
                                img.style.background = '#333';
                                progress.style.setProperty('--progress', `${(loaded / total * 100).toFixed(0)}%`);
                            }
                        };
                        tryLoad();
                    }
                    observer.unobserve(img);
                }
            });
        }, { root: container, rootMargin: '600px 0px' });

        container.querySelectorAll('img[data-src]').forEach(img => observer.observe(img));

        // Setup scroll tracking: page indicator + preload trigger
        _setupScrollTracking(container, total);

    } catch (e) {
        loading.textContent = '\u52a0\u8f7d\u5931\u8d25: ' + (e.message || e);
    }
}

function _setupScrollTracking(container, totalImages) {
    let _preloadTriggered = false;
    container.onscroll = () => {
        const scrollTop = container.scrollTop;
        const scrollHeight = container.scrollHeight - container.clientHeight;
        const ratio = scrollHeight > 0 ? scrollTop / scrollHeight : 0;

        // Page indicator: estimate current image by scroll position
        const currentImg = Math.min(totalImages, Math.max(1, Math.ceil(ratio * totalImages)));
        $('#readerPageIndicator').textContent = `${currentImg}/${totalImages}`;

        // Scroll buttons
        const showBtns = scrollTop > window.innerHeight;
        $('#readerScrollTop').classList.toggle('visible', showBtns);
        $('#readerScrollBottom').classList.toggle('visible', showBtns && ratio < 0.95);

        // Preload next chapter at 80%
        if (ratio > 0.8 && !_preloadTriggered) {
            _preloadTriggered = true;
            _preloadNextChapter();
        }
    };
}

async function _preloadNextChapter() {
    if (!currentManga || !currentManga.chapters) return;
    const nextIdx = _readerChapterIdx + 1;
    if (nextIdx >= currentManga.chapters.length) return;
    const nextCh = currentManga.chapters[nextIdx];
    try {
        const src = currentManga.source || '';
        const data = await api(`/api/chapter-images?url=${encodeURIComponent(nextCh.url)}&source=${encodeURIComponent(src)}`);
        if (data.images && data.images.length) {
            _nextChapterCache = { url: nextCh.url, images: data.images };
            // Also preload first few images
            data.images.slice(0, 5).forEach(u => { const img = new Image(); img.src = proxyUrl(u); });
        }
    } catch (e) { /* silent */ }
}

function _populateChapterSelect() {
    const sel = $('#readerChSelect');
    sel.innerHTML = '';
    if (!currentManga || !currentManga.chapters) return;
    currentManga.chapters.forEach((ch, i) => {
        const opt = document.createElement('option');
        opt.value = i;
        opt.textContent = ch.title;
        if (i === _readerChapterIdx) opt.selected = true;
        sel.appendChild(opt);
    });
}

function closeReader() {
    $('#readerOverlay').style.display = 'none';
    document.body.style.overflow = '';
    _nextChapterCache = null;
    try { sessionStorage.removeItem('lastReaderChapter'); } catch (e) { }
}

function _updateReaderNav() {
    const chapters = currentManga ? currentManga.chapters : [];
    $('#readerPrev').disabled = _readerChapterIdx <= 0;
    $('#readerNext').disabled = _readerChapterIdx < 0 || _readerChapterIdx >= chapters.length - 1;
}

$('#readerClose').onclick = closeReader;
$('#readerPrev').onclick = () => {
    if (!currentManga || _readerChapterIdx <= 0) return;
    const ch = currentManga.chapters[_readerChapterIdx - 1];
    openReader(ch.url, ch.title);
};
$('#readerNext').onclick = () => {
    if (!currentManga || _readerChapterIdx < 0 || _readerChapterIdx >= currentManga.chapters.length - 1) return;
    const ch = currentManga.chapters[_readerChapterIdx + 1];
    openReader(ch.url, ch.title);
};
$('#readerChSelect').onchange = function () {
    if (!currentManga || !currentManga.chapters) return;
    const ch = currentManga.chapters[parseInt(this.value)];
    if (ch) openReader(ch.url, ch.title);
};
$('#readerScrollTop').onclick = () => {
    $('#readerImages').scrollTo({ top: 0, behavior: 'smooth' });
};
$('#readerScrollBottom').onclick = () => {
    $('#readerImages').scrollTo({ top: $('#readerImages').scrollHeight, behavior: 'smooth' });
};

// ═══ Chapter Picker Popover (on 在线阅读 button) ═══
$('#readFirstBtn').onclick = (e) => {
    e.stopPropagation();
    if (!currentManga || !currentManga.chapters || !currentManga.chapters.length) {
        alert('\u6ca1\u6709\u7ae0\u8282\u53ef\u9605\u8bfb');
        return;
    }
    let picker = document.getElementById('chPickerPopover');
    if (!picker) {
        picker = document.createElement('div');
        picker.id = 'chPickerPopover';
        picker.className = 'ch-picker-popover';
        $('#readFirstBtn').parentElement.style.position = 'relative';
        $('#readFirstBtn').parentElement.appendChild(picker);
    }
    if (picker.classList.contains('open')) {
        picker.classList.remove('open');
        return;
    }
    _buildPicker(picker);
    picker.classList.add('open');
};

function _buildPicker(picker) {
    const chapters = currentManga.chapters;
    const lastCh = chapters[chapters.length - 1]; // first chapter (oldest)
    const firstCh = chapters[0]; // newest chapter
    const savedUrl = _getReadProgress();
    const savedCh = savedUrl ? chapters.find(c => c.url === savedUrl) : null;

    let html = '<div class="ch-picker-header">';
    html += `<button class="btn" data-action="first">\u7b2c1\u8bdd</button>`;
    html += `<button class="btn" data-action="latest">\u6700\u65b0\u8bdd</button>`;
    if (savedCh) {
        html += `<button class="btn btn-accent" data-action="continue">\u7ee7\u7eed ${savedCh.title}</button>`;
    }
    html += '</div>';
    html += '<div class="ch-picker-list">';
    chapters.forEach((ch, i) => {
        html += `<div class="ch-picker-item" data-idx="${i}">${esc(ch.title)}</div>`;
    });
    html += '</div>';
    picker.innerHTML = html;

    // Quick buttons
    picker.querySelector('[data-action="first"]').onclick = (e) => {
        e.stopPropagation();
        picker.classList.remove('open');
        openReader(lastCh.url, lastCh.title);
    };
    picker.querySelector('[data-action="latest"]').onclick = (e) => {
        e.stopPropagation();
        picker.classList.remove('open');
        openReader(firstCh.url, firstCh.title);
    };
    if (savedCh) {
        picker.querySelector('[data-action="continue"]').onclick = (e) => {
            e.stopPropagation();
            picker.classList.remove('open');
            openReader(savedCh.url, savedCh.title);
        };
    }

    // Chapter list items
    picker.querySelectorAll('.ch-picker-item').forEach(item => {
        item.onclick = (e) => {
            e.stopPropagation();
            picker.classList.remove('open');
            const ch = chapters[parseInt(item.dataset.idx)];
            openReader(ch.url, ch.title);
        };
    });
}

// Close picker on outside click
document.addEventListener('click', (e) => {
    const picker = document.getElementById('chPickerPopover');
    if (picker && picker.classList.contains('open') && !picker.contains(e.target) && e.target.id !== 'readFirstBtn') {
        picker.classList.remove('open');
    }
});
