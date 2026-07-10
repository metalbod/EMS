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
  const d=new Date(utcValue.endsWith('Z')?utcValue:utcValue+'Z');
  return d.toLocaleString(undefined,{year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'});
}

function notifStatus(n) {
  const now=new Date().toISOString().slice(0,16);
  if(now < n.start_time) return 'Scheduled';
  if(now > n.end_time) return 'Expired';
  return 'Active';
}
const NOTIF_STATUS_COLORS={'Active':'bg-green-100 text-green-700','Scheduled':'bg-amber-100 text-amber-700','Expired':'bg-slate-100 text-slate-500'};

async function loadNotificationSettings() {
  const listEl=document.getElementById('notificationList');
  const emptyEl=document.getElementById('notificationEmpty');
  listEl.innerHTML='<tr><td colspan="5" class="text-slate-400 text-sm text-center py-8">Loading…</td></tr>';
  const res=await api('/api/notifications');
  const rows=res?.ok?await res.json():[];
  notificationsCache=rows;
  if(!rows.length){ listEl.innerHTML=''; emptyEl?.classList.remove('hidden'); return; }
  emptyEl?.classList.add('hidden');
  listEl.innerHTML=rows.map(n=>{
    const status=notifStatus(n);
    return `<tr class="border-t border-slate-100">
      <td class="px-4 py-3 text-slate-700 max-w-md"><p class="line-clamp-2">${esc(n.message)}</p></td>
      <td class="px-4 py-3 text-slate-500 whitespace-nowrap">${utcToLocalDisplay(n.start_time)}</td>
      <td class="px-4 py-3 text-slate-500 whitespace-nowrap">${utcToLocalDisplay(n.end_time)}</td>
      <td class="px-4 py-3"><span class="badge text-xs ${NOTIF_STATUS_COLORS[status]}">${status}</span></td>
      <td class="px-4 py-3 text-right whitespace-nowrap">
        <button onclick="openNotificationModal(${n.id})" class="text-xs text-blue-600 hover:underline mr-3">Edit</button>
        <button onclick="deleteNotification(${n.id})" class="text-xs text-red-600 hover:underline">Delete</button>
      </td>
    </tr>`;
  }).join('');
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
  if(notificationId){
    const n=notificationsCache.find(x=>x.id===notificationId);
    document.getElementById('notificationMessage').value=n?.message||'';
    document.getElementById('notificationStart').value=utcToLocalInput(n?.start_time)||'';
    document.getElementById('notificationEnd').value=utcToLocalInput(n?.end_time)||'';
  } else {
    document.getElementById('notificationMessage').value='';
    document.getElementById('notificationStart').value='';
    document.getElementById('notificationEnd').value='';
  }
  updateNotificationWordCount();
  document.getElementById('notificationModal').classList.remove('hidden');
}
function closeNotificationModal() { document.getElementById('notificationModal').classList.add('hidden'); }

async function submitNotification() {
  const id=document.getElementById('notificationId').value;
  const message=document.getElementById('notificationMessage').value.trim();
  const startTime=document.getElementById('notificationStart').value;
  const endTime=document.getElementById('notificationEnd').value;
  if(!message){ alert('Message is required'); return; }
  if(message.trim().split(/\s+/).filter(Boolean).length>500){ alert('Message must be 500 words or fewer'); return; }
  if(!startTime||!endTime){ alert('Start and end time are required'); return; }
  const body={ message, start_time:localInputToUTC(startTime), end_time:localInputToUTC(endTime) };
  const url=id?`/api/notifications/${id}`:'/api/notifications';
  const res=await api(url,{method:id?'PUT':'POST',body:JSON.stringify(body)});
  if(res?.ok){
    closeNotificationModal();
    loadNotificationSettings();
  } else {
    const d=await res.json(); alert(d.detail||'Failed to save notification');
  }
}

async function deleteNotification(notificationId) {
  if(!confirm('Delete this notification?')) return;
  const res=await api(`/api/notifications/${notificationId}`,{method:'DELETE'});
  if(res?.ok||res?.status===204){ loadNotificationSettings(); }
  else { const d=await res.json(); alert(d.detail||'Failed to delete notification'); }
}

// ---------------------------------------------------------------------------
// Dashboard banner — shown to all roles except superadmin, dismissible per session
// ---------------------------------------------------------------------------
async function checkDashboardNotification() {
  const bar=document.getElementById('dashboardNotifBar');
  if(!bar) return;
  if(currentUser?.role==='superadmin'){ bar.classList.add('hidden'); return; }
  const res=await api('/api/notifications/active');
  const n=res?.ok?await res.json():null;
  if(!n){ bar.classList.add('hidden'); return; }
  if(sessionStorage.getItem(notifDismissKey(n.id))){ bar.classList.add('hidden'); return; }
  document.getElementById('dashboardNotifMsg').textContent=n.message;
  bar.dataset.notifId=n.id;
  bar.classList.remove('hidden');
  bar.classList.add('flex');
}

function notifDismissKey(notifId) {
  // Scoped to the logged-in user, not just the browser tab — sessionStorage
  // otherwise persists across a logout/login in the same tab, incorrectly
  // suppressing the banner for the next person who signs in.
  return `notifDismissed_${notifId}_${currentUser?.id}`;
}

function dismissDashboardNotification() {
  const bar=document.getElementById('dashboardNotifBar');
  const id=bar?.dataset?.notifId;
  if(id) sessionStorage.setItem(notifDismissKey(id),'1');
  bar.classList.add('hidden');
  bar.classList.remove('flex');
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
      <td class="px-4 py-3 text-slate-700 max-w-md"><p class="line-clamp-2">${esc(n.message)}</p></td>
      <td class="px-4 py-3 text-slate-500 whitespace-nowrap">${utcToLocalDisplay(n.start_time)}</td>
      <td class="px-4 py-3 text-slate-500 whitespace-nowrap">${utcToLocalDisplay(n.end_time)}</td>
      <td class="px-4 py-3"><span class="badge text-xs ${NOTIF_STATUS_COLORS[status]}">${status}</span></td>
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
function closeSystemNotificationModal() { document.getElementById('systemNotificationModal').classList.add('hidden'); }

async function submitSystemNotification() {
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
}

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
  document.getElementById('dashboardSystemNotifMsg').textContent=n.message;
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
