// Institution Notifications (HR Manager / HR Admin settings + dashboard banner)
// ---------------------------------------------------------------------------
// start_time/end_time are stored as naive UTC strings ("YYYY-MM-DDTHH:MM") so
// they compare correctly against the server's UTC "now" regardless of which
// timezone the browser or the server happens to be in. <input type="datetime-local">
// only ever works in the browser's local time, so we convert local <-> UTC
// at the two boundaries (save, and populate-for-edit/display).
let notificationsCache=[];

function localInputToUTC(localValue) {
  // "2026-07-09T14:30" (local) -> "2026-07-09T06:30" (UTC, naive, no trailing Z)
  if(!localValue) return localValue;
  return new Date(localValue).toISOString().slice(0,16);
}

function utcToLocalInput(utcValue) {
  // "2026-07-09T06:30" (UTC, naive) -> "2026-07-09T14:30" (local, for datetime-local inputs)
  if(!utcValue) return utcValue;
  const d=new Date(utcValue.endsWith('Z')?utcValue:utcValue+'Z');
  const pad=n=>String(n).padStart(2,'0');
  return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function utcToLocalDisplay(utcValue) {
  return fmtDateTime(utcValue);
}

function notifStatus(n) {
  const now=new Date().toISOString().slice(0,16);
  if(now < n.start_time) return 'Scheduled';
  if(now > n.end_time) return 'Expired';
  return 'Active';
}
const NOTIF_STATUS_COLORS={'Active':'status-positive','Scheduled':'status-pending','Expired':'status-neutral'};

async function loadNotificationGeneralSettings() {
  const msg=document.getElementById('notifGeneralSettingsMsg');
  if(msg) msg.textContent='';
  const res=await api('/api/notifications/general-settings');
  if(!res?.ok) return;
  const s=await res.json();
  const tzSel=document.getElementById('notifSettingsTimezone');
  if(tzSel && s.timezone && ![...tzSel.options].some(o=>o.value===s.timezone)){
    // The institution's saved timezone isn't in our curated dropdown list —
    // add it so the select still shows the actual saved value rather than
    // silently falling back to whatever option happens to be first.
    tzSel.insertAdjacentHTML('beforeend', `<option value="${esc(s.timezone)}">${esc(s.timezone)}</option>`);
  }
  if(tzSel) tzSel.value=s.timezone;
  document.getElementById('notifSettingsHolidayEve').checked=!!s.holiday_eve_announcements_enabled;
}

const saveNotificationGeneralSettings = guardAsync(async function() {
  const msg=document.getElementById('notifGeneralSettingsMsg');
  const body={
    timezone: document.getElementById('notifSettingsTimezone').value,
    holiday_eve_announcements_enabled: document.getElementById('notifSettingsHolidayEve').checked,
  };
  const res=await api('/api/notifications/general-settings', {method:'PUT', body: JSON.stringify(body)});
  if(res?.ok){
    msg.textContent='Settings saved.';
    msg.className='text-xs mt-2 text-green-600';
  } else {
    const d=await res.json();
    msg.textContent=apiErrorText(d.detail, 'Failed to save settings.');
    msg.className='text-xs mt-2 text-red-600';
  }
});

// ---------------------------------------------------------------------------
// Tab switching for the consolidated "Notifications" settings page
// (Announcements / SMTP Settings / Reminders) — same pattern as the
// Dashboard's switchDashTab (static/js/dashboard.js): each non-default
// tab's data loads lazily, only the first time it's opened.
// ---------------------------------------------------------------------------
const _notifTabLoaded = { smtp: false, reminders: false };

async function switchNotifTab(tabId) {
  document.querySelectorAll('.notif-tab-panel').forEach(el => el.classList.toggle('hidden', el.id !== tabId));
  document.querySelectorAll('[data-notiftab]').forEach(el => el.classList.toggle('pill-tab-active', el.dataset.notiftab === tabId));
  if (tabId === 'notif-smtp' && !_notifTabLoaded.smtp) {
    _notifTabLoaded.smtp = true;
    await ensureModuleLoaded('email-notification-settings');
    loadEmailNotificationSettingsPage();
  }
  if (tabId === 'notif-reminders' && !_notifTabLoaded.reminders) {
    _notifTabLoaded.reminders = true;
    loadReminderSettings();
  }
}

function resetNotifTabs() {
  // Always land back on Announcements and re-check per-tab data on every
  // fresh visit to this page, rather than trusting stale state from a
  // previous visit within the same session.
  _notifTabLoaded.smtp = false;
  _notifTabLoaded.reminders = false;
  switchNotifTab('notif-announcements');
}

const REMINDER_CATEGORIES = ['timesheet', 'onboarding', 'offboarding', 'holidays', 'acknowledgement'];

async function loadReminderSettings() {
  const msg = document.getElementById('reminderSettingsMsg');
  if (msg) msg.textContent = '';
  const res = await api('/api/notifications/reminder-settings');
  if (!res?.ok) return;
  const s = await res.json();
  REMINDER_CATEGORIES.forEach(cat => {
    const box = document.getElementById(`reminderToggle_${cat}`);
    if (box) box.checked = !!s[`reminder_${cat}_enabled`];
  });
}

const saveReminderSettings = guardAsync(async function() {
  const msg = document.getElementById('reminderSettingsMsg');
  const body = {};
  REMINDER_CATEGORIES.forEach(cat => {
    body[`reminder_${cat}_enabled`] = document.getElementById(`reminderToggle_${cat}`).checked;
  });
  const res = await api('/api/notifications/reminder-settings', {method: 'PUT', body: JSON.stringify(body)});
  if (res?.ok) {
    msg.textContent = 'Settings saved.';
    msg.className = 'text-xs text-green-600';
  } else {
    const d = await res.json();
    msg.textContent = apiErrorText(d.detail, 'Failed to save settings.');
    msg.className = 'text-xs text-red-600';
  }
});

async function loadNotificationSettings() {
  const listEl=document.getElementById('notificationList');
  const emptyEl=document.getElementById('notificationEmpty');
  listEl.innerHTML='<tr><td colspan="6" class="text-slate-400 text-sm text-center py-8">Loading…</td></tr>';
  const res=await api('/api/notifications');
  const rows=res?.ok?await res.json():[];
  notificationsCache=rows;
  if(!rows.length){ listEl.innerHTML=''; emptyEl?.classList.remove('hidden'); return; }
  emptyEl?.classList.add('hidden');
  listEl.innerHTML=rows.map(n=>{
    const status=notifStatus(n);
    const audience=n.target_type==='under'
      ?`Under: ${(n.target_employees||[]).map(t=>esc(displayName(t.full_name,t.preferred_name)||t.employee_id)).join(', ')||'—'}`
      :'Everyone';
    return `<tr class="border-t border-slate-100">
      <td class="px-4 py-3 text-slate-700 max-w-md"><p class="line-clamp-2">${linkify(n.message)}</p></td>
      <td class="px-4 py-3 text-slate-500 max-w-xs"><p class="line-clamp-2">${audience}</p></td>
      <td class="px-4 py-3 text-slate-500 whitespace-nowrap">${utcToLocalDisplay(n.start_time)}</td>
      <td class="px-4 py-3 text-slate-500 whitespace-nowrap">${utcToLocalDisplay(n.end_time)}</td>
      <td class="px-4 py-3"><span class="badge text-xs ${statusColor(NOTIF_STATUS_COLORS, status)}">${status}</span></td>
      <td class="px-4 py-3 text-right whitespace-nowrap">
        <button onclick="openNotificationModal(${n.id})" class="text-xs text-blue-600 hover:underline mr-3">Edit</button>
        <button onclick="deleteNotification(${n.id})" class="text-xs text-red-600 hover:underline">Delete</button>
      </td>
    </tr>`;
  }).join('');
}

// ---------------------------------------------------------------------------
// Notification audience picker — same searchable-checkbox-list pattern as
// the Project modal's Team Members picker (static/js/timesheet.js's
// renderProjectMembersChecklist/filterProjectMemberOptions), reusing the
// same shared filterEmployeeOptions helper (static/js/employee-picker.js).
// No "Select All", unlike that one — picking literally everyone here would
// just be the "Everyone" radio option instead.
// ---------------------------------------------------------------------------
function renderNotifAudienceOptions(selectedIds) {
  const wrap=document.getElementById('notifAudienceList');
  const active=(employees||[]).filter(e=>e.status==='Active' || selectedIds.includes(e.employee_id));
  wrap.innerHTML=active.map(e=>{
    const label=`${displayName(e.full_name,e.preferred_name)} (${e.employee_id})`;
    return `
    <label class="notif-audience-option flex items-center gap-2 px-3 py-1.5 hover:bg-slate-50 cursor-pointer" data-label="${esc(label)}">
      <input type="checkbox" class="notif-audience-checkbox" value="${e.employee_id}" ${selectedIds.includes(e.employee_id)?'checked':''}/>
      ${esc(label)}
    </label>`;
  }).join('');
  const searchEl=document.getElementById('notifAudienceSearch');
  if(searchEl) searchEl.value='';
  filterNotifAudienceOptions();
}

function filterNotifAudienceOptions() {
  const q=document.getElementById('notifAudienceSearch')?.value||'';
  const opts=[...document.querySelectorAll('.notif-audience-option')];
  const matched=new Set(filterEmployeeOptions(
    opts.map(el=>({value: el.querySelector('.notif-audience-checkbox').value, label: el.dataset.label})),
    q
  ).map(o=>o.value));
  let visibleCount=0;
  opts.forEach(opt=>{
    const match=matched.has(opt.querySelector('.notif-audience-checkbox').value);
    opt.classList.toggle('hidden', !match);
    if(match) visibleCount++;
  });
  document.getElementById('notifAudienceNoMatch')?.classList.toggle('hidden', visibleCount>0);
}

function onNotificationAudienceChange() {
  const under=document.getElementById('notifAudienceUnder').checked;
  document.getElementById('notifAudienceUnderPicker').classList.toggle('hidden', !under);
}

function selectedNotifAudienceIds() {
  return [...document.querySelectorAll('.notif-audience-checkbox:checked')].map(b=>b.value);
}

function updateNotificationWordCount() {
  const words=document.getElementById('notificationMessage').value.trim().split(/\s+/).filter(Boolean);
  const count=words.length;
  const el=document.getElementById('notificationWordCount');
  el.textContent=`${count} / 500 words`;
  el.classList.toggle('text-red-500', count>500);
  el.classList.toggle('text-slate-400', count<=500);
}

function openNotificationModal(notificationId) {
  document.getElementById('notificationId').value=notificationId||'';
  document.getElementById('notificationModalTitle').textContent=notificationId?'Edit Notification':'Add Notification';
  let targetType='everyone', selectedIds=[];
  if(notificationId){
    const n=notificationsCache.find(x=>x.id===notificationId);
    document.getElementById('notificationMessage').value=n?.message||'';
    document.getElementById('notificationStart').value=utcToLocalInput(n?.start_time)||'';
    document.getElementById('notificationEnd').value=utcToLocalInput(n?.end_time)||'';
    targetType=n?.target_type||'everyone';
    selectedIds=(n?.target_employees||[]).map(t=>t.employee_id);
  } else {
    document.getElementById('notificationMessage').value='';
    document.getElementById('notificationStart').value='';
    document.getElementById('notificationEnd').value='';
  }
  document.getElementById('notifAudienceEveryone').checked=targetType!=='under';
  document.getElementById('notifAudienceUnder').checked=targetType==='under';
  renderNotifAudienceOptions(selectedIds);
  onNotificationAudienceChange();
  updateNotificationWordCount();
  document.getElementById('notificationModal').classList.remove('hidden');
}
function closeNotificationModal() { closeModal('notificationModal'); }

const submitNotification = guardAsync(async function() {
  const id=document.getElementById('notificationId').value;
  const message=document.getElementById('notificationMessage').value.trim();
  const startTime=document.getElementById('notificationStart').value;
  const endTime=document.getElementById('notificationEnd').value;
  if(!message){ alert('Message is required'); return; }
  if(message.trim().split(/\s+/).filter(Boolean).length>500){ alert('Message must be 500 words or fewer'); return; }
  if(!startTime||!endTime){ alert('Start and end time are required'); return; }
  const targetType=document.getElementById('notifAudienceUnder').checked?'under':'everyone';
  const targetEmployeeIds=targetType==='under'?selectedNotifAudienceIds():[];
  if(targetType==='under' && !targetEmployeeIds.length){ alert('Select at least one person for "All under"'); return; }
  const body={
    message, start_time:localInputToUTC(startTime), end_time:localInputToUTC(endTime),
    target_type:targetType, target_employee_ids:targetEmployeeIds,
  };
  const url=id?`/api/notifications/${id}`:'/api/notifications';
  const res=await api(url,{method:id?'PUT':'POST',body:JSON.stringify(body)});
  if(res?.ok){
    closeNotificationModal();
    loadNotificationSettings();
  } else {
    const d=await res.json(); alert(apiErrorText(d.detail, 'Failed to save notification'));
  }
});

async function deleteNotification(notificationId) {
  if(!confirm('Delete this notification?')) return;
  const res=await api(`/api/notifications/${notificationId}`,{method:'DELETE'});
  if(res?.ok||res?.status===204){ loadNotificationSettings(); }
  else { const d=await res.json(); alert(d.detail||'Failed to delete notification'); }
}

// ---------------------------------------------------------------------------
// Dashboard banners — shown to all roles except superadmin, each
// independently dismissible per session. Any number can be active at
// once (see routers/notifications.py's module docstring) — including a
// synthetic "public holiday tomorrow" entry (id like "holiday-eve-42")
// merged in server-side alongside real institution_notifications rows;
// the frontend treats every entry identically, real or virtual.
// ---------------------------------------------------------------------------
async function checkDashboardNotification() {
  const container=document.getElementById('dashboardNotifList');
  if(!container) return;
  if(currentUser?.role==='superadmin'){ container.innerHTML=''; return; }
  const res=await api('/api/notifications/active');
  const list=res?.ok?await res.json():[];
  const visible=list.filter(n=>!sessionStorage.getItem(notifDismissKey(n.id)));
  container.innerHTML=visible.map(n=>`
    <div class="flex items-start gap-3 bg-purple-50 border border-purple-200 rounded-xl px-4 py-3 mb-5" data-notif-id="${esc(String(n.id))}">
      <svg class="w-5 h-5 text-purple-600 shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9"/></svg>
      <p class="flex-1 text-sm text-purple-800 whitespace-pre-line">${linkify(n.message)}</p>
      <button onclick="dismissDashboardNotification('${String(n.id).replace(/'/g,"")}')" class="text-purple-400 hover:text-purple-600 shrink-0"><svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg></button>
    </div>`).join('');
}

function notifDismissKey(notifId) {
  // Scoped to the logged-in user, not just the browser tab — sessionStorage
  // otherwise persists across a logout/login in the same tab, incorrectly
  // suppressing the banner for the next person who signs in.
  return `notifDismissed_${notifId}_${currentUser?.id}`;
}

function dismissDashboardNotification(id) {
  sessionStorage.setItem(notifDismissKey(id),'1');
  document.querySelector(`#dashboardNotifList [data-notif-id="${CSS.escape(String(id))}"]`)?.remove();
}

// ---------------------------------------------------------------------------
// System-Wide Notifications (superadmin settings + red dashboard banner for ALL roles)
// ---------------------------------------------------------------------------
let systemNotificationsCache=[];

async function loadSystemNotificationSettings() {
  const listEl=document.getElementById('systemNotificationList');
  const emptyEl=document.getElementById('systemNotificationEmpty');
  listEl.innerHTML='<tr><td colspan="5" class="text-slate-400 text-sm text-center py-8">Loading…</td></tr>';
  const res=await api('/api/system-notifications');
  const rows=res?.ok?await res.json():[];
  systemNotificationsCache=rows;
  if(!rows.length){ listEl.innerHTML=''; emptyEl?.classList.remove('hidden'); return; }
  emptyEl?.classList.add('hidden');
  listEl.innerHTML=rows.map(n=>{
    const status=notifStatus(n);
    return `<tr class="border-t border-slate-100">
      <td class="px-4 py-3 text-slate-700 max-w-md"><p class="line-clamp-2">${linkify(n.message)}</p></td>
      <td class="px-4 py-3 text-slate-500 whitespace-nowrap">${utcToLocalDisplay(n.start_time)}</td>
      <td class="px-4 py-3 text-slate-500 whitespace-nowrap">${utcToLocalDisplay(n.end_time)}</td>
      <td class="px-4 py-3"><span class="badge text-xs ${statusColor(NOTIF_STATUS_COLORS, status)}">${status}</span></td>
      <td class="px-4 py-3 text-right whitespace-nowrap">
        <button onclick="openSystemNotificationModal(${n.id})" class="text-xs text-blue-600 hover:underline mr-3">Edit</button>
        <button onclick="deleteSystemNotification(${n.id})" class="text-xs text-red-600 hover:underline">Delete</button>
      </td>
    </tr>`;
  }).join('');
}

function updateSystemNotificationWordCount() {
  const words=document.getElementById('systemNotificationMessage').value.trim().split(/\s+/).filter(Boolean);
  const count=words.length;
  const el=document.getElementById('systemNotificationWordCount');
  el.textContent=`${count} / 500 words`;
  el.classList.toggle('text-red-500', count>500);
  el.classList.toggle('text-slate-400', count<=500);
}

function openSystemNotificationModal(notificationId) {
  document.getElementById('systemNotificationId').value=notificationId||'';
  document.getElementById('systemNotificationModalTitle').textContent=notificationId?'Edit System Notification':'Add System Notification';
  if(notificationId){
    const n=systemNotificationsCache.find(x=>x.id===notificationId);
    document.getElementById('systemNotificationMessage').value=n?.message||'';
    document.getElementById('systemNotificationStart').value=utcToLocalInput(n?.start_time)||'';
    document.getElementById('systemNotificationEnd').value=utcToLocalInput(n?.end_time)||'';
  } else {
    document.getElementById('systemNotificationMessage').value='';
    document.getElementById('systemNotificationStart').value='';
    document.getElementById('systemNotificationEnd').value='';
  }
  updateSystemNotificationWordCount();
  document.getElementById('systemNotificationModal').classList.remove('hidden');
}
function closeSystemNotificationModal() { closeModal('systemNotificationModal'); }

const submitSystemNotification = guardAsync(async function() {
  const id=document.getElementById('systemNotificationId').value;
  const message=document.getElementById('systemNotificationMessage').value.trim();
  const startTime=document.getElementById('systemNotificationStart').value;
  const endTime=document.getElementById('systemNotificationEnd').value;
  if(!message){ alert('Message is required'); return; }
  if(message.trim().split(/\s+/).filter(Boolean).length>500){ alert('Message must be 500 words or fewer'); return; }
  if(!startTime||!endTime){ alert('Start and end time are required'); return; }
  const body={ message, start_time:localInputToUTC(startTime), end_time:localInputToUTC(endTime) };
  const url=id?`/api/system-notifications/${id}`:'/api/system-notifications';
  const res=await api(url,{method:id?'PUT':'POST',body:JSON.stringify(body)});
  if(res?.ok){
    closeSystemNotificationModal();
    loadSystemNotificationSettings();
  } else {
    const d=await res.json(); alert(d.detail||'Failed to save system notification');
  }
});

async function deleteSystemNotification(notificationId) {
  if(!confirm('Delete this system-wide notification?')) return;
  const res=await api(`/api/system-notifications/${notificationId}`,{method:'DELETE'});
  if(res?.ok||res?.status===204){ loadSystemNotificationSettings(); }
  else { const d=await res.json(); alert(d.detail||'Failed to delete system notification'); }
}

// Dashboard banner — shown to ALL roles (including superadmin), dismissible per session
async function checkDashboardSystemNotification() {
  const bar=document.getElementById('dashboardSystemNotifBar');
  if(!bar) return;
  const res=await api('/api/system-notifications/active');
  const n=res?.ok?await res.json():null;
  if(!n){ bar.classList.add('hidden'); bar.classList.remove('flex'); return; }
  if(sessionStorage.getItem(sysNotifDismissKey(n.id))){ bar.classList.add('hidden'); bar.classList.remove('flex'); return; }
  document.getElementById('dashboardSystemNotifMsg').innerHTML=linkify(n.message);
  bar.dataset.notifId=n.id;
  bar.classList.remove('hidden');
  bar.classList.add('flex');
}

function sysNotifDismissKey(notifId) {
  return `sysNotifDismissed_${notifId}_${currentUser?.id}`;
}

function dismissDashboardSystemNotification() {
  const bar=document.getElementById('dashboardSystemNotifBar');
  const id=bar?.dataset?.notifId;
  if(id) sessionStorage.setItem(sysNotifDismissKey(id),'1');
  bar.classList.add('hidden');
  bar.classList.remove('flex');
}
