const form = document.getElementById('videoUploadForm');
const fileInput = document.getElementById('videoFile');
const dropzone = document.getElementById('dropzone');
const selectedFile = document.getElementById('selectedFile');
const selectedFileName = document.getElementById('selectedFileName');
const selectedFileSize = document.getElementById('selectedFileSize');
const removeVideo = document.getElementById('removeVideo');
const uploadButton = document.getElementById('uploadButton');
const uploadProgress = document.getElementById('uploadProgress');
const progressBar = document.getElementById('progressBar');
const progressText = document.getElementById('progressText');
const progressPercent = document.getElementById('progressPercent');
const progressNote = document.getElementById('progressNote');
const animeSelect = document.getElementById('animeSelect');
const animeStatus = document.getElementById('animeStatus');
const refreshAnime = document.getElementById('refreshAnime');
const videoTitle = document.getElementById('videoTitle');

function humanSize(bytes) {
  if (bytes === null || bytes === undefined) return '—';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let value = Number(bytes), i = 0;
  while (value >= 1024 && i < units.length - 1) { value /= 1024; i++; }
  return `${value.toFixed(i ? 2 : 0)} ${units[i]}`;
}

function showFile(file) {
  if (!file) { selectedFile.classList.add('hidden'); return; }
  selectedFileName.textContent = file.name;
  selectedFileSize.textContent = humanSize(file.size);
  selectedFile.classList.remove('hidden');
}

function useFile(file) {
  const dt = new DataTransfer();
  dt.items.add(file);
  fileInput.files = dt.files;
  showFile(file);
}

dropzone.addEventListener('click', () => fileInput.click());
dropzone.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); fileInput.click(); } });
['dragenter','dragover'].forEach(name => dropzone.addEventListener(name, e => { e.preventDefault(); dropzone.classList.add('dragging'); }));
['dragleave','drop'].forEach(name => dropzone.addEventListener(name, e => { e.preventDefault(); dropzone.classList.remove('dragging'); }));
dropzone.addEventListener('drop', e => { const f = e.dataTransfer.files[0]; if (f) useFile(f); });
fileInput.addEventListener('change', () => showFile(fileInput.files[0]));
removeVideo.addEventListener('click', () => { fileInput.value = ''; showFile(null); });

async function loadAnime() {
  animeStatus.textContent = 'Anime жагсаалт ачаалж байна...';
  refreshAnime.disabled = true;
  try {
    const res = await fetch('/api/admin/anime');
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Anime API error');
    const list = Array.isArray(data.results) ? data.results : [];
    animeSelect.innerHTML = '<option value="">Anime сонгох...</option>';
    list.forEach(anime => {
      const opt = document.createElement('option');
      opt.value = anime.id;
      opt.textContent = anime.name;
      opt.dataset.name = anime.name;
      animeSelect.appendChild(opt);
    });
    animeStatus.textContent = `${list.length} Anime ачааллаа.`;
  } catch (err) {
    animeStatus.textContent = `Anime list: ${err.message}`;
  } finally { refreshAnime.disabled = false; }
}

refreshAnime.addEventListener('click', loadAnime);
animeSelect.addEventListener('change', () => {
  const opt = animeSelect.options[animeSelect.selectedIndex];
  if (opt?.dataset?.name && !videoTitle.value.trim()) videoTitle.value = opt.dataset.name;
});

function clearResult() {
  document.getElementById('resultEmpty').classList.add('hidden');
  document.getElementById('resultSuccess').classList.add('hidden');
  document.getElementById('resultError').classList.add('hidden');
}
function errorResult(msg) {
  clearResult();
  document.getElementById('resultErrorText').textContent = msg;
  document.getElementById('resultError').classList.remove('hidden');
}
function successResult(data) {
  clearResult();
  const v = data.video || {}, d = data.django || {};
  document.getElementById('resultChannel').textContent = v.telegram_channel_id ?? '—';
  document.getElementById('resultMessage').textContent = v.telegram_message_id ?? '—';
  document.getElementById('resultFile').textContent = v.file_name || '—';
  document.getElementById('resultSize').textContent = humanSize(v.file_size);
  const state = document.getElementById('djangoSaveState');
  if (d.saved) state.textContent = 'Django / PostgreSQL хадгалсан';
  else if (!d.configured) state.textContent = 'Django callback тохируулаагүй';
  else state.textContent = 'Telegram OK · Django save failed';
  document.getElementById('resultSuccess').classList.remove('hidden');
}

form.addEventListener('submit', e => {
  e.preventDefault();
  if (!fileInput.files.length) { errorResult('Video file сонгоно уу.'); return; }
  clearResult();
  uploadButton.disabled = true;
  uploadProgress.classList.remove('hidden');
  progressBar.style.width = '0%'; progressPercent.textContent = '0%';
  progressText.textContent = 'Файлыг Flask руу илгээж байна...'; progressNote.textContent = 'Browser → Flask';

  const xhr = new XMLHttpRequest();
  xhr.open('POST', '/api/admin/upload-video');
  xhr.upload.onprogress = e => {
    if (!e.lengthComputable) return;
    const p = Math.round((e.loaded / e.total) * 100);
    progressBar.style.width = `${p}%`; progressPercent.textContent = `${p}%`;
    if (p >= 100) { progressText.textContent = 'Telegram руу upload хийж байна...'; progressNote.textContent = 'Flask → Telegram · response хүлээж байна'; }
  };
  xhr.onload = () => {
    uploadButton.disabled = false;
    let data;
    try { data = JSON.parse(xhr.responseText); } catch { errorResult(xhr.responseText || 'Invalid server response'); return; }
    if (xhr.status >= 200 && xhr.status < 300 && data.ok) {
      progressBar.style.width = '100%'; progressPercent.textContent = '100%'; progressText.textContent = 'Upload complete'; progressNote.textContent = 'Telegram upload дууслаа';
      successResult(data);
    } else errorResult(data.error || 'Upload failed');
  };
  xhr.onerror = () => { uploadButton.disabled = false; errorResult('Network error'); };
  xhr.send(new FormData(form));
});

loadAnime();
