// Learning & Development
// ---------------------------------------------------------------------------
let ldCoursesCache=[], ldCatFilter='', ldEnrollFilter='';
const LD_CATEGORY_LABELS={mandatory:'Mandatory',professional_development:'Professional Dev',certification:'Certification'};
const LD_CATEGORY_COLORS={mandatory:'bg-red-100 text-red-700',professional_development:'bg-blue-100 text-blue-700',certification:'bg-purple-100 text-purple-700'};
const LD_STATUS_COLORS={'Pending Approval':'bg-amber-100 text-amber-700','Approved':'bg-blue-100 text-blue-700','Rejected':'bg-red-100 text-red-700','In Progress':'bg-blue-100 text-blue-700','Completed':'bg-green-100 text-green-700'};

async function loadLdCourses() {
  const listEl=document.getElementById('ldCourseList');
  const emptyEl=document.getElementById('ldCourseEmpty');
  listEl.innerHTML='<p class="text-slate-400 text-sm text-center py-8 col-span-full">Loading…</p>';
  let url='/api/ld/courses';
  if(ldCatFilter) url+=`?category=${encodeURIComponent(ldCatFilter)}`;
  const res=await api(url);
  if(!res||!res.ok){listEl.innerHTML='';return;}
  const rows=await res.json();
  ldCoursesCache=rows;
  if(!rows.length){listEl.innerHTML='';emptyEl?.classList.remove('hidden');return;}
  emptyEl?.classList.add('hidden');
  const canManage=['superadmin','hr_manager','hr_admin'].includes(currentUser?.role);
  listEl.innerHTML=rows.map(c=>`
    <div class="bg-white border border-slate-200 rounded-xl p-4">
      <div class="flex items-start justify-between gap-2 mb-2">
        <span class="badge text-xs ${LD_CATEGORY_COLORS[c.category]||'bg-slate-100 text-slate-600'}">${LD_CATEGORY_LABELS[c.category]||c.category}</span>
        ${canManage?`<div class="flex items-center gap-1">
          <button onclick="openLdModulesModal(${c.id})" class="text-slate-300 hover:text-green-600" title="Course Content"><svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s4.832.477 6 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.746 0 3.332.477 4.5 1.253v13C19.832 18.477 18.246 18 16.5 18c-1.746 0-3.332.477-4.5 1.253"/></svg></button>
          <button onclick="openLdQuizModal(${c.id})" class="text-slate-300 hover:text-purple-500" title="Manage Quiz"><svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/></svg></button>
          <button onclick="openLdCourseModal(${c.id})" class="text-slate-300 hover:text-blue-500" title="Edit"><svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"/></svg></button>
          <button onclick="deleteLdCourse(${c.id})" class="text-slate-300 hover:text-red-500" title="Remove"><svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg></button>
        </div>`:''}
      </div>
      <p class="font-medium text-slate-800 mb-1">${esc(c.title)}</p>
      <p class="text-xs text-slate-500 mb-3 line-clamp-2">${esc(c.description||'')}</p>
      <div class="flex items-center justify-between">
        <span class="text-sm font-medium ${c.cost>0?'text-amber-600':'text-green-600'}">${c.cost>0?'RM '+Number(c.cost).toLocaleString('en-MY',{minimumFractionDigits:2}):'Free'}</span>
        <div class="flex items-center gap-2">
          ${canManage?`<button onclick="openLdPreviewQuizModal(${c.id})" class="btn-ghost text-xs px-3 py-1.5 border border-slate-200">Preview</button>`:''}
          <button onclick="openLdEnrollModal(${c.id})" class="btn-primary text-xs px-3 py-1.5">Enroll</button>
        </div>
      </div>
    </div>`).join('');
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
    costNote.textContent=`This course costs RM ${Number(course.cost).toLocaleString('en-MY',{minimumFractionDigits:2})} — enrollment will require manager/HR approval before starting.`;
    costNote.classList.remove('hidden');
  } else {
    costNote.classList.add('hidden');
  }
  const empWrap=document.getElementById('ldEnrollEmpWrap');
  const canManage=['superadmin','hr_manager','hr_admin','manager'].includes(currentUser?.role);
  if(canManage){
    empWrap.classList.remove('hidden');
    const sel=document.getElementById('ldEnrollEmpId');
    sel.innerHTML=employees.filter(e=>e.status==='Active').map(e=>`<option value="${e.employee_id}">${e.employee_id} — ${esc(e.full_name)}</option>`).join('');
    if(currentUser?.employee_id) sel.value=currentUser.employee_id;
  } else {
    empWrap.classList.add('hidden');
  }
  document.getElementById('ldEnrollModal').classList.remove('hidden');
}

function closeLdEnrollModal() {
  document.getElementById('ldEnrollModal').classList.add('hidden');
}

