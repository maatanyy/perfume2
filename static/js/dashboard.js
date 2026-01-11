// 대시보드 JavaScript (실시간 업데이트용)
(function() {
    'use strict';
    
    // 진행 중인 작업이 있으면 주기적으로 업데이트
    const activeJobs = document.querySelectorAll('[data-job-id]');
    
    if (activeJobs.length > 0) {
        activeJobs.forEach(jobElement => {
            const jobId = jobElement.dataset.jobId;
            updateJobProgress(jobId);
            setInterval(() => updateJobProgress(jobId), 3000); // 3초마다 업데이트
        });
    }
    
    function updateJobProgress(jobId) {
        fetch(`/api/progress/${jobId}`)
            .then(response => response.json())
            .then(data => {
                // 진행률 바 업데이트
                const progressBar = document.querySelector(`[data-job-id="${jobId}"] .progress-bar`);
                if (progressBar) {
                    progressBar.style.width = data.progress + '%';
                    progressBar.textContent = data.progress + '%';
                }
                
                // 카운터 업데이트
                const counter = document.querySelector(`[data-job-id="${jobId}"] .progress-counter`);
                if (counter) {
                    counter.textContent = `${data.current}/${data.total}`;
                }
            })
            .catch(error => {
                console.error('진행률 업데이트 실패:', error);
            });
    }
})();

