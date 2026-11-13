document.querySelectorAll('.project-quote').forEach(link => {
  link.addEventListener('click', () => {
    const form = document.querySelector('#contact form');
    if (!form) return;
    form.elements.service.value = link.dataset.service;
    const details = form.elements.details;
    if (!details.value.trim()) details.value = link.dataset.project;
    const notice = document.querySelector('#project-selection');
    if (notice) notice.textContent = `Selected: ${link.closest('article').querySelector('h3').textContent} Add your details below.`;
    form.elements.name.focus({preventScroll:true});
  });
});