async function submitLdEnroll(e) {
  e.preventDefault();
  const courseId=parseInt(document.getElementById('ldEnrollCourseId').value);
  const canManage=['superadmin','hr_manager','hr_admin','manager'].includes(currentUser?.role);
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

async function loadLdEnrollments() {
  const listEl=document.getElementById('ldEnrollmentList');
  const emptyEl=document.getElementById('ldEnrollmentEmpty');
  listEl.innerHTML='<p class="text-slate-400 text-sm text-center py-8">Loading…</p>';
  let url='/api/ld/enrollments';
  if(ldEnrollFilter) url+=`?status=${encodeURIComponent(ldEnrollFilter)}`;
  const res=await api(url);
  if(!res||!res.ok){listEl.innerHTML='';return;}
  const rows=await res.json();
  if(!rows.length){listEl.innerHTML='';emptyEl?.classList.remove('hidden');return;}
  emptyEl?.classList.add('hidden');
  const canApprove=['superadmin','hr_manager','hr_admin','manager'].includes(currentUser?.role);
  listEl.innerHTML=rows.map(en=>{
    const isSelf = currentUser?.role!=='employee' || currentUser?.employee_id===en.employee_id;
    const isOwnEmployeeAccount = currentUser?.role==='employee' && currentUser?.employee_id===en.employee_id;
    const canAct = en.status==='In Progress' && isSelf;
    const hasQuiz = !!en.quiz_id;
    return `<div class="bg-white border border-slate-200 rounded-xl p-4">
      <div class="flex items-start justify-between gap-3">
        <div class="flex-1 min-w-0">
          <div class="flex items-center gap-2 mb-0.5 flex-wrap">
            <p class="font-medium text-slate-800">${esc(en.course_title)}</p>
            <span class="badge text-xs ${LD_CATEGORY_COLORS[en.course_category]||'bg-slate-100 text-slate-600'}">${LD_CATEGORY_LABELS[en.course_category]||en.course_category}</span>
            ${hasQuiz?`<span class="badge text-xs bg-purple-100 text-purple-700">Quiz Required</span>`:''}
            ${en.module_count>0?`<span class="badge text-xs bg-slate-100 text-slate-600">${en.modules_viewed}/${en.module_count} lessons</span>`:''}
          </div>
          <p class="text-xs text-slate-500">${esc(en.employee_name)} · ${esc(en.department||'')}${en.designation?' · '+esc(en.designation):''}</p>
          ${en.notes?`<p class="text-xs text-slate-400 italic mt-1">${esc(en.notes)}</p>`:''}
        </div>
        <div class="flex items-center gap-2 flex-shrink-0">
          <span class="badge ${LD_STATUS_COLORS[en.status]||'bg-slate-100 text-slate-600'}">${en.status}</span>
        </div>
      </div>
      <div class="mt-3 flex items-center gap-2">
        ${en.status==='Pending Approval'&&canApprove?`
          <button onclick="updateLdEnrollStatus(${en.id},'Approved')" class="btn-primary text-xs px-3 py-1.5">Approve</button>
          <button onclick="updateLdEnrollStatus(${en.id},'Rejected')" class="btn-ghost text-xs px-3 py-1.5 text-red-600">Reject</button>
        `:''}
        ${en.status!=='Pending Approval'&&en.status!=='Rejected'&&en.module_count>0?`<button onclick="openLdViewerModal(${en.course_id},${en.id},'${esc(en.course_title).replace(/'/g,"\\'")}')" class="btn-ghost text-xs px-3 py-1.5 border border-slate-200">View Course</button>`:''}
        ${en.status==='In Progress'&&hasQuiz&&isOwnEmployeeAccount?`<button onclick="openLdTakeQuizModal(${en.course_id},${en.id})" class="btn-primary text-xs px-3 py-1.5">Take Quiz</button>`:''}
        ${en.status==='In Progress'&&hasQuiz&&!isOwnEmployeeAccount?`<span class="text-xs text-slate-400 italic">Awaiting employee to take quiz</span>`:''}
        ${canAct&&!hasQuiz?`<button onclick="updateLdEnrollStatus(${en.id},'Completed')" class="btn-primary text-xs px-3 py-1.5">Mark Complete</button>`:''}
      </div>
      <p class="text-xs text-slate-400 mt-2">Requested ${en.created_at?.slice(0,10)} by ${esc(en.requested_by)}${en.completed_at?' · Completed '+en.completed_at.slice(0,10):''}</p>
    </div>`;
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

async function submitLdQuiz() {
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
}

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
async function openLdTakeQuizModal(courseId, enrollmentId) {
  const res=await api(`/api/ld/courses/${courseId}/quiz`);
  if(!res?.ok){alert('Could not load quiz.');return;}
  const quiz=await res.json();
  document.getElementById('ldTakeQuizId').value=quiz.id;
  document.getElementById('ldTakeQuizEnrollId').value=enrollmentId;
  document.getElementById('ldTakeQuizTitle').textContent=quiz.title;
  document.getElementById('ldTakeQuizResult').classList.add('hidden');
  document.getElementById('ldTakeQuizSubmitBtn').classList.remove('hidden');
  document.getElementById('ldTakeQuizQuestions').innerHTML=quiz.questions.map(q=>{
    const isMulti=q.question_type==='multi';
    return `<div data-qid="${q.id}" data-qtype="${isMulti?'multi':'single'}">
      <p class="text-sm font-medium text-slate-800 mb-1">${esc(q.question_text)}</p>
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

async function submitLdQuizAttempt() {
  const quizId=document.getElementById('ldTakeQuizId').value;
  const questionEls=document.querySelectorAll('#ldTakeQuizQuestions > div');
  const answers={};
  let unanswered=false;
  questionEls.forEach(qEl=>{
    const qId=qEl.dataset.qid;
    const checked=[...qEl.querySelectorAll('input:checked')].map(el=>parseInt(el.value));
    if(checked.length) answers[qId]=checked;
    else unanswered=true;
  });
  if(unanswered && !confirm('Some questions are unanswered. Submit anyway?')) return;

  const res=await api(`/api/ld/quizzes/${quizId}/attempts`,{method:'POST',body:JSON.stringify({answers})});
  if(!res?.ok){
    const d=await res.json();
    alert(d.detail||'Failed to submit quiz');
    return;
  }
  const result=await res.json();
  const resultEl=document.getElementById('ldTakeQuizResult');
  resultEl.classList.remove('hidden');
  if(result.passed){
    resultEl.className='mb-4 rounded-xl p-4 text-sm bg-green-50 border border-green-200 text-green-700';
    resultEl.innerHTML=`<strong>Passed!</strong> Score: ${result.score}%. Course marked complete.`;
    document.getElementById('ldTakeQuizSubmitBtn').classList.add('hidden');
  } else {
    const remaining=result.max_attempts - result.attempt_number;
    resultEl.className='mb-4 rounded-xl p-4 text-sm bg-red-50 border border-red-200 text-red-700';
    resultEl.innerHTML=`<strong>Not passed.</strong> Score: ${result.score}%. ${remaining>0?`${remaining} attempt(s) remaining.`:'No attempts remaining.'}`;
    if(remaining<=0) document.getElementById('ldTakeQuizSubmitBtn').classList.add('hidden');
  }
  loadLdEnrollments();
}

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
    modules.forEach(m=>addLdModule(m.content_type, m.title, m.content));
  }
  document.getElementById('ldModulesModal').classList.remove('hidden');
}

function closeLdModulesModal() {
  document.getElementById('ldModulesModal').classList.add('hidden');
}

function addLdModule(type, title, content) {
  const idx=ldModuleCount++;
  const wrap=document.createElement('div');
  wrap.id=`ldM-${idx}`;
  wrap.dataset.contentType=type;
  wrap.className='border border-slate-200 rounded-xl p-4';
  wrap.innerHTML=`
    <div class="flex items-center gap-2 mb-2">
      <span class="badge text-xs ${type==='video'?'bg-rose-100 text-rose-700':'bg-slate-100 text-slate-600'}">${type==='video'?'Video':'Text'}</span>
      <input class="inp ldm-title flex-1" placeholder="Lesson title…" value="${esc(title||'')}"/>
      <button type="button" onclick="ldMoveModule(${idx},-1)" class="text-slate-300 hover:text-blue-500" title="Move up"><svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 15l7-7 7 7"/></svg></button>
      <button type="button" onclick="ldMoveModule(${idx},1)" class="text-slate-300 hover:text-blue-500" title="Move down"><svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/></svg></button>
      <button type="button" onclick="document.getElementById('ldM-${idx}').remove()" class="text-slate-300 hover:text-red-500" title="Remove"><svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg></button>
    </div>
    ${type==='video'
      ?`<input class="inp ldm-content text-sm" placeholder="Video URL (YouTube / Vimeo / direct link)…" value="${esc(content||'')}"/>
        <p class="text-xs text-slate-400 mt-1">YouTube links are embedded as a player; other links open in a new tab.</p>`
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

async function submitLdModules() {
  const courseId=document.getElementById('ldModulesCourseId').value;
  const modules=[...document.querySelectorAll('#ldModulesList > div')].map(el=>({
    title: el.querySelector('.ldm-title').value.trim(),
    content_type: el.dataset.contentType,
    content: el.querySelector('.ldm-content').value.trim()||null
  })).filter(m=>m.title);
  const res=await api(`/api/ld/courses/${courseId}/modules`,{method:'PUT',body:JSON.stringify({modules})});
  if(res?.ok){closeLdModulesModal();loadLdCourses();}
  else{const d=await res.json();alert(d.detail||'Failed to save content');}
}

// ---------------------------------------------------------------------------
// Course Modules — Viewer (Employee)
// ---------------------------------------------------------------------------
function ldYoutubeEmbed(url) {
  const m=url.match(/(?:youtube\.com\/watch\?v=|youtu\.be\/)([\w-]{11})/);
  return m?`https://www.youtube.com/embed/${m[1]}`:null;
}

async function openLdViewerModal(courseId, enrollmentId, courseTitle) {
  const res=await api(`/api/ld/courses/${courseId}/modules?enrollment_id=${enrollmentId}`);
  if(!res?.ok){alert('Could not load course content.');return;}
  const modules=await res.json();
  document.getElementById('ldViewerTitle').textContent=courseTitle||'Course';
  const viewed=modules.filter(m=>m.viewed).length;
  document.getElementById('ldViewerProgress').textContent=`${viewed} / ${modules.length} lessons viewed`;
  const isOwn=currentUser?.role==='employee';
  document.getElementById('ldViewerBody').innerHTML=modules.map(m=>{
    let contentHtml='';
    if(m.content_type==='video'&&m.content){
      const embed=ldYoutubeEmbed(m.content);
      contentHtml=embed
        ?`<div class="aspect-video rounded-lg overflow-hidden bg-slate-100"><iframe src="${embed}" class="w-full h-full" frameborder="0" allowfullscreen></iframe></div>`
        :`<a href="${esc(m.content)}" target="_blank" rel="noopener" class="text-sm text-blue-600 hover:underline">Open video ↗</a>`;
    } else {
      contentHtml=`<p class="text-sm text-slate-600 whitespace-pre-wrap">${esc(m.content||'')}</p>`;
    }
    return `<div class="border border-slate-200 rounded-xl p-4" id="ldv-${m.id}">
      <div class="flex items-center justify-between gap-2 mb-2">
        <p class="font-medium text-slate-800 text-sm">${esc(m.title)}</p>
        ${m.viewed
          ?`<span class="badge text-xs bg-green-100 text-green-700">✓ Viewed</span>`
          :isOwn?`<button onclick="markLdModuleViewed(${enrollmentId},${m.id},${courseId},'${esc(courseTitle||'').replace(/'/g,"\\'")}')" class="btn-ghost text-xs px-2 py-1 border border-slate-200">Mark as viewed</button>`
          :`<span class="badge text-xs bg-slate-100 text-slate-500">Not viewed</span>`}
      </div>
      ${contentHtml}
    </div>`;
  }).join('')||'<p class="text-sm text-slate-400 text-center py-8">No content in this course yet.</p>';
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
  const res=await api(`/api/ld/courses/${courseId}/quiz/manage`);
  document.getElementById('ldPreviewQuizResult').classList.add('hidden');
  document.getElementById('ldPreviewQuizSubmitBtn').classList.remove('hidden');
  document.getElementById('ldPreviewQuizRetryBtn').classList.add('hidden');
  const course=ldCoursesCache.find(c=>c.id===courseId);
  document.getElementById('ldPreviewQuizTitle').textContent=`Quiz Preview — ${course?course.title:''}`;

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
  document.getElementById('ldPreviewQuizQuestions').innerHTML=questions.map(q=>{
    const isMulti=q.question_type==='multi';
    let opts=q.options;
    if(quiz.randomize_options) opts=ldShuffle(opts);
    ldPreviewAnswerKey[q.id]=opts.filter(o=>o.is_correct).map(o=>o.id);
    return `<div data-qid="${q.id}" data-qtype="${isMulti?'multi':'single'}" id="ldpq-${q.id}">
      <p class="text-sm font-medium text-slate-800 mb-1">${esc(q.question_text)}</p>
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
  const score=total?Math.round((correctCount/total)*100):0;
  const resultEl=document.getElementById('ldPreviewQuizResult');
  resultEl.classList.remove('hidden');
  resultEl.className=`mb-4 rounded-xl p-4 text-sm ${score>=80?'bg-green-50 border border-green-200 text-green-700':'bg-amber-50 border border-amber-200 text-amber-700'}`;
  resultEl.innerHTML=`<strong>Preview result:</strong> ${correctCount}/${total} correct (${score}%). This was not recorded — correct answers are highlighted in green, wrong picks in red.`;
  document.getElementById('ldPreviewQuizSubmitBtn').classList.add('hidden');
  document.getElementById('ldPreviewQuizRetryBtn').classList.remove('hidden');
}
