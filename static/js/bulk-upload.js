// Bulk Upload Employees (HR Manager only)
// ---------------------------------------------------------------------------
function resetBulkUploadUI() {
  const fileInput=document.getElementById('bulkUploadFile');
  if(fileInput) fileInput.value='';
  document.getElementById('bulkUploadBtn').disabled=true;
  document.getElementById('bulkUploadResults').classList.add('hidden');
  document.getElementById('bulkUploadErrorList').innerHTML='';
  if(fileInput) fileInput.onchange=()=>{ document.getElementById('bulkUploadBtn').disabled=!fileInput.files.length; };
}

async function downloadBulkTemplate() {
  const res=await api('/api/employees/bulk-template');
  if(!res?.ok){ alert('Failed to download template'); return; }
  const blob=await res.blob();
  const url=URL.createObjectURL(blob);
  const a=document.createElement('a');
  a.href=url; a.download='employee-bulk-upload-template.csv';
  document.body.appendChild(a); a.click(); a.remove();
  URL.revokeObjectURL(url);
}

function readFileAsText(file) {
  return new Promise((resolve,reject)=>{
    const reader=new FileReader();
    reader.onload=()=>resolve(reader.result);
    reader.onerror=reject;
    reader.readAsText(file);
  });
}

function sleep(ms) { return new Promise(resolve => setTimeout(resolve, ms)); }

// Bulk upload runs as an async Celery task (202 + task_id) — poll
// GET /api/tasks/{task_id} until it leaves PENDING/STARTED, same pattern
// any async-task consumer in this app needs to follow.
async function pollBulkUploadTask(taskId) {
  const maxAttempts = 60; // ~60s at 1s intervals before giving up
  for (let attempt = 0; attempt < maxAttempts; attempt++) {
    const res = await api(`/api/tasks/${taskId}`);
    if (!res?.ok) throw new Error('Failed to check upload status');
    const status = await res.json();
    if (status.status === 'SUCCESS') return status.result;
    if (status.status === 'FAILURE') throw new Error(status.error || 'Bulk upload failed');
    await sleep(1000);
  }
  throw new Error('Bulk upload is taking longer than expected. Check back later or refresh.');
}

async function submitBulkUpload() {
  const fileInput=document.getElementById('bulkUploadFile');
  const file=fileInput.files[0];
  if(!file){ alert('Choose a CSV file first'); return; }
  const btn=document.getElementById('bulkUploadBtn');
  btn.disabled=true; btn.textContent='Uploading…';
  try {
    const csv_content=await readFileAsText(file);
    const res=await api('/api/employees/bulk-upload',{method:'POST',body:JSON.stringify({csv_content})});
    if(!res?.ok){
      let detail='Upload failed';
      try { detail=(await res.json()).detail||detail; } catch(_) {}
      alert(detail); return;
    }
    const { task_id } = await res.json();
    btn.textContent='Processing…';
    const result=await pollBulkUploadTask(task_id);
    renderBulkUploadResults(result);
    if(result.created.length || result.updated.length) { await loadEmployees(); }
  } catch (err) {
    alert(err.message || 'Upload failed');
  } finally {
    btn.disabled=false; btn.textContent='Upload';
  }
}

function renderBulkUploadResults(result) {
  document.getElementById('bulkUploadResults').classList.remove('hidden');
  const successEl=document.getElementById('bulkUploadSuccessCount');
  const parts=[`${result.created.length} employee${result.created.length==1?'':'s'} created`];
  if(result.updated.length) parts.push(`${result.updated.length} updated`);
  successEl.textContent=parts.join(', ');
  const errorEl=document.getElementById('bulkUploadErrorCount');
  if(result.errors.length){
    errorEl.textContent=`${result.errors.length} row${result.errors.length==1?'':'s'} failed`;
    errorEl.classList.remove('hidden');
  } else {
    errorEl.classList.add('hidden');
  }
  document.getElementById('bulkUploadErrorList').innerHTML=result.errors.length?result.errors.map(e=>{
    const who=[e.employee_id,e.full_name].filter(Boolean).join(' – ');
    return `
    <div class="flex items-start gap-2 text-sm bg-red-50 border border-red-100 rounded-lg px-3 py-2">
      <span class="font-semibold text-red-700 shrink-0">Row ${e.row}${who?` (${esc(who)})`:''}</span>
      <span class="text-red-600">${esc(e.reason)}</span>
    </div>`;
  }).join(''):'';
}
