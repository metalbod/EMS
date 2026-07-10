// Payroll (Malaysia, salaried employees — Phase 1)
// ---------------------------------------------------------------------------
let payrollRunsCache=[];
let currentPayrollRunId=null;

function isPayrollManager() { return currentUser?.role==='payroll_manager'; }

const PAYROLL_STATUS_COLORS={'Draft':'bg-amber-100 text-amber-700','Finalized':'bg-green-100 text-green-700'};

function fmtMoney(n) { return 'RM ' + Number(n||0).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2}); }

// ---------------------------------------------------------------------------
// Payroll Runs (list)
// ---------------------------------------------------------------------------
async function loadPayrollRuns() {
  document.getElementById('newPayrollRunBtn').classList.toggle('hidden', !isPayrollManager());
  const listEl=document.getElementById('payrollRunList');
  const emptyEl=document.getElementById('payrollRunEmpty');
  listEl.innerHTML='<tr><td colspan="5" class="text-slate-400 text-sm text-center py-8">Loading…</td></tr>';
  const res=await api('/api/payroll/runs');
  const rows=res?.ok?await res.json():[];
  payrollRunsCache=rows;
  if(!rows.length){ listEl.innerHTML=''; emptyEl?.classList.remove('hidden'); return; }
  emptyEl?.classList.add('hidden');
  listEl.innerHTML=rows.map(r=>`
    <tr class="border-t border-slate-100 cursor-pointer hover:bg-slate-50 transition" onclick="openPayrollRunDetail(${r.id})">
      <td class="px-4 py-3 font-medium text-slate-800">${r.period_start} → ${r.period_end}</td>
      <td class="px-4 py-3"><span class="badge text-xs ${PAYROLL_STATUS_COLORS[r.status]||'bg-slate-100 text-slate-600'}">${r.status}</span></td>
      <td class="px-4 py-3 text-slate-600">${r.employee_count}</td>
      <td class="px-4 py-3 text-slate-600">${fmtMoney(r.total_net_pay)}</td>
      <td class="px-4 py-3 text-right text-slate-300"><svg class="w-4 h-4 inline" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"/></svg></td>
    </tr>`).join('');
}

function openPayrollRunModal() {
  document.getElementById('prStart').value='';
  document.getElementById('prEnd').value='';
  document.getElementById('payrollRunModal').classList.remove('hidden');
}
function closePayrollRunModal() { document.getElementById('payrollRunModal').classList.add('hidden'); }

async function submitPayrollRun() {
  const period_start=document.getElementById('prStart').value;
  const period_end=document.getElementById('prEnd').value;
  if(!period_start||!period_end){ alert('Both dates are required'); return; }
  const res=await api('/api/payroll/runs',{method:'POST',body:JSON.stringify({period_start,period_end})});
  if(res?.ok){
    closePayrollRunModal();
    const run=await res.json();
    loadPayrollRuns();
    openPayrollRunDetail(run.id);
  } else {
    const d=await res.json(); alert(d.detail||'Failed to create payroll run');
  }
}

