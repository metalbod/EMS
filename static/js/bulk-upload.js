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
      const d=await res.json(); alert(d.detail||'Upload failed'); return;
    }
    const result=await res.json();
    renderBulkUploadResults(result);
    if(result.created.length) { await loadEmployees(); }
  } finally {
    btn.disabled=false; btn.textContent='Upload';
  }
}

function renderBulkUploadResults(result) {
  document.getElementById('bulkUploadResults').classList.remove('hidden');
  const successEl=document.getElementById('bulkUploadSuccessCount');
  successEl.textContent=`${result.created.length} employee${result.created.length==1?'':'s'} created`;
  const errorEl=document.getElementById('bulkUploadErrorCount');
  if(result.errors.length){
    errorEl.textContent=`${result.errors.length} row${result.errors.length==1?'':'s'} failed`;
    errorEl.classList.remove('hidden');
  } else {
    errorEl.classList.add('hidden');
  }
  document.getElementById('bulkUploadErrorList').innerHTML=result.errors.length?result.errors.map(e=>`
    <div class="flex items-start gap-2 text-sm bg-red-50 border border-red-100 rounded-lg px-3 py-2">
      <span class="font-semibold text-red-700 flex-shrink-0">Row ${e.row}</span>
      <span class="text-red-600">${esc(e.reason)}</span>
    </div>`).join(''):'';
}
