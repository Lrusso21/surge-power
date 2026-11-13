/* Progressive enhancements preserve native forms when JavaScript is unavailable. */
(()=>{
 const filters=document.querySelector('.owner .filter-grid.expanded');
 if(filters){
  const extra=document.createElement('details');extra.className='advanced-filters';extra.innerHTML='<summary>More filters</summary><div class="advanced-fields"></div>';
  const fields=extra.querySelector('div');
  ['service','urgency','assigned','city','order'].forEach(name=>{const el=filters.querySelector('[name="'+name+'"]');if(el){fields.append(el);if(el.value && !['priority'].includes(el.value))extra.open=true;}});
  filters.insertBefore(extra,filters.querySelector('button'));
 }
 const form=document.querySelector('.public form[action="/inquiry"]');
 if(form){
  const extra=document.createElement('details');extra.className='optional-intake';extra.innerHTML='<summary>Add preferences or equipment details (optional)</summary>';
  ['preferred_contact','best_time','property_type','vehicle_or_equipment'].forEach(name=>{const el=form.querySelector('[name="'+name+'"]');if(el)extra.append(el.closest('label'));});
  const consent=form.querySelector('.consent-check');form.insertBefore(extra,consent||form.querySelector('button'));
 }
 document.querySelectorAll('.inquiry-table').forEach(table=>{
  const labels=[...table.querySelectorAll('.inquiry-head>span')].map(x=>x.textContent);
  table.querySelectorAll('.inquiry-row').forEach(row=>[...row.children].forEach((cell,i)=>cell.dataset.label=labels[i]||''));
 });
 const edit=document.querySelector('.compact-form');
 if(edit){const details=document.createElement('details');details.className='project-editor';details.innerHTML='<summary>Edit customer and project</summary>';edit.before(details);details.append(edit);}
 document.querySelectorAll('.calendar-event strong').forEach(el=>{el.title=el.textContent;el.textContent=el.textContent.replace(/^DEMO — /,'');});
})();
document.querySelectorAll('.owner .filter-grid').forEach(form=>{const button=form.querySelector('button');const clear=[...form.querySelectorAll('a')].find(a=>a.textContent.trim()==='Clear');if(button&&clear){const actions=document.createElement('div');actions.className='filter-actions';form.append(actions);actions.append(button,clear);}});
