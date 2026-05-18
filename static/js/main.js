// main.js — students will add JavaScript here as features are built

(function () {
    const overlay  = document.getElementById('demo-modal');
    const openBtn  = document.getElementById('open-demo-modal');
    const closeBtn = document.getElementById('close-demo-modal');
    const iframe   = document.getElementById('demo-iframe');

    if (!overlay || !openBtn) return;

    function openModal() {
        iframe.src = iframe.dataset.src;
        overlay.classList.add('is-open');
        document.body.style.overflow = 'hidden';
    }

    function closeModal() {
        overlay.classList.remove('is-open');
        document.body.style.overflow = '';
        // Reset src to stop video playback
        iframe.src = '';
    }

    openBtn.addEventListener('click', openModal);
    closeBtn.addEventListener('click', closeModal);

    overlay.addEventListener('click', function (e) {
        if (e.target === overlay) closeModal();
    });

    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape' && overlay.classList.contains('is-open')) closeModal();
    });
}());