// ---------------------------------------------------------------------------
// Payroll Run Detail (editable payslip table)
// ---------------------------------------------------------------------------
async function openPayrollRunDetail(runId) {
  currentPayrollRunId=runId;
  const res=await api(`/api/payroll/runs/${runId}`);
  if(!res?.ok) return;
  const run=await res.json();
  document.getElementById('prDetailTitle').textContent=`Payroll Run — ${run.period_start} → ${run.period_end}`;
  document.getElementById('prDetailMeta').innerHTML=`<span class="badge text-xs ${PAYROLL_STATUS_COLORS[run.status]||''}">${run.status}</span>`;
  const canEdit=isPayrollManager() && run.status==='Draft';
  document.getElementById('payrollRunDetailList').innerHTML=run.payslips.length?run.payslips.map(p=>{
    const hourly=p.salary_type==='Hourly';
    const basicCell=hourly
      ? `<span class="text-xs text-slate-500" title="Regular hours × hourly rate">${p.regular_hours}h reg.</span>`
      : (canEdit?`<input type="number" step="0.01" class="inp text-right text-xs" style="width:90px" value="${p.basic_salary}" id="ps-basic-${p.id}"/>`:fmtMoney(p.basic_salary));
    const unpaidCell=hourly
      ? `<span class="text-xs text-slate-500" title="Overtime hours × 1.5x rate">${p.overtime_hours}h OT</span>`
      : (canEdit?`<input type="number" step="0.5" min="0" class="inp text-right text-xs" style="width:70px" value="${p.unpaid_leave_days}" id="ps-unpaid-${p.id}"/>`:p.unpaid_leave_days);
    const actionCell=canEdit
      ? (hourly?`<button onclick="recomputePayslip(${p.id})" class="text-xs text-blue-600 hover:underline">Recompute</button>`
                :`<button onclick="saveAdjustedPayslip(${p.id})" class="text-xs text-blue-600 hover:underline">Save</button>`)
      : '';
    return `<tr class="border-t border-slate-100" data-payslip-id="${p.id}">
      <td class="px-3 py-2">
        <p class="font-medium text-slate-800 cursor-pointer hover:underline" onclick="viewPayslip(${p.id})">${esc(p.full_name)}</p>
        <p class="text-xs text-slate-400">${esc(p.department||'')}${p.designation?' · '+esc(p.designation):''}${hourly?' · Hourly':''}</p>
      </td>
      <td class="px-3 py-2 text-right">${basicCell}</td>
      <td class="px-3 py-2 text-right">${unpaidCell}</td>
      <td class="px-3 py-2 text-right text-slate-600">${fmtMoney(p.gross_pay)}</td>
      <td class="px-3 py-2 text-right text-slate-500">${fmtMoney(p.epf_employee)}</td>
      <td class="px-3 py-2 text-right text-slate-500">${fmtMoney(p.socso_employee)}</td>
      <td class="px-3 py-2 text-right text-slate-500">${fmtMoney(p.eis_employee)}</td>
      <td class="px-3 py-2 text-right text-slate-500">${fmtMoney(p.pcb)}</td>
      <td class="px-3 py-2 text-right font-semibold text-slate-800">${fmtMoney(p.net_pay)}</td>
      <td class="px-3 py-2 text-right">${actionCell}</td>
    </tr>`;
  }).join(''):'<tr><td colspan="10" class="text-center text-slate-400 text-sm py-8">No payslips in this run.</td></tr>';

  const actions=document.getElementById('payrollRunDetailActions');
  const btns=[];
  if(isPayrollManager() && run.status==='Draft'){
    btns.push(`<button onclick="finalizePayrollRun(${run.id})" class="btn-primary">Finalize Run</button>`);
    btns.push(`<button onclick="deletePayrollRun(${run.id})" class="btn-ghost text-red-600">Delete Run</button>`);
  }
  if(isPayrollManager() && run.status==='Finalized'){
    btns.push(`<button onclick="exportBankCsv(${run.id})" class="btn-primary">Export Bank CSV</button>`);
  }
  btns.push(`<button onclick="closePayrollRunDetailModal()" class="btn-ghost">Close</button>`);
  actions.innerHTML=btns.join('');

  document.getElementById('payrollRunDetailModal').classList.remove('hidden');
}
function closePayrollRunDetailModal() { document.getElementById('payrollRunDetailModal').classList.add('hidden'); }

async function saveAdjustedPayslip(payslipId) {
  const basic_salary=parseFloat(document.getElementById(`ps-basic-${payslipId}`).value);
  const unpaid_leave_days=parseFloat(document.getElementById(`ps-unpaid-${payslipId}`).value);
  const res=await api(`/api/payroll/payslips/${payslipId}`,{method:'PUT',body:JSON.stringify({basic_salary,unpaid_leave_days})});
  if(res?.ok){ openPayrollRunDetail(currentPayrollRunId); loadPayrollRuns(); }
  else { const d=await res.json(); alert(d.detail||'Failed to save'); }
}

async function recomputePayslip(payslipId) {
  const res=await api(`/api/payroll/payslips/${payslipId}/recompute`,{method:'PATCH'});
  if(res?.ok){ openPayrollRunDetail(currentPayrollRunId); loadPayrollRuns(); }
  else { const d=await res.json(); alert(d.detail||'Failed to recompute'); }
}

async function finalizePayrollRun(runId) {
  if(!confirm('Finalize this payroll run? Payslips will be locked and become visible to employees.')) return;
  const res=await api(`/api/payroll/runs/${runId}/finalize`,{method:'PATCH'});
  if(res?.ok){ openPayrollRunDetail(runId); loadPayrollRuns(); }
  else { const d=await res.json(); alert(d.detail||'Failed to finalize'); }
}

async function deletePayrollRun(runId) {
  if(!confirm('Delete this Draft payroll run and all its payslips?')) return;
  const res=await api(`/api/payroll/runs/${runId}`,{method:'DELETE'});
  if(res?.ok||res?.status===204){ closePayrollRunDetailModal(); loadPayrollRuns(); }
  else { const d=await res.json(); alert(d.detail||'Failed to delete'); }
}

async function exportBankCsv(runId) {
  const res=await api(`/api/payroll/runs/${runId}/bank-csv`);
  if(!res?.ok){ alert('Failed to export bank CSV'); return; }
  const blob=await res.blob();
  const url=URL.createObjectURL(blob);
  const a=document.createElement('a');
  a.href=url; a.download=`bank-file-run-${runId}.csv`;
  document.body.appendChild(a); a.click(); a.remove();
  URL.revokeObjectURL(url);
}

