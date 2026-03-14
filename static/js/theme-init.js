/* WizzardChat \u2013 theme initialiser (runs synchronously in <head> to prevent FOUC) */
(function () {
    var t = localStorage.getItem('wc_theme') || 'dark';
    document.documentElement.setAttribute('data-bs-theme', t);
    document.documentElement.setAttribute('data-theme', t);
}());
