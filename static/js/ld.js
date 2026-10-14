// Learning & Development
// ---------------------------------------------------------------------------
let ldCoursesCache=[], ldCatFilter='', ldEnrollFilter='', ldEnrollData=[];
// Sort-only, like the Projects list (timesheet.js) — the catalog has no
// pagination UI, and an institution's course count is small enough that
// showing everything at once (rather than paging) matches how the rest
// of L&D's own tables (My Trainings, below) already behave.
const ldCourseList = createListState({ sortKey: 'title', pageSize: Number.MAX_SAFE_INTEGER });
const LD_COURSE_COLUMNS = [
  { key:'title', label:'Course', sortKey:'title' },
  { key:'category', label:'Category', sortKey:'category' },
  { key:'cost', label:'Cost', sortKey:'cost' },
];
const ldEnrollList = createListState({
  sortKey: 'employee_name',
  pageSize: Number.MAX_SAFE_INTEGER,
  sortValue: (en, key) => key === 'progress' ? (en.module_count > 0 ? en.modules_viewed / en.module_count : -1)
    : key === 'score' ? (en.best_score ?? -1) : en[key],
});
const LD_ENROLL_COLUMNS = [
  { key:'employee_name', label:'Employee', sortKey:'employee_name' },
  { key:'department', label:'Department', sortKey:'department' },
  { key:'course_title', label:'Course', sortKey:'course_title' },
  { key:'course_category', label:'Category', sortKey:'course_category' },
  { key:'status', label:'Status', sortKey:'status' },
  { key:'progress', label:'Progress', sortKey:'progress' },
  { key:'score', label:'Quiz Score', sortKey:'score' },
  { key:'created_at', label:'Requested', sortKey:'created_at' },
  { key:'completed_at', label:'Completed', sortKey:'completed_at' },
];
const LD_CATEGORY_LABELS={mandatory:'Mandatory',professional_development:'Professional Dev',certification:'Certification'};
const LD_CATEGORY_COLORS={mandatory:'bg-red-100 text-red-700',professional_development:'bg-blue-100 text-blue-700',certification:'bg-purple-100 text-purple-700'};
const LD_STATUS_COLORS={'Pending Approval':'status-pending','Approved':'status-info','Rejected':'status-negative','In Progress':'status-info','Completed':'status-positive'};

async function loadLdCourses() {
  // Policies chip: HR and managers only (managers see their own team's status). Under it the
  // course table gives way to the policy table.
  document.getElementById('ldPolicyChip')?.classList.toggle('hidden',!HR_AND_MANAGER_ROLES.includes(currentUser?.role));
  const showPolicies=ldCatFilter==='policy';
  document.getElementById('ldCourseTableWrap')?.classList.toggle('hidden',showPolicies);
  document.getElementById('ldPolicyWrap')?.classList.toggle('hidden',!showPolicies);
  if(showPolicies){ document.getElementById('ldCourseEmpty')?.classList.add('hidden'); loadLdPolicies(); return; }
  const bodyEl=document.getElementById('ldCourseTableBody');
  const emptyEl=document.getElementById('ldCourseEmpty');
  bodyEl.innerHTML='<tr><td colspan="4" class="text-slate-400 text-sm text-center py-8">Loading…</td></tr>';
  let url='/api/ld/courses';
  if(ldCatFilter) url+=`?category=${encodeURIComponent(ldCatFilter)}`;
  const res=await api(url);
  ldCoursesCache=res&&res.ok?await res.json():[];
  renderLdCourseTable();
}

function setLdCourseSort(key) { ldCourseList.setSort(key); renderLdCourseTable(); }

function renderLdCourseTableHead() {
  document.getElementById('ldCourseTableHead').innerHTML = LD_COURSE_COLUMNS.map(c =>
    `<th class="text-left px-4 py-2.5 text-xs font-semibold text-slate-500 uppercase tracking-wide cursor-pointer select-none whitespace-nowrap" onclick="setLdCourseSort('${c.sortKey}')">${esc(c.label)}<span class="ld-course-sort-arrow" data-sort-key="${c.sortKey}"></span></th>`
  ).join('') + `<th class="px-4 py-2.5"></th>`;
}

function renderLdCourseTable() {
  const bodyEl=document.getElementById('ldCourseTableBody');
  const emptyEl=document.getElementById('ldCourseEmpty');
  renderLdCourseTableHead();
  ldCourseList.updateSortArrows('.ld-course-sort-arrow');
  if(!ldCoursesCache.length){bodyEl.innerHTML='';emptyEl?.classList.remove('hidden');return;}
  emptyEl?.classList.add('hidden');
  const canManage=HR_MANAGE_ROLES.includes(currentUser?.role);
  const { pageItems } = ldCourseList.view(ldCoursesCache);
  bodyEl.innerHTML=pageItems.map(c=>`
    <tr class="border-t border-slate-100">
      <td class="px-4 py-3">
        <p class="font-medium text-slate-800">${esc(c.title)}${c.file_count?` <span class="badge text-xs bg-slate-100 text-slate-600 align-middle" title="Downloadable documents in this course">📎 ${c.file_count}</span>`:''}</p>
        <p class="text-xs text-slate-400 line-clamp-1">${esc(c.description||'')}</p>
      </td>
      <td class="px-4 py-3 whitespace-nowrap"><span class="badge text-xs ${statusColor(LD_CATEGORY_COLORS, c.category)}">${LD_CATEGORY_LABELS[c.category]||c.category}</span></td>
      <td class="px-4 py-3 whitespace-nowrap font-medium ${c.cost>0?'text-amber-600':'text-green-600'}">${c.cost>0?fmtCurrency(c.cost):'Free'}</td>
      <td class="px-4 py-3 text-right whitespace-nowrap">
        <div class="flex items-center justify-end gap-2">
          ${canManage?`<div class="flex items-center gap-1">
            <button onclick="openLdModulesModal(${c.id})" class="text-slate-300 hover:text-green-600" title="Course Content"><svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s4.832.477 6 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.746 0 3.332.477 4.5 1.253v13C19.832 18.477 18.246 18 16.5 18c-1.746 0-3.332.477-4.5 1.253"/></svg></button>
            <button onclick="openLdQuizModal(${c.id})" class="text-slate-300 hover:text-purple-500" title="Manage Quiz"><svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/></svg></button>
            <button onclick="openLdCourseModal(${c.id})" class="text-slate-300 hover:text-blue-500" title="Edit"><svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"/></svg></button>
            <button onclick="deleteLdCourse(${c.id})" class="text-slate-300 hover:text-red-500" title="Remove"><svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg></button>
          </div>
          <button onclick="openLdPreviewQuizModal(${c.id})" class="btn-ghost text-xs px-3 py-1.5 border border-slate-200">Preview</button>`:''}
          <button onclick="openLdEnrollModal(${c.id})" class="btn-primary text-xs px-3 py-1.5">Enroll</button>
        </div>
      </td>
    </tr>`).join('');
}

function setLdCatFilter(cat) {
  ldCatFilter=cat;
  document.querySelectorAll('.ld-cat-filter-btn').forEach(b=>b.classList.remove('ld-cat-filter-active'));
  event?.target?.classList?.add('ld-cat-filter-active');
  loadLdCourses();
}

function openLdCourseModal(courseId) {
  const form=document.getElementById('ldCourseModal').querySelector('form');
  form.reset();
  document.getElementById('ldCourseId').value=courseId||'';
  document.getElementById('ldCourseModalTitle').textContent=courseId?'Edit Course':'Add Course';
  if(courseId){
    const c=ldCoursesCache.find(x=>x.id===courseId);
    if(c){
      document.getElementById('ldCourseTitle').value=c.title;
      document.getElementById('ldCourseCategory').value=c.category;
      document.getElementById('ldCourseDesc').value=c.description||'';
      document.getElementById('ldCourseCost').value=c.cost;
    }
  }
  document.getElementById('ldCourseModal').classList.remove('hidden');
}

function closeLdCourseModal() {
  document.getElementById('ldCourseModal').classList.add('hidden');
}

async function submitLdCourse(e) {
  e.preventDefault();
  const id=document.getElementById('ldCourseId').value;
  const body={
    title:document.getElementById('ldCourseTitle').value.trim(),
    category:document.getElementById('ldCourseCategory').value,
    description:document.getElementById('ldCourseDesc').value.trim()||null,
    cost:parseFloat(document.getElementById('ldCourseCost').value)||0,
  };
  const url=id?`/api/ld/courses/${id}`:'/api/ld/courses';
  const res=await api(url,{method:id?'PUT':'POST',body:JSON.stringify(body)});
  if(res?.ok){closeLdCourseModal();loadLdCourses();}
}

async function deleteLdCourse(courseId) {
  if(!confirm('Remove this course from the catalog?')) return;
  await api(`/api/ld/courses/${courseId}`,{method:'DELETE'});
  loadLdCourses();
}

function openLdEnrollModal(courseId) {
  document.getElementById('ldEnrollCourseId').value=courseId;
  document.getElementById('ldEnrollNotes').value='';
  const course=ldCoursesCache.find(c=>c.id===courseId);
  const costNote=document.getElementById('ldEnrollCostNote');
  if(course && course.cost>0){
    costNote.textContent=`This course costs ${fmtCurrency(course.cost)} — enrollment will require manager/HR approval before starting.`;
    costNote.classList.remove('hidden');
  } else {
    costNote.classList.add('hidden');
  }
  const empWrap=document.getElementById('ldEnrollEmpWrap');
  const empSel=document.getElementById('ldEnrollEmpId');
  const canManage=HR_AND_MANAGER_ROLES.includes(currentUser?.role);
  if(canManage){
    empWrap.classList.remove('hidden');
    empSel.required=true;
    empSel.innerHTML=employees.filter(e=>e.status==='Active').map(e=>`<option value="${e.employee_id}">${e.employee_id} — ${esc(displayName(e.full_name,e.preferred_name))}</option>`).join('');
    if(currentUser?.employee_id) empSel.value=currentUser.employee_id;
    initEmployeeSearchSelect('ldEnrollEmpId', 'Search employee…');
  } else {
    empWrap.classList.add('hidden');
    // See static/js/leave.js's identical fix: a `required` field left
    // hidden-but-not-display:none by initEmployeeSearchSelect silently
    // blocks native form submission for every role that doesn't see it —
    // a plain employee self-enrolling would click Enroll and see nothing
    // happen at all.
    empSel.required=false;
  }
  document.getElementById('ldEnrollModal').classList.remove('hidden');
}