// ---------------------------------------------------------------------------
// My Payslips (self-service)
// ---------------------------------------------------------------------------
async function loadMyPayslips() {
  const listEl=document.getElementById('myPayslipList');
  const emptyEl=document.getElementById('myPayslipEmpty');
  listEl.innerHTML='<p class="text-slate-400 text-sm text-center py-8">Loading…</p>';
  const res=await api('/api/payroll/payslips/mine');
  const rows=res?.ok?await res.json():[];
  if(!rows.length){ listEl.innerHTML=''; emptyEl?.classList.remove('hidden'); return; }
  emptyEl?.classList.add('hidden');
  listEl.innerHTML=rows.map(p=>`
    <div class="bg-white border border-slate-200 rounded-xl p-4 cursor-pointer hover:shadow-sm transition flex items-center justify-between" onclick="viewPayslip(${p.id})">
      <div>
        <p class="font-medium text-slate-800">${p.period_start} → ${p.period_end}</p>
        <p class="text-xs text-slate-400">Net Pay: ${fmtMoney(p.net_pay)}</p>
      </div>
      <svg class="w-4 h-4 text-slate-300" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"/></svg>
    </div>`).join('');
}

// ---------------------------------------------------------------------------
// Payslip view/print
// ---------------------------------------------------------------------------
async function viewPayslip(payslipId) {
  const res=await api(`/api/payroll/payslips/${payslipId}`);
  if(!res?.ok){ alert('Failed to load payslip'); return; }
  const p=await res.json();
  document.getElementById('payslipContent').innerHTML=`
    <div class="mb-4">
      <p class="text-xs text-slate-400 uppercase tracking-wide">Payslip</p>
      <h3 class="text-lg font-semibold">${esc(p.full_name)}</h3>
      <p class="text-sm text-slate-500">${esc(p.designation||'')}${p.department?' · '+esc(p.department):''}</p>
      <p class="text-xs text-slate-400 mt-1">Period: ${p.period_start} → ${p.period_end}</p>
    </div>
    <table class="w-full text-sm mb-4">
      ${p.salary_type==='Hourly' ? `
      <tr class="border-t border-slate-100"><td class="py-1.5 text-slate-500">Regular Pay (${p.regular_hours}h)</td><td class="py-1.5 text-right">${fmtMoney(p.basic_salary)}</td></tr>
      <tr class="border-t border-slate-100"><td class="py-1.5 text-slate-500">Overtime Pay (${p.overtime_hours}h @ 1.5x)</td><td class="py-1.5 text-right">${fmtMoney(p.overtime_pay)}</td></tr>
      ` : `
      <tr class="border-t border-slate-100"><td class="py-1.5 text-slate-500">Basic Salary</td><td class="py-1.5 text-right">${fmtMoney(p.basic_salary)}</td></tr>
      <tr class="border-t border-slate-100"><td class="py-1.5 text-slate-500">Unpaid Leave (${p.unpaid_leave_days} day${p.unpaid_leave_days==1?'':'s'})</td><td class="py-1.5 text-right text-red-600">-${fmtMoney(p.unpaid_leave_deduction)}</td></tr>
      `}
      <tr class="border-t border-slate-200 font-medium"><td class="py-1.5">Gross Pay</td><td class="py-1.5 text-right">${fmtMoney(p.gross_pay)}</td></tr>
      <tr class="border-t border-slate-100"><td class="py-1.5 text-slate-500">EPF (Employee 11%)</td><td class="py-1.5 text-right text-red-600">-${fmtMoney(p.epf_employee)}</td></tr>
      <tr class="border-t border-slate-100"><td class="py-1.5 text-slate-500">SOCSO (Employee)</td><td class="py-1.5 text-right text-red-600">-${fmtMoney(p.socso_employee)}</td></tr>
      <tr class="border-t border-slate-100"><td class="py-1.5 text-slate-500">EIS (Employee)</td><td class="py-1.5 text-right text-red-600">-${fmtMoney(p.eis_employee)}</td></tr>
      <tr class="border-t border-slate-100"><td class="py-1.5 text-slate-500">PCB (Income Tax)</td><td class="py-1.5 text-right text-red-600">-${fmtMoney(p.pcb)}</td></tr>
      <tr class="border-t-2 border-slate-300 font-semibold text-base"><td class="py-2">Net Pay</td><td class="py-2 text-right">${fmtMoney(p.net_pay)}</td></tr>
    </table>
    <table class="w-full text-xs text-slate-400 border-t border-slate-100 pt-2">
      <tr><td class="py-1">Employer EPF</td><td class="py-1 text-right">${fmtMoney(p.epf_employer)}</td></tr>
      <tr><td class="py-1">Employer SOCSO</td><td class="py-1 text-right">${fmtMoney(p.socso_employer)}</td></tr>
      <tr><td class="py-1">Employer EIS</td><td class="py-1 text-right">${fmtMoney(p.eis_employer)}</td></tr>
    </table>
    <p class="text-xs text-slate-400 mt-4">Bank: ${esc(p.bank_name||'—')} · ${esc(p.bank_account||'—')}</p>
  `;
  document.getElementById('payslipViewModal').classList.remove('hidden');
}
function closePayslipViewModal() { document.getElementById('payslipViewModal').classList.add('hidden'); }
