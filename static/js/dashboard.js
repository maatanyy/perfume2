/**
 * dashboard.js - SSE 기반 실시간 진행률 (perfume3)
 * SSE 연결 실패 시 폴링 방식으로 자동 fallback
 */

/**
 * SSE로 특정 job 진행률 실시간 수신
 * @param {number} jobId
 * @param {string} siteKey  - 사이트 키 (카드 ID에 사용)
 */
function connectJobSSE(jobId, siteKey) {
    const source = new EventSource(`/api/jobs/${jobId}/stream`);

    source.onmessage = function(event) {
        const data = JSON.parse(event.data);
        if (data.heartbeat) return;

        updateSiteCard(siteKey, data);

        if (data.done) {
            source.close();
            setTimeout(() => location.reload(), 1000);
        }
    };

    source.onerror = function() {
        source.close();
        // SSE 실패 → 2초 폴링으로 fallback
        startPolling(jobId, siteKey);
    };

    return source;
}

/**
 * 폴링 방식 fallback
 */
function startPolling(jobId, siteKey) {
    const interval = setInterval(async function() {
        try {
            const res = await fetch(`/api/progress/${jobId}`);
            if (!res.ok) { clearInterval(interval); return; }
            const data = await res.json();

            updateSiteCard(siteKey, {
                percent: data.progress,
                processed: data.current,
                total: data.total,
                eta_display: data.stats && data.stats.eta_display ? data.stats.eta_display : '',
                speed: data.stats && data.stats.items_per_second ? data.stats.items_per_second : 0,
            });

            if (data.status !== 'running' && data.status !== 'pending') {
                clearInterval(interval);
                setTimeout(() => location.reload(), 1000);
            }
        } catch (err) {
            clearInterval(interval);
        }
    }, 2000);
}

/**
 * 카드 UI 업데이트
 */
function updateSiteCard(siteKey, data) {
    // 진행률 바
    const bar = document.getElementById(`progress-bar-${siteKey}`);
    if (bar && data.percent !== undefined) {
        const pct = Math.round(data.percent);
        bar.style.width = pct + '%';
        bar.textContent = pct + '%';
    }

    // ETA
    const etaEl = document.getElementById(`eta-${siteKey}`);
    if (etaEl && data.eta_display) {
        etaEl.textContent = '⏱ ' + data.eta_display;
    }

    // 처리 수
    const countEl = document.getElementById(`count-${siteKey}`);
    if (countEl && data.processed !== undefined) {
        countEl.textContent = `${data.processed}/${data.total || '?'}`;
    }

    // 마지막 아이템
    const lastEl = document.getElementById(`last-item-${siteKey}`);
    if (lastEl && data.last_item) {
        lastEl.textContent = data.last_item;
    }

    // 속도 배지
    const badge = document.getElementById(`badge-${siteKey}`);
    if (badge && data.speed && data.speed > 0) {
        badge.textContent = `크롤링 중 (${data.speed.toFixed(2)}/s)`;
    }
}