function closeLdEnrollModal() {
  document.getElementById('ldEnrollModal').classList.add('hidden');
}

async function submitLdEnroll(e) {
  e.preventDefault();
  const courseId=parseInt(document.getElementById('ldEnrollCourseId').value);
  const canManage=HR_AND_MANAGER_ROLES.includes(currentUser?.role);
  const employeeId=canManage?document.getElementById('ldEnrollEmpId').value:currentUser?.employee_id;
  if(!employeeId){alert('No employee selected.');return;}
  const res=await api('/api/ld/enrollments',{method:'POST',body:JSON.stringify({
    employee_id:employeeId, course_id:courseId,
    notes:document.getElementById('ldEnrollNotes').value.trim()||null
  })});
  if(res?.ok){
    closeLdEnrollModal();
    showPage('ld-trainings');
  } else {
    const d=await res.json();
    alert(d.detail||'Failed to enroll');
  }
}

// What a quiz-score cell says for an enrolment row (from GET /api/ld/enrollments or /api/employees/{id}/ld-courses).
// Pure so it is unit-tested. tone: 'pass' | 'fail' | 'none'.
function ldScoreSummary(row) {
  if(!row.quiz_id) return {label:'—', detail:'', tone:'none', clickable:false};
  const used=row.attempts_used||0, max=row.quiz_max_attempts;
  if(!used) return {label:'Not attempted', detail:max?`${max} ${max===1?'attempt':'attempts'} allowed`:'', tone:'none', clickable:false};
  if(row.passed_any) return {label:`${row.best_score}% · Passed`, detail:`${used} of ${max} ${max===1?'attempt':'attempts'} used`, tone:'pass', clickable:true};
  const left=Math.max(0,(max||0)-used);
  return {label:`${row.best_score}% · Not passed`, detail:left>0?`${left} ${left===1?'attempt':'attempts'} left`:'No attempts left', tone:'fail', clickable:true};
}
function ldScoreCellHtml(row) {
  const s=ldScoreSummary(row);
  if(s.tone==='none') return `<span class="text-slate-400 text-xs">${esc(s.label)}</span>`;
  const colour=s.tone==='pass'?'text-green-700':'text-red-600';
  return `<button onclick="openLdAttemptsModal(${row.id})" class="text-left hover:underline" title="See every attempt">
    <span class="font-medium ${colour}">${esc(s.label)}</span><span class="block text-xs text-slate-400">${esc(s.detail)}</span></button>`;
}

async function openLdAttemptsModal(enrollmentId) {
  const res=await api(`/api/ld/enrollments/${enrollmentId}/quiz-attempts`);
  if(!res?.ok){ const d=await res?.json().catch(()=>null); alert(d?.detail?apiErrorText(d.detail):'Could not load the scores.'); return; }
  const d=await res.json();
  document.getElementById('ldAttemptsTitle').textContent=`${d.course_title} — quiz scores`;
  document.getElementById('ldAttemptsSub').textContent=
    `${displayName(d.employee_name,d.employee_preferred_name)||d.employee_id}${d.quiz?` · Pass mark ${d.quiz.pass_threshold}% · ${d.quiz.max_attempts} attempts allowed`:''}`;
  document.getElementById('ldAttemptsEmpty').classList.toggle('hidden',d.attempts.length>0);
  document.getElementById('ldAttemptsBody').innerHTML=d.attempts.map(a=>`<tr class="border-t border-slate-100">
    <td class="px-4 py-2.5">${a.attempt_number}</td>
    <td class="px-4 py-2.5 text-slate-600 whitespace-nowrap">${fmtDateTime(a.submitted_at)}</td>
    <td class="px-4 py-2.5 font-medium">${a.score}%</td>
    <td class="px-4 py-2.5"><span class="badge text-xs ${a.passed?'status-positive':'status-negative'}">${a.passed?'Passed':'Not passed'}</span></td>
  </tr>`).join('');
  document.getElementById('ldAttemptsNote').textContent=d.quiz?'The pass mark shown is the quiz\'s current one. If HR changed the pass mark or the questions since, earlier attempts were scored against the old ones.':'';
  document.getElementById('ldAttemptsModal').classList.remove('hidden');
}
function closeLdAttemptsModal() { document.getElementById('ldAttemptsModal').classList.add('hidden'); }

// Employee profile → Learning tab
async function loadEmployeeLearning(employeeId) {
  const body=document.getElementById('employeeLearningBody'), empty=document.getElementById('employeeLearningEmpty');
  body.innerHTML='<tr><td colspan="4" class="text-slate-400 text-sm text-center py-6">Loading…</td></tr>';
  const res=await api(`/api/employees/${encodeURIComponent(employeeId)}/ld-courses`);
  const rows=res?.ok?await res.json():[];
  empty.classList.toggle('hidden',rows.length>0);
  body.innerHTML=rows.map(r=>`<tr class="border-t border-slate-100">
    <td class="px-4 py-3"><p class="font-medium text-slate-800">${esc(r.course_title)}</p><p class="text-xs text-slate-400">${esc(LD_CATEGORY_LABELS[r.course_category]||r.course_category)}</p></td>
    <td class="px-4 py-3 whitespace-nowrap"><span class="badge text-xs ${statusColor(LD_STATUS_COLORS,r.status)}">${esc(r.status)}</span></td>
    <td class="px-4 py-3 text-slate-600 whitespace-nowrap">${r.completed_at?fmtDate(r.completed_at):'—'}</td>
    <td class="px-4 py-3 whitespace-nowrap">${ldScoreCellHtml(r)}</td>
  </tr>`).join('');
}

async function loadLdEnrollments() {
  const bodyEl=document.getElementById('ldEnrollTableBody');
  const emptyEl=document.getElementById('ldEnrollmentEmpty');
  bodyEl.innerHTML='<tr><td colspan="10" class="text-slate-400 text-sm text-center py-8">Loading…</td></tr>';
  let url='/api/ld/enrollments';
  if(ldEnrollFilter) url+=`?status=${encodeURIComponent(ldEnrollFilter)}`;
  const res=await api(url);
  ldEnrollData=res&&res.ok?await res.json():[];
  loadLdMyPolicies();
  const focusId=pendingFocusId('ld-trainings');
  if(focusId) ldEnrollList.showItem(ldEnrollData, en=>String(en.id)===focusId);
  renderLdEnrollTable();
  applyFocus('ld-trainings');
}

function setLdSort(key) { ldEnrollList.setSort(key); renderLdEnrollTable(); }

function renderLdEnrollTableHead() {
  document.getElementById('ldEnrollTableHead').innerHTML = LD_ENROLL_COLUMNS.map(c =>
    `<th class="text-left px-4 py-2.5 text-xs font-semibold text-slate-500 uppercase tracking-wide cursor-pointer select-none whitespace-nowrap" onclick="setLdSort('${c.sortKey}')">${esc(c.label)}<span class="ld-sort-arrow" data-sort-key="${c.sortKey}"></span></th>`
  ).join('') + `<th class="px-4 py-2.5"></th>`;
}

