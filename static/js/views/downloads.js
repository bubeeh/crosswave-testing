// Downloads View & Live Manager Handler Module for CrossWave Hybrid
import { escapeHtml } from '../core/utils.js';
import { createResultRow } from './search.js';

let downloadsPollInterval = null;

export function initDownloadsView() {
    const refreshBtn = document.getElementById('btn-refresh-downloads');
    if (refreshBtn) {
        refreshBtn.addEventListener('click', () => {
            fetchDownloadJobs();
            fetchLocalDownloadedFiles();
        });
    }
}

export function startDownloadsPolling() {
    stopDownloadsPolling();
    fetchDownloadJobs();
    fetchLocalDownloadedFiles();
    downloadsPollInterval = setInterval(() => {
        fetchDownloadJobs();
    }, 2000);
}

export function stopDownloadsPolling() {
    if (downloadsPollInterval) {
        clearInterval(downloadsPollInterval);
        downloadsPollInterval = null;
    }
}

export async function fetchDownloadJobs() {
    const container = document.getElementById('download-jobs-container');
    const spinner = document.getElementById('dl-spinner-icon');
    if (!container) return;

    try {
        const res = await fetch('/api/soundload/jobs');
        const data = await res.json();
        const jobs = data.jobs || [];

        const dirPath = document.getElementById('downloads-dir-path');
        if (dirPath && data.download_dir) {
            dirPath.innerText = `Cartella: ${data.download_dir}`;
        }

        const activeJobs = jobs.filter(j => j.status === 'downloading' || j.status === 'pending' || j.status === 'processing');
        if (spinner) {
            if (activeJobs.length > 0) spinner.classList.remove('hidden');
            else spinner.classList.add('hidden');
        }

        if (jobs.length === 0) {
            container.innerHTML = '<div class="empty-state-text" style="padding: 16px;">Nessun download in coda. Clicca ☁️ su qualsiasi brano per avviare!</div>';
            return;
        }

        container.innerHTML = '';
        jobs.slice().reverse().forEach(job => {
            const card = document.createElement('div');
            card.className = 'download-job-card glassmorphic';

            let statusBadge = '<span class="badge badge-pending">In attesa</span>';
            if (job.status === 'downloading') statusBadge = `<span class="badge badge-downloading"><i class="fa-solid fa-spinner fa-spin"></i> ${job.percent_val || 0}%</span>`;
            else if (job.status === 'processing') statusBadge = '<span class="badge badge-processing">Conversione MP3</span>';
            else if (job.status === 'finished') statusBadge = '<span class="badge badge-finished">Completato ✅</span>';
            else if (job.status === 'failed') statusBadge = '<span class="badge badge-failed">Fallito ❌</span>';

            card.innerHTML = `
                <div class="job-info-row">
                    <div class="job-meta">
                        <span class="job-title truncate">${escapeHtml(job.title || job.url)}</span>
                        <span class="job-subtext">${escapeHtml(job.message || '')} ${job.speed_str ? '• ' + job.speed_str : ''} ${job.eta_str ? '• ETA: ' + job.eta_str : ''}</span>
                    </div>
                    ${statusBadge}
                </div>
                <div class="job-progress-bar">
                    <div class="job-progress-fill" style="width: ${job.percent_val || 0}%"></div>
                </div>
            `;
            container.appendChild(card);
        });

    } catch (e) {
        console.error('Failed to fetch download jobs', e);
    }
}

export async function fetchLocalDownloadedFiles() {
    const list = document.getElementById('local-downloads-list');
    if (!list) return;

    try {
        const res = await fetch('/api/downloads/local');
        const data = await res.json();
        const files = data.files || [];

        list.innerHTML = '';
        if (files.length === 0) {
            list.innerHTML = '<div class="empty-state-text" style="padding: 16px;">Nessun file scaricato nella cartella downloads/.</div>';
            return;
        }

        files.forEach((file, idx) => {
            const track = {
                id: 'local_' + idx,
                title: file.title || file.filename,
                artist: file.artist || 'Libreria Locale',
                url: `/api/downloads/stream/${encodeURIComponent(file.rel_path)}`,
                thumbnail: 'https://images.unsplash.com/photo-1614680376593-902f74fa0d41?w=80',
                duration: file.duration || 0,
                source: 'local',
                type: 'track'
            };
            const row = createResultRow(track, idx);
            list.appendChild(row);
        });
    } catch (e) {
        console.error('Failed to fetch local downloaded files', e);
    }
}

if (document.readyState !== 'loading') {
    initDownloadsView();
} else {
    document.addEventListener('DOMContentLoaded', () => {
        initDownloadsView();
    });
}