function renderLdEnrollTable() {
  const bodyEl=document.getElementById('ldEnrollTableBody');
  const emptyEl=document.getElementById('ldEnrollmentEmpty');
  renderLdEnrollTableHead();
  ldEnrollList.updateSortArrows('.ld-sort-arrow');
  if(!ldEnrollData.length){bodyEl.innerHTML='';emptyEl?.classList.remove('hidden');return;}
  emptyEl?.classList.add('hidden');
  const canApprove=HR_AND_MANAGER_ROLES.includes(currentUser?.role);
  const { pageItems } = ldEnrollList.view(ldEnrollData);
  bodyEl.innerHTML=pageItems.map(en=>{
    const isSelf = currentUser?.role!=='employee' || currentUser?.employee_id===en.employee_id;
    const isOwnEmployeeAccount = currentUser?.role==='employee' && currentUser?.employee_id===en.employee_id;
    const canAct = en.status==='In Progress' && isSelf;
    const hasQuiz = !!en.quiz_id;
    return `<tr class="border-t border-slate-100" data-focus-id="${en.id}">
      <td class="px-4 py-3 font-medium text-slate-800 whitespace-nowrap">${esc(displayName(en.employee_name,en.employee_preferred_name))}</td>
      <td class="px-4 py-3 text-slate-600 whitespace-nowrap">${esc(en.department||'—')}</td>
      <td class="px-4 py-3">
        <p class="text-slate-800">${esc(en.course_title)}</p>
        ${hasQuiz?`<span class="badge text-xs bg-purple-100 text-purple-700 mt-1 inline-block">Quiz Required</span>`:''}
      </td>
      <td class="px-4 py-3 whitespace-nowrap"><span class="badge text-xs ${statusColor(LD_CATEGORY_COLORS, en.course_category)}">${LD_CATEGORY_LABELS[en.course_category]||en.course_category}</span></td>
      <td class="px-4 py-3 whitespace-nowrap"><span class="badge ${statusColor(LD_STATUS_COLORS, en.status)}">${en.status}</span></td>
      <td class="px-4 py-3 text-slate-600 whitespace-nowrap">${en.module_count>0?`${en.modules_viewed}/${en.module_count} lessons`:'—'}</td>
      <td class="px-4 py-3 whitespace-nowrap">${ldScoreCellHtml(en)}</td>
      <td class="px-4 py-3 text-slate-600 whitespace-nowrap">${fmtDate(en.created_at)}</td>
      <td class="px-4 py-3 text-slate-600 whitespace-nowrap">${en.completed_at?fmtDate(en.completed_at):'—'}</td>
      <td class="px-4 py-3 text-right whitespace-nowrap">
        ${en.status==='Pending Approval'&&canApprove?`
          <button onclick="updateLdEnrollStatus(${en.id},'Approved')" class="btn-primary text-xs px-3 py-1.5">Approve</button>
          <button onclick="updateLdEnrollStatus(${en.id},'Rejected')" class="btn-ghost text-xs px-3 py-1.5 text-red-600">Reject</button>
        `:''}
        ${en.status!=='Pending Approval'&&en.status!=='Rejected'&&en.module_count>0?`<button onclick="openLdViewerModal(${en.course_id},${en.id},'${esc(en.course_title).replace(/'/g,"\\'")}')" class="btn-ghost text-xs px-3 py-1.5 border border-slate-200">View Course</button>`:''}
        ${en.status==='In Progress'&&hasQuiz&&isOwnEmployeeAccount?`<button onclick="openLdTakeQuizModal(${en.course_id},${en.id})" class="btn-primary text-xs px-3 py-1.5">Take Quiz</button>`:''}
        ${en.status==='In Progress'&&hasQuiz&&!isOwnEmployeeAccount?`<span class="text-xs text-slate-400 italic">Awaiting employee to take quiz</span>`:''}
        ${canAct&&!hasQuiz?`<button onclick="updateLdEnrollStatus(${en.id},'Completed')" class="btn-primary text-xs px-3 py-1.5">Mark Complete</button>`:''}
      </td>
    </tr>`;
  }).join('');
}

function setLdEnrollFilter(status) {
  ldEnrollFilter=status;
  document.querySelectorAll('.ld-enr-filter-btn').forEach(b=>b.classList.remove('ld-enr-filter-active'));
  event?.target?.classList?.add('ld-enr-filter-active');
  loadLdEnrollments();
}

async function updateLdEnrollStatus(enrId, status) {
  const res=await api(`/api/ld/enrollments/${enrId}/status`,{method:'PATCH',body:JSON.stringify({status})});
  if(res?.ok) loadLdEnrollments();
}

// ---------------------------------------------------------------------------
// Quiz Builder (HR)
// ---------------------------------------------------------------------------
let ldQuizQuestionCount=0;

async function openLdQuizModal(courseId) {
  document.getElementById('ldQuizCourseId').value=courseId;
  document.getElementById('ldQuizQuestions').innerHTML='';
  ldQuizQuestionCount=0;
  document.getElementById('ldQuizTitle').value='';
  document.getElementById('ldQuizPassThreshold').value=80;
  document.getElementById('ldQuizMaxAttempts').value=3;
  document.getElementById('ldQuizRandomizeQuestions').checked=false;
  document.getElementById('ldQuizRandomizeOptions').checked=false;
  document.getElementById('ldQuizDeleteBtn').classList.add('hidden');

  const res=await api(`/api/ld/courses/${courseId}/quiz/manage`);
  if(res?.ok){
    const quiz=await res.json();
    document.getElementById('ldQuizTitle').value=quiz.title;
    document.getElementById('ldQuizPassThreshold').value=quiz.pass_threshold;
    document.getElementById('ldQuizMaxAttempts').value=quiz.max_attempts;
    document.getElementById('ldQuizRandomizeQuestions').checked=!!quiz.randomize_questions;
    document.getElementById('ldQuizRandomizeOptions').checked=!!quiz.randomize_options;
    document.getElementById('ldQuizDeleteBtn').classList.remove('hidden');
    quiz.questions.forEach(q=>addLdQuizQuestion(q.question_text, q.options, q.question_type));
  } else {
    addLdQuizQuestion();
  }
  document.getElementById('ldQuizModal').classList.remove('hidden');
}

function closeLdQuizModal() {
  document.getElementById('ldQuizModal').classList.add('hidden');
}

function addLdQuizQuestion(questionText, options, questionType) {
  const idx=ldQuizQuestionCount++;
  const opts=options || [{text:'',is_correct:true},{text:'',is_correct:false}];
  const qtype=questionType||'single';
  const wrap=document.createElement('div');
  wrap.id=`ldQ-${idx}`;
  wrap.dataset.qtype=qtype;
  wrap.className='border border-slate-200 rounded-xl p-4';
  wrap.innerHTML=`
    <div class="flex items-start gap-2 mb-2">
      <input class="inp ldq-text flex-1" placeholder="Question text…" value="${esc(questionText||'')}"/>
      <button type="button" onclick="document.getElementById('ldQ-${idx}').remove()" class="text-slate-300 hover:text-red-500 mt-1.5" title="Remove question"><svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg></button>
    </div>
    <label class="flex items-center gap-2 text-xs text-slate-500 mb-2 cursor-pointer">
      <input type="checkbox" class="ldq-multi-toggle" ${qtype==='multi'?'checked':''} onchange="ldToggleQuestionType(${idx},this.checked)"/> Multiple correct answers
    </label>
    <div class="ldq-options space-y-2">
      ${opts.map((o,i)=>`
        <div class="flex items-center gap-2">
          <input type="${qtype==='multi'?'checkbox':'radio'}" name="ldq-correct-${idx}" class="ldq-correct" ${o.is_correct?'checked':''}/>
          <input class="inp ldq-option-text flex-1 text-sm" placeholder="Option text…" value="${esc(o.text||'')}"/>
          <button type="button" onclick="this.parentElement.remove()" class="text-slate-300 hover:text-red-500" title="Remove option"><svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg></button>
        </div>`).join('')}
    </div>
    <button type="button" onclick="addLdQuizOption(${idx})" class="text-xs text-blue-600 hover:text-blue-700 mt-2">+ Add Option</button>
  `;
  document.getElementById('ldQuizQuestions').appendChild(wrap);
}

function ldToggleQuestionType(idx, isMulti) {
  const wrap=document.getElementById(`ldQ-${idx}`);
  wrap.dataset.qtype=isMulti?'multi':'single';
  wrap.querySelectorAll('.ldq-correct').forEach(el=>{
    const checked=el.checked;
    el.type=isMulti?'checkbox':'radio';
    el.checked=checked;
  });
  if(!isMulti){
    // Switching back to single-answer: keep only the first checked option
    const checked=[...wrap.querySelectorAll('.ldq-correct')].filter(el=>el.checked);
    checked.slice(1).forEach(el=>el.checked=false);
  }
}

function addLdQuizOption(idx) {
  const wrap=document.getElementById(`ldQ-${idx}`);
  const optsEl=wrap.querySelector('.ldq-options');
  const isMulti=wrap.dataset.qtype==='multi';
  const div=document.createElement('div');
  div.className='flex items-center gap-2';
  div.innerHTML=`
    <input type="${isMulti?'checkbox':'radio'}" name="ldq-correct-${idx}" class="ldq-correct"/>
    <input class="inp ldq-option-text flex-1 text-sm" placeholder="Option text…"/>
    <button type="button" onclick="this.parentElement.remove()" class="text-slate-300 hover:text-red-500" title="Remove option"><svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg></button>
  `;
  optsEl.appendChild(div);
}

const submitLdQuiz = guardAsync(async function() {
  const courseId=document.getElementById('ldQuizCourseId').value;
  const title=document.getElementById('ldQuizTitle').value.trim();
  if(!title){alert('Quiz title is required');return;}
  const questions=[...document.querySelectorAll('#ldQuizQuestions > div')].map(qEl=>{
    const question_text=qEl.querySelector('.ldq-text').value.trim();
    const question_type=qEl.dataset.qtype==='multi'?'multi':'single';
    const options=[...qEl.querySelectorAll('.ldq-options > div')].map(oEl=>({
      text: oEl.querySelector('.ldq-option-text').value.trim(),
      is_correct: oEl.querySelector('.ldq-correct').checked
    })).filter(o=>o.text);
    return {question_text, question_type, options};
  }).filter(q=>q.question_text && q.options.length>=2);

  if(!questions.length){alert('Add at least one question with at least 2 options.');return;}
  for(const q of questions){
    const correctCount=q.options.filter(o=>o.is_correct).length;
    if(correctCount===0){alert(`Mark a correct answer for: "${q.question_text}"`);return;}
    if(q.question_type==='single'&&correctCount>1){alert(`"${q.question_text}" is single-answer but has multiple correct options marked. Check "Multiple correct answers" if that's intended.`);return;}
  }

  const body={
    title,
    pass_threshold: parseInt(document.getElementById('ldQuizPassThreshold').value)||80,
    max_attempts: parseInt(document.getElementById('ldQuizMaxAttempts').value)||3,
    randomize_questions: document.getElementById('ldQuizRandomizeQuestions').checked,
    randomize_options: document.getElementById('ldQuizRandomizeOptions').checked,
    questions
  };
  const res=await api(`/api/ld/courses/${courseId}/quiz`,{method:'PUT',body:JSON.stringify(body)});
  if(res?.ok){closeLdQuizModal();loadLdCourses();}
  else{const d=await res.json();alert(d.detail||'Failed to save quiz');}
});

async function deleteLdQuiz() {
  if(!confirm('Remove this quiz? Employees will be able to mark the course complete manually instead.')) return;
  const courseId=document.getElementById('ldQuizCourseId').value;
  await api(`/api/ld/courses/${courseId}/quiz`,{method:'DELETE'});
  closeLdQuizModal();
  loadLdCourses();
}

// ---------------------------------------------------------------------------
// Quiz Taking (Employee)
// ---------------------------------------------------------------------------
// What the employee is told after submitting: the score against the pass mark, whether they passed, and — if
// not — exactly why they have to retake and how many tries are left. Pure so it is unit-tested.
// `numberOf(questionId)` maps a question id to the number shown beside it.
function ldQuizOutcome(r, numberOf) {
  const scoreLine=`You scored ${r.score}% (${r.correct} of ${r.total} correct). The pass mark is ${r.pass_threshold}%.`;
  if(r.passed) return {passed:true, headline:'Passed', lines:[scoreLine, 'This course is now marked complete.'], canRetake:false};
  const wrong=(r.incorrect_question_ids||[]).map(id=>numberOf?numberOf(id):id).filter(n=>n!=null).sort((a,b)=>a-b);
  const lines=[scoreLine, `You needed at least ${r.required_correct} of ${r.total} correct to pass, so you will need to retake the quiz.`];
  if(wrong.length) lines.push(`Questions to review: ${wrong.join(', ')}.`);
  lines.push(r.attempts_remaining>0
    ? `Attempt ${r.attempt_number} of ${r.max_attempts} used — you have ${r.attempts_remaining} ${r.attempts_remaining===1?'attempt':'attempts'} left.`
    : `You have used all ${r.max_attempts} ${r.max_attempts===1?'attempt':'attempts'}. Please contact HR to arrange another attempt.`);
  return {passed:false, headline:'Not passed', lines, canRetake:r.attempts_remaining>0};
}

async function openLdTakeQuizModal(courseId, enrollmentId) {
  const res=await api(`/api/ld/courses/${courseId}/quiz`);
  if(!res?.ok){alert('Could not load quiz.');return;}
  const quiz=await res.json();
  document.getElementById('ldTakeQuizId').value=quiz.id;
  document.getElementById('ldTakeQuizEnrollId').value=enrollmentId;
  document.getElementById('ldTakeQuizCourseId').value=courseId;
  document.getElementById('ldTakeQuizTitle').textContent=quiz.title;
  document.getElementById('ldTakeQuizIntro').textContent=
    `${quiz.questions.length} question${quiz.questions.length===1?'':'s'} · Pass mark ${quiz.pass_threshold}% · Attempt ${(quiz.attempts_used||0)+1} of ${quiz.max_attempts}`;
  document.getElementById('ldTakeQuizResult').classList.add('hidden');
  document.getElementById('ldTakeQuizSubmitBtn').classList.remove('hidden');
  document.getElementById('ldTakeQuizQuestions').innerHTML=quiz.questions.map((q,i)=>{
    const isMulti=q.question_type==='multi';
    return `<div data-qid="${q.id}" data-qnum="${i+1}" data-qtype="${isMulti?'multi':'single'}">
      <p class="text-sm font-medium text-slate-800 mb-1"><span class="text-slate-500">${i+1}.</span> ${esc(q.question_text)}<span class="ldtq-flag hidden ml-2 text-xs font-medium text-red-600">Incorrect</span></p>
      ${isMulti?`<p class="text-xs text-slate-400 mb-2">Select all that apply</p>`:''}
      <div class="space-y-1.5">
        ${q.options.map(o=>`
          <label class="flex items-center gap-2 text-sm cursor-pointer">
            <input type="${isMulti?'checkbox':'radio'}" name="ldtq-${q.id}" value="${o.id}"/>
            ${esc(o.text)}
          </label>`).join('')}
      </div>
    </div>`;
  }).join('');
  document.getElementById('ldTakeQuizModal').classList.remove('hidden');
}

function closeLdTakeQuizModal() {
  document.getElementById('ldTakeQuizModal').classList.add('hidden');
}

const submitLdQuizAttempt = guardAsync(async function() {
  const quizId=document.getElementById('ldTakeQuizId').value;
  const questionEls=document.querySelectorAll('#ldTakeQuizQuestions > div');
  const answers={};
  const unansweredNums=[];
  questionEls.forEach(qEl=>{
    const qId=qEl.dataset.qid;
    const checked=[...qEl.querySelectorAll('input:checked')].map(el=>parseInt(el.value));
    if(checked.length) answers[qId]=checked;
    else unansweredNums.push(qEl.dataset.qnum);
  });
  if(unansweredNums.length && !confirm(`Question${unansweredNums.length===1?'':'s'} ${unansweredNums.join(', ')} ${unansweredNums.length===1?'is':'are'} unanswered. Submit anyway?`)) return;

  const res=await api(`/api/ld/quizzes/${quizId}/attempts`,{method:'POST',body:JSON.stringify({answers})});
  if(!res?.ok){
    const d=await res.json();
    alert(apiErrorText(d.detail,'Failed to submit quiz'));
    return;
  }
  const result=await res.json();
  const numberOf=id=>{ const el=document.querySelector(`#ldTakeQuizQuestions > div[data-qid="${id}"]`); return el?parseInt(el.dataset.qnum):null; };
  const outcome=ldQuizOutcome(result,numberOf);
  const resultEl=document.getElementById('ldTakeQuizResult');
  resultEl.classList.remove('hidden');
  resultEl.className=`mb-4 rounded-xl p-4 text-sm ${outcome.passed?'bg-green-50 border border-green-200 text-green-700':'bg-red-50 border border-red-200 text-red-700'}`;
  resultEl.innerHTML=`<p class="font-semibold text-base mb-1">${outcome.headline}</p>`+outcome.lines.map(l=>`<p class="mb-1">${esc(l)}</p>`).join('')+
    (outcome.canRetake?`<button type="button" onclick="openLdTakeQuizModal(${parseInt(document.getElementById('ldTakeQuizCourseId').value)},${parseInt(document.getElementById('ldTakeQuizEnrollId').value)})" class="btn-primary text-sm mt-2">Retake quiz</button>`:'');
  // The answers are now locked in; flag the wrong ones so they know where to look.
  questionEls.forEach(qEl=>qEl.querySelectorAll('input').forEach(i=>i.disabled=true));
  if(!outcome.passed) (result.incorrect_question_ids||[]).forEach(id=>
    document.querySelector(`#ldTakeQuizQuestions > div[data-qid="${id}"] .ldtq-flag`)?.classList.remove('hidden'));
  document.getElementById('ldTakeQuizSubmitBtn').classList.add('hidden');
  resultEl.scrollIntoView({block:'nearest'});
  loadLdEnrollments();
});

// ---------------------------------------------------------------------------
// Course Modules — Editor (HR)
// ---------------------------------------------------------------------------
let ldModuleCount=0;

async function openLdModulesModal(courseId) {
  document.getElementById('ldModulesCourseId').value=courseId;
  document.getElementById('ldModulesList').innerHTML='';
  ldModuleCount=0;
  const course=ldCoursesCache.find(c=>c.id===courseId);
  document.getElementById('ldModulesModalTitle').textContent=`Course Content — ${course?course.title:''}`;
  const res=await api(`/api/ld/courses/${courseId}/modules`);
  if(res?.ok){
    const modules=await res.json();
    modules.forEach(m=>addLdModule(m.content_type, m.title, m.content, m));
  }
  document.getElementById('ldModulesModal').classList.remove('hidden');
}

function closeLdModulesModal() {
  document.getElementById('ldModulesModal').classList.add('hidden');
}

// Document lessons (PDF / Word / PowerPoint). The file is uploaded as soon as it is picked
// (POST /api/ld/courses/{id}/files) and the lesson just remembers its id until Save Content.
const LD_DOC_EXTS=['.pdf','.doc','.docx','.ppt','.pptx'];
const LD_DOC_MAX_BYTES=20*1024*1024;
function ldFileSize(bytes) {
  if(bytes>=1048576) return `${(bytes/1048576).toFixed(1)} MB`;
  return `${Math.max(1,Math.round(bytes/1024))} KB`;
}
function ldDocTag(name) {
  const ext=(name||'').split('.').pop().toLowerCase();
  return ({pdf:'PDF',doc:'Word',docx:'Word',ppt:'PowerPoint',pptx:'PowerPoint'})[ext]||'File';
}
function ldDocFileLabel(name, size) {
  return name?`${esc(name)} <span class="text-slate-400">(${ldFileSize(size)})</span>`:'<span class="text-slate-400">No file chosen yet</span>';
}

async function ldPickDocument(idx, input) {
  const file=input.files?.[0];
  input.value='';
  if(!file) return;
  const wrap=document.getElementById(`ldM-${idx}`);
  const status=wrap.querySelector('.ldm-file-status');
  const ext='.'+file.name.split('.').pop().toLowerCase();
  if(!LD_DOC_EXTS.includes(ext)) { alert('Please choose a PDF, Word (.doc/.docx) or PowerPoint (.ppt/.pptx) file.'); return; }
  if(file.size>LD_DOC_MAX_BYTES) { alert(`That file is ${ldFileSize(file.size)} — the limit is 20 MB.`); return; }
  status.innerHTML='Uploading…';
  const dataUrl=await new Promise((resolve,reject)=>{ const r=new FileReader(); r.onload=()=>resolve(r.result); r.onerror=reject; r.readAsDataURL(file); });
  const courseId=document.getElementById('ldModulesCourseId').value;
  const res=await api(`/api/ld/courses/${courseId}/files`,{method:'POST',body:JSON.stringify({file_name:file.name,data_url:dataUrl})});
  if(!res?.ok) {
    const d=await res?.json().catch(()=>null);
    status.innerHTML=ldDocFileLabel(wrap.dataset.fileName, parseInt(wrap.dataset.fileSize)||0);
    alert(d?.detail?apiErrorText(d.detail):'Upload failed.');
    return;
  }
  const f=await res.json();
  wrap.dataset.fileId=f.id; wrap.dataset.fileName=f.file_name; wrap.dataset.fileSize=f.size_bytes;
  status.innerHTML=ldDocFileLabel(f.file_name, f.size_bytes);
  const t=wrap.querySelector('.ldm-title');
  if(!t.value.trim()) t.value=f.file_name.replace(/\.[^.]+$/,'');
  wrap.querySelector('.ldm-doc-tag').textContent=ldDocTag(f.file_name);
}

function addLdModule(type, title, content, mod) {
  const idx=ldModuleCount++;
  const wrap=document.createElement('div');
  wrap.id=`ldM-${idx}`;
  wrap.dataset.contentType=type;
  if(type==='document' && mod?.file_id) { wrap.dataset.fileId=mod.file_id; wrap.dataset.fileName=mod.file_name||''; wrap.dataset.fileSize=mod.file_size||0; }
  wrap.className='border border-slate-200 rounded-xl p-4';
  wrap.innerHTML=`
    <div class="flex items-center gap-2 mb-2">
      <span class="badge text-xs ${type==='video'?'bg-rose-100 text-rose-700':type==='document'?'bg-blue-100 text-blue-700':'bg-slate-100 text-slate-600'} ldm-doc-tag">${type==='video'?'Video':type==='document'?ldDocTag(mod?.file_name):'Text'}</span>
      <input class="inp ldm-title flex-1" placeholder="Lesson title…" value="${esc(title||'')}"/>
      <button type="button" onclick="ldMoveModule(${idx},-1)" class="text-slate-300 hover:text-blue-500" title="Move up"><svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 15l7-7 7 7"/></svg></button>
      <button type="button" onclick="ldMoveModule(${idx},1)" class="text-slate-300 hover:text-blue-500" title="Move down"><svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/></svg></button>
      <button type="button" onclick="document.getElementById('ldM-${idx}').remove()" class="text-slate-300 hover:text-red-500" title="Remove"><svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg></button>
    </div>
    ${type==='video'
      ?`<input class="inp ldm-content text-sm" placeholder="Video URL (YouTube / Vimeo / direct link)…" value="${esc(content||'')}"/>
        <p class="text-xs text-slate-400 mt-1">YouTube links are embedded as a player; other links open in a new tab.</p>`
      :type==='document'
      ?`<div class="flex items-center gap-3 flex-wrap">
          <label class="btn-ghost text-sm cursor-pointer">Choose file…
            <input type="file" class="hidden" accept=".pdf,.doc,.docx,.ppt,.pptx" onchange="ldPickDocument(${idx},this)"/>
          </label>
          <span class="ldm-file-status text-sm text-slate-600">${ldDocFileLabel(mod?.file_name, mod?.file_size)}</span>
        </div>
        <p class="text-xs text-slate-400 mt-1">PDF, Word or PowerPoint, up to 20 MB. Employees enrolled in the course can download it.</p>`
      :`<textarea class="inp ldm-content text-sm" rows="4" placeholder="Lesson content…">${esc(content||'')}</textarea>`}
  `;
  document.getElementById('ldModulesList').appendChild(wrap);
}

function ldMoveModule(idx, dir) {
  const el=document.getElementById(`ldM-${idx}`);
  if(!el) return;
  if(dir<0 && el.previousElementSibling) el.parentElement.insertBefore(el, el.previousElementSibling);
  if(dir>0 && el.nextElementSibling) el.parentElement.insertBefore(el.nextElementSibling, el);
}

const submitLdModules = guardAsync(async function() {
  const courseId=document.getElementById('ldModulesCourseId').value;
  const modules=[];
  for(const el of document.querySelectorAll('#ldModulesList > div')) {
    const title=el.querySelector('.ldm-title').value.trim();
    if(!title) continue;
    if(el.dataset.contentType==='document') {
      if(!el.dataset.fileId) { alert(`Choose a file for the document lesson "${title}", or remove it.`); return; }
      modules.push({title, content_type:'document', file_id:parseInt(el.dataset.fileId)});
    } else {
      modules.push({title, content_type:el.dataset.contentType, content:el.querySelector('.ldm-content').value.trim()||null});
    }
  }
  const res=await api(`/api/ld/courses/${courseId}/modules`,{method:'PUT',body:JSON.stringify({modules})});
  if(res?.ok){closeLdModulesModal();loadLdCourses();}
  else{const d=await res.json();alert(d.detail?apiErrorText(d.detail):'Failed to save content');}
});

// ---------------------------------------------------------------------------
// Course Modules — Viewer (Employee)
// ---------------------------------------------------------------------------
function ldYoutubeEmbed(url) {
  const m=url.match(/(?:youtube\.com\/watch\?v=|youtu\.be\/)([\w-]{11})/);
  return m?`https://www.youtube.com/embed/${m[1]}`:null;
}

// Renders a single module's body (video embed/link, or plain text) —
// shared by the real Course Viewer (employee, enrollment-bound, below)
// and the HR Preview modal, which has no enrollment behind it and so
// never has viewed/progress state to render alongside this.
// Download/Open a document lesson's file. With an enrollment id (the employee's own) the server
// also marks the lesson viewed, so the viewer is refreshed afterwards.
async function ldOpenModuleFile(btn, moduleId, enrollmentId, inline) {
  const name=btn.dataset.name||'document';
  const win=inline?window.open('','_blank'):null;   // opened now so the popup blocker allows it
  const qs=[enrollmentId?`enrollment_id=${enrollmentId}`:'', inline?'inline=true':''].filter(Boolean).join('&');
  const res=await api(`/api/ld/modules/${moduleId}/file${qs?'?'+qs:''}`);
  if(!res?.ok) {
    if(win) win.close();
    const d=await res?.json().catch(()=>null);
    alert(d?.detail?apiErrorText(d.detail):'Could not open the file.');
    return;
  }
  const url=URL.createObjectURL(await res.blob());
  if(win) win.location=url;
  else { const a=document.createElement('a'); a.href=url; a.download=name; document.body.appendChild(a); a.click(); a.remove(); }
  setTimeout(()=>URL.revokeObjectURL(url), 120000);
  if(enrollmentId && ldViewerCtx) openLdViewerModal(ldViewerCtx.courseId, ldViewerCtx.enrollmentId, ldViewerCtx.title);
}

function ldModuleContentHtml(m, enrollmentId) {
  if(m.content_type==='document') {
    if(!m.file_name) return '<p class="text-sm text-slate-400">This lesson has no file attached.</p>';
    const enr=enrollmentId||'null';
    return `<div class="flex items-center gap-3 flex-wrap rounded-lg bg-slate-50 border border-slate-200 p-3">
      <span class="badge text-xs bg-blue-100 text-blue-700">${ldDocTag(m.file_name)}</span>
      <div class="flex-1 min-w-0">
        <p class="text-sm text-slate-700 truncate" title="${esc(m.file_name)}">${esc(m.file_name)}</p>
        <p class="text-xs text-slate-400">${ldFileSize(m.file_size||0)}</p>
      </div>
      ${m.file_mime_type==='application/pdf'?`<button type="button" class="btn-ghost text-xs" data-name="${esc(m.file_name)}" onclick="ldOpenModuleFile(this,${m.id},${enr},true)">Open</button>`:''}
      <button type="button" class="btn-primary text-xs" data-name="${esc(m.file_name)}" onclick="ldOpenModuleFile(this,${m.id},${enr},false)">Download</button>
    </div>`;
  }
  if(m.content_type==='video'&&m.content){
    const embed=ldYoutubeEmbed(m.content);
    return embed
      ?`<div class="aspect-video rounded-lg overflow-hidden bg-slate-100"><iframe src="${embed}" class="w-full h-full" frameborder="0" allowfullscreen></iframe></div>`
      :`<a href="${esc(m.content)}" target="_blank" rel="noopener" class="text-sm text-blue-600 hover:underline">Open video ↗</a>`;
  }
  return `<p class="text-sm text-slate-600 whitespace-pre-wrap">${esc(m.content||'')}</p>`;
}

let ldViewerCtx=null;
async function openLdViewerModal(courseId, enrollmentId, courseTitle) {
  ldViewerCtx={courseId, enrollmentId, title:courseTitle};
  const res=await api(`/api/ld/courses/${courseId}/modules?enrollment_id=${enrollmentId}`);
  if(!res?.ok){alert('Could not load course content.');return;}
  const modules=await res.json();
  document.getElementById('ldViewerTitle').textContent=courseTitle||'Course';
  const viewed=modules.filter(m=>m.viewed).length;
  document.getElementById('ldViewerProgress').textContent=`${viewed} / ${modules.length} lessons viewed`;
  const isOwn=currentUser?.role==='employee';
  document.getElementById('ldViewerBody').innerHTML=modules.map(m=>`
    <div class="border border-slate-200 rounded-xl p-4" id="ldv-${m.id}">
      <div class="flex items-center justify-between gap-2 mb-2">
        <p class="font-medium text-slate-800 text-sm">${esc(m.title)}</p>
        ${m.viewed
          ?`<span class="badge text-xs status-positive">✓ Viewed</span>`
          :isOwn?`<button onclick="markLdModuleViewed(${enrollmentId},${m.id},${courseId},'${esc(courseTitle||'').replace(/'/g,"\\'")}')" class="btn-ghost text-xs px-2 py-1 border border-slate-200">Mark as viewed</button>`
          :`<span class="badge text-xs status-neutral">Not viewed</span>`}
      </div>
      ${ldModuleContentHtml(m, isOwn?enrollmentId:null)}
    </div>`).join('')||'<p class="text-sm text-slate-400 text-center py-8">No content in this course yet.</p>';
  document.getElementById('ldViewerModal').classList.remove('hidden');
}

function closeLdViewerModal() {
  document.getElementById('ldViewerModal').classList.add('hidden');
  loadLdEnrollments();
}

async function markLdModuleViewed(enrollmentId, moduleId, courseId, courseTitle) {
  const res=await api(`/api/ld/enrollments/${enrollmentId}/modules/${moduleId}/viewed`,{method:'POST'});
  if(res?.ok) openLdViewerModal(courseId, enrollmentId, courseTitle);
}

// ---------------------------------------------------------------------------
// Quiz Preview (HR test-run — graded client-side, nothing persisted)
// ---------------------------------------------------------------------------
let ldPreviewAnswerKey={};
window.ldPreviewCourseId=null;

function ldShuffle(arr) {
  const a=[...arr];
  for(let i=a.length-1;i>0;i--){
    const j=Math.floor(Math.random()*(i+1));
    [a[i],a[j]]=[a[j],a[i]];
  }
  return a;
}

async function openLdPreviewQuizModal(courseId) {
  window.ldPreviewCourseId=courseId;
  document.getElementById('ldPreviewQuizResult').classList.add('hidden');
  document.getElementById('ldPreviewQuizSubmitBtn').classList.remove('hidden');
  document.getElementById('ldPreviewQuizRetryBtn').classList.add('hidden');
  const course=ldCoursesCache.find(c=>c.id===courseId);
  document.getElementById('ldPreviewQuizTitle').textContent=`Course Preview — ${course?course.title:''}`;

  // Course Content — same rendering as the real Course Viewer
  // (ldModuleContentHtml), just with no viewed/progress state: a preview
  // has no real enrollment behind it, so there's nothing to track.
  const modRes=await api(`/api/ld/courses/${courseId}/modules`);
  const modules=modRes?.ok?await modRes.json():[];
  document.getElementById('ldPreviewContent').innerHTML=modules.map(m=>`
    <div class="border border-slate-200 rounded-xl p-4">
      <p class="font-medium text-slate-800 text-sm mb-2">${esc(m.title)}</p>
      ${ldModuleContentHtml(m)}
    </div>`).join('')||'<p class="text-sm text-slate-400 text-center py-6">No content in this course yet.</p>';

  const res=await api(`/api/ld/courses/${courseId}/quiz/manage`);
  if(!res?.ok){
    document.getElementById('ldPreviewQuizQuestions').innerHTML='<p class="text-sm text-slate-400 text-center py-8">This course has no quiz yet.</p>';
    document.getElementById('ldPreviewQuizSubmitBtn').classList.add('hidden');
    document.getElementById('ldPreviewQuizModal').classList.remove('hidden');
    return;
  }
  const quiz=await res.json();
  let questions=quiz.questions;
  if(quiz.randomize_questions) questions=ldShuffle(questions);

  ldPreviewAnswerKey={};
  window.ldPreviewPassMark=quiz.pass_threshold;
  document.getElementById('ldPreviewQuizQuestions').innerHTML=questions.map((q,i)=>{
    const isMulti=q.question_type==='multi';
    let opts=q.options;
    if(quiz.randomize_options) opts=ldShuffle(opts);
    ldPreviewAnswerKey[q.id]=opts.filter(o=>o.is_correct).map(o=>o.id);
    return `<div data-qid="${q.id}" data-qtype="${isMulti?'multi':'single'}" id="ldpq-${q.id}">
      <p class="text-sm font-medium text-slate-800 mb-1"><span class="text-slate-500">${i+1}.</span> ${esc(q.question_text)}</p>
      ${isMulti?`<p class="text-xs text-slate-400 mb-2">Select all that apply</p>`:''}
      <div class="space-y-1.5 ldpq-options">
        ${opts.map(o=>`
          <label class="flex items-center gap-2 text-sm cursor-pointer" data-oid="${o.id}">
            <input type="${isMulti?'checkbox':'radio'}" name="ldpq-${q.id}" value="${o.id}"/>
            <span class="ldpq-option-label">${esc(o.text)}</span>
          </label>`).join('')}
      </div>
    </div>`;
  }).join('');
  document.getElementById('ldPreviewQuizModal').classList.remove('hidden');
}

function closeLdPreviewQuizModal() {
  document.getElementById('ldPreviewQuizModal').classList.add('hidden');
}

function submitLdQuizPreview() {
  const questionEls=document.querySelectorAll('#ldPreviewQuizQuestions > div');
  let correctCount=0;
  questionEls.forEach(qEl=>{
    const qId=qEl.dataset.qid;
    const selected=[...qEl.querySelectorAll('input:checked')].map(el=>parseInt(el.value));
    const correctIds=ldPreviewAnswerKey[qId]||[];
    const isCorrect=selected.length===correctIds.length && selected.every(id=>correctIds.includes(id));
    if(isCorrect) correctCount++;
    // Mark each option: green if correct answer, red ring if wrongly selected
    qEl.querySelectorAll('.ldpq-options > label').forEach(lbl=>{
      const oid=parseInt(lbl.dataset.oid);
      const wasSelected=selected.includes(oid);
      const isRight=correctIds.includes(oid);
      lbl.classList.remove('bg-green-50','bg-red-50','rounded-lg','px-2','py-1','-mx-2');
      if(isRight){ lbl.classList.add('bg-green-50','rounded-lg','px-2','py-1','-mx-2'); }
      else if(wasSelected){ lbl.classList.add('bg-red-50','rounded-lg','px-2','py-1','-mx-2'); }
    });
    qEl.querySelectorAll('input').forEach(inp=>inp.disabled=true);
  });
  const total=questionEls.length;
  const score=total?Math.round((correctCount/total)*1000)/10:0;
  const passMark=window.ldPreviewPassMark??80;
  const resultEl=document.getElementById('ldPreviewQuizResult');
  resultEl.classList.remove('hidden');
  resultEl.className=`mb-4 rounded-xl p-4 text-sm ${score>=passMark?'bg-green-50 border border-green-200 text-green-700':'bg-amber-50 border border-amber-200 text-amber-700'}`;
  resultEl.innerHTML=`<strong>Preview result:</strong> ${correctCount}/${total} correct (${score}%) — pass mark ${passMark}%, so this would ${score>=passMark?'pass':'not pass'}. This was not recorded — correct answers are highlighted in green, wrong picks in red.`;
  document.getElementById('ldPreviewQuizSubmitBtn').classList.add('hidden');
  document.getElementById('ldPreviewQuizRetryBtn').classList.remove('hidden');
}


// ---------------------------------------------------------------------------
// Policies — documents employees read and acknowledge (routers/policies.py)
// ---------------------------------------------------------------------------
const POLICY_STATUS_LABEL={acknowledged:'Acknowledged',overdue:'Overdue',opened:'Opened, not acknowledged',not_opened:'Not opened'};
const POLICY_STATUS_CLASS={acknowledged:'status-positive',overdue:'status-negative',opened:'status-pending',not_opened:'status-pending'};
let ldPolicies=[], policyPeople=[], policyTracker=null, policyTrackerFilter='outstanding', policyRead=null;

function policyAudienceLabel(type, ref, lookup) {
  if(type==='department') return ref?`Department: ${ref}`:'A department';
  if(type==='team') return `Team of ${(lookup&&lookup(ref))||ref||'a manager'}`;
  if(type==='people') return 'Named people';
  return 'All employees';
}
function policyLinkHost(url) {
  try { return new URL(url).hostname; } catch (e) { return url || ''; }
}
function policyProgressPct(assigned, acknowledged) {
  return assigned>0?Math.round(acknowledged/assigned*100):0;
}
function policyEmpName(id) {
  const e=(typeof employees!=='undefined'?employees:[]).find(x=>x.employee_id===id);
  return e?displayName(e.full_name,e.preferred_name):null;
}

async function loadLdPolicies() {
  const body=document.getElementById('ldPolicyTableBody');
  const empty=document.getElementById('ldPolicyEmpty');
  const canManage=HR_MANAGE_ROLES.includes(currentUser?.role);
  document.getElementById('ldPublishPolicyBtn')?.classList.toggle('hidden',!canManage);
  body.innerHTML='<tr><td colspan="6" class="text-slate-400 text-sm text-center py-8">Loading…</td></tr>';
  const res=await api('/api/policies');
  ldPolicies=res&&res.ok?await res.json():[];
  if(!ldPolicies.length){body.innerHTML='';empty.classList.remove('hidden');return;}
  empty.classList.add('hidden');
  body.innerHTML=ldPolicies.map(p=>{
    const pct=policyProgressPct(p.assigned,p.acknowledged);
    return `<tr class="border-t border-slate-100">
      <td class="px-4 py-3"><p class="font-medium text-slate-800">${esc(p.title)}</p><p class="text-xs text-slate-400">${esc(p.link_url?`Link: ${policyLinkHost(p.link_url)}${p.file_name?' + PDF copy':''}`:(p.file_name||''))}</p></td>
      <td class="px-4 py-3 whitespace-nowrap">v${p.version}${p.change_note?`<p class="text-xs text-slate-400 max-w-[14rem] truncate" title="${esc(p.change_note)}">${esc(p.change_note)}</p>`:''}</td>
      <td class="px-4 py-3 text-slate-600">${esc(policyAudienceLabel(p.audience_type,p.audience_ref,policyEmpName))}</td>
      <td class="px-4 py-3 whitespace-nowrap text-slate-600">${p.due_date?fmtDate(p.due_date):'—'}</td>
      <td class="px-4 py-3 whitespace-nowrap">
        <div class="flex items-center gap-2"><div class="bg-slate-100 rounded-full h-1.5 w-24"><div class="bg-green-500 h-1.5 rounded-full" style="width:${pct}%"></div></div>
        <span class="text-xs text-slate-600">${p.acknowledged} / ${p.assigned}</span>${p.overdue?`<span class="badge status-negative text-xs">${p.overdue} overdue</span>`:''}</div>
      </td>
      <td class="px-4 py-3 text-right whitespace-nowrap">
        <button onclick="openPolicyTracker(${p.course_id})" class="btn-ghost text-xs">Tracker</button>
        ${canManage?`<button onclick="openPolicyPublishModal(${p.course_id})" class="btn-ghost text-xs">New version</button>
        <button onclick="deleteLdCourse(${p.course_id})" class="btn-ghost text-xs text-red-600">Remove</button>`:''}
      </td>
    </tr>`;
  }).join('');
}

// ---- Publish / new version ----
function openPolicyPublishModal(courseId) {
  document.getElementById('policyPublishForm').reset();
  policyPeople=[]; renderPolicyPeople();
  document.getElementById('policyCourseId').value=courseId||'';
  const p=courseId?ldPolicies.find(x=>x.course_id===courseId):null;
  document.getElementById('policyPublishTitle').textContent=p?`New version of ${p.title}`:'Publish Policy';
  document.getElementById('policyPublishBtn').textContent=p?`Publish v${p.version+1}`:'Publish';
  document.getElementById('policyTitle').value=p?p.title:'';
  const note=document.getElementById('policyVersionNote');
  note.classList.toggle('hidden',!p);
  if(p) note.textContent=`This asks everyone in the audience to acknowledge again. Version ${p.version} and who acknowledged it stay on record.`;
  const active=(typeof employees!=='undefined'?employees:[]).filter(e=>e.status==='Active');
  const opts=active.map(e=>`<option value="${esc(e.employee_id)}">${esc(e.employee_id)} — ${esc(displayName(e.full_name,e.preferred_name))}</option>`).join('');
  const depts=[...new Set(active.map(e=>e.department).filter(Boolean))].sort();
  document.getElementById('policyAudienceDept').innerHTML=depts.map(d=>`<option value="${esc(d)}">${esc(d)}</option>`).join('');
  document.getElementById('policyAudienceTeam').innerHTML=opts;
  document.getElementById('policyAudiencePerson').innerHTML=opts;
  initEmployeeSearchSelect('policyAudienceTeam','Search manager…');
  initEmployeeSearchSelect('policyAudiencePerson','Search employee…');
  if(p){
    document.getElementById('policyAudienceType').value=p.audience_type;
    if(p.audience_type==='department') document.getElementById('policyAudienceDept').value=p.audience_ref;
    if(p.audience_type==='team') document.getElementById('policyAudienceTeam').value=p.audience_ref;
    document.getElementById('policyRequireOpen').checked=!!p.require_open;
  }
  onPolicyAudienceChange();
  onPolicySourceChange();
  document.getElementById('policyPublishModal').classList.remove('hidden');
}
function onPolicySourceChange() {
  const link=document.getElementById('policySource').value==='link';
  document.getElementById('policySourceFileWrap').classList.toggle('hidden',link);
  document.getElementById('policySourceLinkWrap').classList.toggle('hidden',!link);
}
function closePolicyPublishModal() { document.getElementById('policyPublishModal').classList.add('hidden'); }

function onPolicyAudienceChange() {
  const t=document.getElementById('policyAudienceType').value;
  document.getElementById('policyAudienceDept').classList.toggle('hidden',t!=='department');
  document.getElementById('policyAudienceTeam').classList.toggle('hidden',t!=='team');
  document.getElementById('policyAudienceTeamSearchWrap')?.classList.toggle('hidden',t!=='team');
  document.getElementById('policyAudiencePeopleWrap').classList.toggle('hidden',t!=='people');
  const active=(typeof employees!=='undefined'?employees:[]).filter(e=>e.status==='Active');
  let n=null;
  if(t==='all') n=active.length;
  else if(t==='department') n=active.filter(e=>e.department===document.getElementById('policyAudienceDept').value).length;
  else if(t==='people') n=policyPeople.length;
  document.getElementById('policyAudienceCount').textContent=n===null?"Everyone in that manager's reporting chain (including them).":`Will be assigned to ${n} employee${n===1?'':'s'}.`;
}
document.addEventListener('change',e=>{ if(e.target?.id==='policyAudienceDept') onPolicyAudienceChange(); });

function addPolicyPerson() {
  const id=document.getElementById('policyAudiencePerson').value;
  if(!id||policyPeople.some(x=>x.id===id)) return;
  policyPeople.push({id,name:policyEmpName(id)||id});
  renderPolicyPeople(); onPolicyAudienceChange();
}
function removePolicyPerson(id) { policyPeople=policyPeople.filter(x=>x.id!==id); renderPolicyPeople(); onPolicyAudienceChange(); }
function renderPolicyPeople() {
  document.getElementById('policyPeopleChips').innerHTML=policyPeople.map(x=>
    `<span class="badge status-neutral text-xs">${esc(x.name)} <button type="button" onclick="removePolicyPerson('${esc(x.id)}')" class="ml-1" aria-label="Remove">×</button></span>`).join('');
}

const submitPolicyPublish = guardAsync(async function(e) {
  e.preventDefault();
  const courseId=document.getElementById('policyCourseId').value;
  const isLink=document.getElementById('policySource').value==='link';
  const link=document.getElementById('policyLink').value.trim();
  const file=document.getElementById(isLink?'policyFileCopy':'policyFile').files?.[0];
  if(isLink){
    if(!/^https?:\/\//i.test(link)){ alert('Enter the link, starting with http:// or https://'); return; }
  } else if(!file){ alert('Choose the document to publish.'); return; }
  if(file){
    const ext='.'+file.name.split('.').pop().toLowerCase();
    if(!LD_DOC_EXTS.includes(ext)){ alert('Please choose a PDF, Word (.doc/.docx) or PowerPoint (.ppt/.pptx) file.'); return; }
    if(file.size>LD_DOC_MAX_BYTES){ alert(`That file is ${ldFileSize(file.size)} — the limit is 20 MB.`); return; }
  }
  const type=document.getElementById('policyAudienceType').value;
  if(type==='people'&&!policyPeople.length){ alert('Add at least one person.'); return; }
  const dataUrl=file?await new Promise((resolve,reject)=>{ const r=new FileReader(); r.onload=()=>resolve(r.result); r.onerror=reject; r.readAsDataURL(file); }):null;
  const body={
    title:document.getElementById('policyTitle').value.trim(),
    change_note:document.getElementById('policyChangeNote').value.trim()||null,
    due_date:document.getElementById('policyDue').value||null,
    require_open:document.getElementById('policyRequireOpen').checked,
    audience_type:type,
    audience_ref:type==='department'?document.getElementById('policyAudienceDept').value:type==='team'?document.getElementById('policyAudienceTeam').value:null,
    employee_ids:type==='people'?policyPeople.map(x=>x.id):[],
    link_url:isLink?link:null,
    file_name:file?file.name:null, data_url:dataUrl,
  };
  const res=await api(courseId?`/api/policies/${courseId}/versions`:'/api/policies',{method:'POST',body:JSON.stringify(body)});
  if(!res?.ok){ const d=await res?.json().catch(()=>null); alert(d?.detail?apiErrorText(d.detail):'Could not publish the policy.'); return; }
  closePolicyPublishModal();
  loadLdPolicies();
});

// ---- Tracker (HR sees everyone; a manager their own team, read-only) ----
async function openPolicyTracker(courseId, versionId) {
  const res=await api(`/api/policies/${courseId}/tracker${versionId?`?version_id=${versionId}`:''}`);
  if(!res?.ok){ const d=await res?.json().catch(()=>null); alert(d?.detail?apiErrorText(d.detail):'Could not load the tracker.'); return; }
  policyTracker=await res.json();
  policyTrackerFilter=policyTracker.summary.assigned>policyTracker.summary.acknowledged?'outstanding':'all';
  renderPolicyTracker();
  document.getElementById('policyTrackerModal').classList.remove('hidden');
}
function closePolicyTrackerModal() { document.getElementById('policyTrackerModal').classList.add('hidden'); }
function setPolicyTrackerFilter(f) { policyTrackerFilter=f; renderPolicyTracker(); }
function onPolicyTrackerVersionChange() {
  openPolicyTracker(policyTracker.policy.course_id, parseInt(document.getElementById('policyTrackerVersion').value));
}
function policyTrackerRows(rows, filter) {
  if(filter==='outstanding') return rows.filter(r=>r.status!=='acknowledged');
  if(filter==='acknowledged') return rows.filter(r=>r.status==='acknowledged');
  return rows;
}
function renderPolicyTracker() {
  const t=policyTracker, v=t.version;
  document.getElementById('policyTrackerTitle').textContent=`${t.policy.title} — v${v.version}`;
  document.getElementById('policyTrackerSub').textContent=
    `${v.due_date?`Due ${fmtDate(v.due_date)} · `:''}${t.summary.acknowledged} of ${t.summary.assigned} acknowledged${t.summary.overdue?` · ${t.summary.overdue} overdue`:''}${t.is_current?'':' · an earlier version'}`;
  document.getElementById('policyTrackerVersion').innerHTML=t.versions.map(x=>
    `<option value="${x.id}"${x.id===v.id?' selected':''}>v${x.version} — ${fmtDate(x.created_at)}</option>`).join('');
  document.querySelectorAll('.policy-trk-chip').forEach(b=>b.classList.toggle('ld-cat-filter-active',b.dataset.f===policyTrackerFilter));
  const rows=policyTrackerRows(t.rows,policyTrackerFilter);
  document.getElementById('policyTrackerEmpty').classList.toggle('hidden',rows.length>0);
  document.getElementById('policyTrackerBody').innerHTML=rows.map(r=>`<tr class="border-t border-slate-100">
    <td class="px-4 py-2.5 font-medium text-slate-800 whitespace-nowrap">${esc(displayName(r.full_name,r.preferred_name)||r.employee_id)}${r.employee_status&&r.employee_status!=='Active'?` <span class="text-xs text-slate-400">(${esc(r.employee_status)})</span>`:''}</td>
    <td class="px-4 py-2.5 text-slate-600">${esc(r.department||'—')}</td>
    <td class="px-4 py-2.5"><span class="badge text-xs ${POLICY_STATUS_CLASS[r.status]}">${POLICY_STATUS_LABEL[r.status]}</span></td>
    <td class="px-4 py-2.5 text-slate-600 whitespace-nowrap">${r.first_opened_at?fmtDateTime(r.first_opened_at):'—'}</td>
    <td class="px-4 py-2.5 text-slate-600 whitespace-nowrap">${r.acknowledged_at?fmtDateTime(r.acknowledged_at):'—'}</td>
    <td class="px-4 py-2.5 text-slate-600 whitespace-nowrap">${r.last_reminded_at?fmtDateTime(r.last_reminded_at):'—'}</td>
  </tr>`).join('');
  const outstanding=t.rows.filter(r=>r.status!=='acknowledged'&&(!r.employee_status||r.employee_status==='Active')).length;
  const remindBtn=document.getElementById('policyRemindBtn');
  remindBtn.classList.toggle('hidden',!(t.can_manage&&t.is_current&&outstanding>0));
  remindBtn.textContent=`Send reminder (${outstanding})`;
  const un=t.unassigned||[];
  document.getElementById('policyUnassignedHint').classList.toggle('hidden',!un.length);
  document.getElementById('policyUnassignedText').textContent=un.length
    ?`${un.length} active employee${un.length===1?'':'s'} in this audience ${un.length===1?"hasn't":"haven't"} been assigned: ${un.slice(0,4).map(u=>u.full_name).join(', ')}${un.length>4?'…':''}`:'';
  const addWrap=document.getElementById('policyAddPeopleWrap');
  addWrap.classList.toggle('hidden',!(t.can_manage&&t.is_current));
  if(t.can_manage&&t.is_current){
    document.getElementById('policyTrackerAddEmp').innerHTML=(typeof employees!=='undefined'?employees:[]).filter(e=>e.status==='Active')
      .map(e=>`<option value="${esc(e.employee_id)}">${esc(e.employee_id)} — ${esc(displayName(e.full_name,e.preferred_name))}</option>`).join('');
    initEmployeeSearchSelect('policyTrackerAddEmp','Search employee…');
  }
}
const remindPolicyOutstanding = guardAsync(async function() {
  const t=policyTracker;
  if(t.email_ready===false){ alert("Email isn't set up for this company. Turn on email notifications under Settings → Notifications first."); return; }
  if(!confirm('Email everyone who has not acknowledged this version yet? Anyone reminded in the last day is skipped.')) return;
  const res=await api(`/api/policies/versions/${t.version.id}/remind`,{method:'POST'});
  if(!res?.ok){ const d=await res?.json().catch(()=>null); alert(d?.detail?apiErrorText(d.detail):'Could not send the reminders.'); return; }
  const r=await res.json();
  alert(`Reminder queued for ${r.queued} ${r.queued===1?'person':'people'}.${r.skipped_recent?` ${r.skipped_recent} skipped (reminded in the last day).`:''}${r.no_email?` ${r.no_email} have no email address.`:''}`);
  await openPolicyTracker(t.policy.course_id, t.version.id);
});

// CSV of who acknowledged what and when (audit evidence). Fetched with the auth header, so it goes via a blob.
async function exportPolicyCsv() {
  const t=policyTracker;
  const res=await api(`/api/policies/${t.policy.course_id}/export.csv?version_id=${t.version.id}`);
  if(!res?.ok){ const d=await res?.json().catch(()=>null); alert(d?.detail?apiErrorText(d.detail):'Could not export.'); return; }
  const url=URL.createObjectURL(await res.blob());
  const a=document.createElement('a'); a.href=url;
  a.download=`${t.policy.title.replace(/[^A-Za-z0-9]+/g,'-')}-v${t.version.version}-acknowledgements.csv`;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(()=>URL.revokeObjectURL(url),60000);
}

async function policyAssign(ids) {
  const res=await api(`/api/policies/versions/${policyTracker.version.id}/assign`,{method:'POST',body:JSON.stringify({employee_ids:ids})});
  if(!res?.ok){ const d=await res?.json().catch(()=>null); alert(d?.detail?apiErrorText(d.detail):'Could not add them.'); return; }
  await openPolicyTracker(policyTracker.policy.course_id);
  loadLdPolicies();
}
const assignPolicyUnassigned = guardAsync(async function() { await policyAssign((policyTracker.unassigned||[]).map(u=>u.employee_id)); });
const addPolicyTrackerPerson = guardAsync(async function() {
  const id=document.getElementById('policyTrackerAddEmp').value;
  if(id) await policyAssign([id]);
});

// ---- Employee: My Policies ----
let ldMyPolicies=[];
async function loadLdMyPolicies() {
  const sec=document.getElementById('ldMyPoliciesSection');
  if(!sec) return;
  if(!currentUser?.employee_id){ sec.classList.add('hidden'); return; }
  const res=await api('/api/policies/mine');
  ldMyPolicies=res&&res.ok?await res.json():[];
  sec.classList.toggle('hidden',!ldMyPolicies.length);
  const pending=ldMyPolicies.filter(p=>p.status!=='acknowledged');
  const banner=document.getElementById('ldMyPoliciesBanner');
  banner.classList.toggle('hidden',!pending.length);
  if(pending.length){
    const next=pending.filter(p=>p.due_date).sort((a,b)=>a.due_date.localeCompare(b.due_date))[0];
    banner.textContent=`${pending.length} polic${pending.length===1?'y is':'ies are'} waiting for your acknowledgement${next?` — ${next.title} is due ${fmtDate(next.due_date)}`:''}.`;
  }
  document.getElementById('ldMyPoliciesBody').innerHTML=ldMyPolicies.map(p=>`<tr class="border-t border-slate-100">
    <td class="px-4 py-3 font-medium text-slate-800">${esc(p.title)}</td>
    <td class="px-4 py-3 whitespace-nowrap text-slate-600">v${p.version}</td>
    <td class="px-4 py-3 whitespace-nowrap text-slate-600">${p.due_date?fmtDate(p.due_date):'—'}</td>
    <td class="px-4 py-3 whitespace-nowrap"><span class="badge text-xs ${POLICY_STATUS_CLASS[p.status]}">${p.status==='acknowledged'?`Acknowledged ${fmtDate(p.acknowledged_at)}`:p.status==='overdue'?'Overdue':'Action needed'}</span></td>
    <td class="px-4 py-3 text-right whitespace-nowrap"><button onclick="openPolicyRead(${p.version_id})" class="${p.status==='acknowledged'?'btn-ghost':'btn-primary'} text-xs px-3 py-1.5">${p.status==='acknowledged'?'View':'Read and acknowledge'}</button></td>
  </tr>`).join('');
}

function openPolicyRead(versionId) {
  const p=ldMyPolicies.find(x=>x.version_id===versionId);
  if(!p) return;
  policyRead=p;
  const done=p.status==='acknowledged';
  document.getElementById('policyReadTitle').innerHTML=`${esc(p.title)} <span class="badge status-info text-xs">v${p.version}</span>`;
  document.getElementById('policyReadMeta').innerHTML=
    (p.description?`<p>${esc(p.description)}</p>`:'')+
    (p.change_note?`<p class="text-slate-500">What changed: ${esc(p.change_note)}</p>`:'')+
    (p.due_date?`<p class="text-slate-500">Acknowledge by ${fmtDate(p.due_date)}</p>`:'');
  // The document: a link (opened through EMS so the open is recorded), an uploaded file, or both
  // (then the file is the PDF copy of what the link showed).
  const row=(label,btnLabel,fn)=>`<div class="border border-slate-200 rounded-lg px-4 py-3 flex items-center justify-between gap-3">
    <span class="text-sm text-slate-700 truncate" title="${esc(label)}">${esc(label)}</span>
    <button onclick="${fn}()" class="btn-ghost text-sm shrink-0 whitespace-nowrap">${btnLabel}</button></div>`;
  document.getElementById('policyReadDocs').innerHTML=
    (p.link_url?row(policyLinkHost(p.link_url),'Open link','policyOpenLinkFromModal'):'')+
    (p.file_name?row(p.link_url?`PDF copy — ${p.file_name}`:p.file_name,p.link_url?'View copy':'Open document','policyOpenFromModal'):'');
  document.getElementById('policyReadPassword').value='';
  const viaMicrosoft=!!currentUser?.password_signin_blocked;
  document.getElementById('policyReadPasswordWrap').classList.toggle('hidden',viaMicrosoft);
  document.getElementById('policyReadAckBtn').textContent=viaMicrosoft?'Confirm with Microsoft':'Acknowledge';
  document.getElementById('policyReadStatement').textContent=`I have read and understood ${p.title} (v${p.version}).`;
  document.getElementById('policyReadHint').textContent=(p.require_open?'Open the document first. ':'')+(viaMicrosoft?"Microsoft will ask you to sign in again to confirm it's you. Your acknowledgement is recorded with today's date and time."
    :"Entering your password confirms it's you. Your acknowledgement is recorded with today's date and time.");
  document.getElementById('policyReadAckBlock').classList.toggle('hidden',done||!p.is_current);
  document.getElementById('policyReadAckBtn').classList.toggle('hidden',done||!p.is_current);
  const msg=document.getElementById('policyReadDone');
  msg.classList.toggle('hidden',!done);
  if(done) msg.textContent=`You acknowledged this on ${fmtDateTime(p.acknowledged_at)}.`;
  document.getElementById('policyReadModal').classList.remove('hidden');
}
function closePolicyReadModal() {
  document.getElementById('policyReadPassword').value='';
  document.getElementById('policyReadModal').classList.add('hidden');
}

function policyMarkOpened() {
  policyRead.first_opened_at=policyRead.first_opened_at||new Date().toISOString();   // the server has recorded it
  document.getElementById('policyReadHint').textContent=currentUser?.password_signin_blocked
    ?'Thanks for opening it. Confirm with Microsoft when you have read it.':'Thanks for opening it. Enter your password and acknowledge when you have read it.';
}

async function policyOpenFromModal() {
  const p=policyRead; if(!p) return;
  const isPdf=/\.pdf$/i.test(p.file_name||'');
  const win=isPdf?window.open('','_blank'):null;   // opened now so the popup blocker allows it
  const res=await api(`/api/policies/versions/${p.version_id}/file${isPdf?'?inline=true':''}`);
  if(!res?.ok){
    if(win) win.close();
    const d=await res?.json().catch(()=>null);
    alert(d?.detail?apiErrorText(d.detail):'Could not open the document.');
    return;
  }
  const url=URL.createObjectURL(await res.blob());
  if(win) win.location=url;
  else { const a=document.createElement('a'); a.href=url; a.download=p.file_name; document.body.appendChild(a); a.click(); a.remove(); }
  setTimeout(()=>URL.revokeObjectURL(url),120000);
  policyMarkOpened();
}

async function policyOpenLinkFromModal() {
  const p=policyRead; if(!p) return;
  const win=window.open('','_blank');   // opened now so the popup blocker allows it
  const res=await api(`/api/policies/versions/${p.version_id}/open-link`,{method:'POST'});
  if(!res?.ok){
    if(win) win.close();
    const d=await res?.json().catch(()=>null);
    alert(d?.detail?apiErrorText(d.detail):'Could not open the link.');
    return;
  }
  const {url}=await res.json();
  if(win){ win.opener=null; win.location=url; }
  policyMarkOpened();
}

const submitPolicyAcknowledge = guardAsync(async function() {
  const p=policyRead; if(!p) return;
  if(currentUser?.password_signin_blocked){
    if(p.require_open&&!p.first_opened_at){ alert('Open the document first, then confirm.'); return; }
    const start=await api('/api/auth/sso/reauth-start',{method:'POST',body:JSON.stringify({purpose:'policy_ack',ref:String(p.version_id)})});
    if(!start?.ok){
      const d=await start?.json().catch(()=>null);
      alert(d?.detail?apiErrorText(d.detail):'Could not start the Microsoft confirmation.');
      return;
    }
    window.location.href=(await start.json()).authorize_url;   // comes back via resumeSsoReauth() in core.js
    return;
  }
  const password=document.getElementById('policyReadPassword').value;
  if(!password){ alert('Enter your password to confirm.'); return; }
  const res=await api(`/api/policies/versions/${p.version_id}/acknowledge`,{method:'POST',body:JSON.stringify({password})});
  if(!res?.ok){
    const d=await res?.json().catch(()=>null);
    document.getElementById('policyReadPassword').value='';
    alert(d?.detail?apiErrorText(d.detail):'Could not record your acknowledgement.');
    return;
  }
  closePolicyReadModal();
  loadLdMyPolicies();
});
