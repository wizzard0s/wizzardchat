/* WizzardChat – shared sidebar logic (loaded on every page) */

// ─── Accordion toggle ─────────────────────────────────────────────────────────
var WC_NAV_STATE_KEY = 'wc_nav_state_v3';

function _saveNavState() {
    var state = {};
    document.querySelectorAll('.nav-section-body').forEach(function (b) {
        if (b.id) state[b.id] = !b.classList.contains('collapsed');
    });
    localStorage.setItem(WC_NAV_STATE_KEY, JSON.stringify(state));
}

function navToggle(id, hdr) {
    var body = document.getElementById(id);
    var chev = hdr.querySelector('.section-chev');
    if (!body) return;
    var willOpen = body.classList.contains('collapsed');
    body.classList.toggle('collapsed', !willOpen);
    if (chev) chev.classList.toggle('collapsed', !willOpen);
    _saveNavState();
}

// ─── Theme management ─────────────────────────────────────────────────────────
var WC_THEME_KEY = 'wc_theme';

function applyTheme(theme) {
    document.documentElement.setAttribute('data-bs-theme', theme);
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem(WC_THEME_KEY, theme);
    var toggle = document.getElementById('themeToggle');
    if (toggle) toggle.checked = (theme === 'light');
}

// ─── Profile dropdown injection ───────────────────────────────────────────────
function injectProfileDropdown() {
    var nameEl = document.getElementById('agentName');
    if (!nameEl) return;
    var container = nameEl.closest('.d-flex');
    if (!container) return;

    // Preserve wsStatusDot if present (agent page only)
    var wsDotHtml = document.getElementById('wsStatusDot')
        ? '<span id="wsStatusDot" class="status-dot" title="WebSocket connection"></span>'
        : '';

    container.outerHTML =
        '<div class="dropdown mb-1" id="profileDropdownWrap">' +
            '<button type="button"' +
                    ' class="btn btn-sm w-100 text-start d-flex align-items-center gap-2 text-white profile-btn"' +
                    ' data-bs-toggle="dropdown" aria-expanded="false">' +
                '<i class="bi bi-person-circle opacity-75"></i>' +
                wsDotHtml +
                '<span class="flex-fill text-truncate small" id="agentName">–</span>' +
                '<i class="bi bi-chevron-down" style="font-size:10px;opacity:.5"></i>' +
            '</button>' +
            '<ul class="dropdown-menu dropdown-menu-dark profile-menu">' +
                '<li><h6 class="dropdown-header text-truncate" id="profileName">–</h6></li>' +
                '<li><hr class="dropdown-divider m-1"></li>' +
                '<li>' +
                    '<label class="dropdown-item d-flex align-items-center justify-content-between gap-3 py-2"' +
                           ' style="cursor:pointer;user-select:none">' +
                        '<span class="small"><i class="bi bi-sun me-2 text-warning"></i>Light theme</span>' +
                        '<div class="form-check form-switch mb-0">' +
                            '<input class="form-check-input" type="checkbox" id="themeToggle" role="switch">' +
                        '</div>' +
                    '</label>' +
                '</li>' +
                '<li><hr class="dropdown-divider m-1"></li>' +
                '<li>' +
                    '<a class="dropdown-item text-danger small py-2" href="/login" id="btnLogout">' +
                        '<i class="bi bi-box-arrow-right me-2"></i>Sign out' +
                    '</a>' +
                '</li>' +
            '</ul>' +
        '</div>';

    // Wire logout directly here so it works regardless of which page JS is loaded
    var logoutBtn = document.getElementById('btnLogout');
    if (logoutBtn) {
        logoutBtn.addEventListener('click', function (e) {
            e.preventDefault();
            localStorage.removeItem('wizzardchat_token');
            window.location.href = '/login';
        });
    }

    // Wire theme toggle
    var toggle = document.getElementById('themeToggle');
    if (toggle) {
        var currentTheme = localStorage.getItem(WC_THEME_KEY) || 'dark';
        toggle.checked = (currentTheme === 'light');
        toggle.addEventListener('change', function () {
            applyTheme(toggle.checked ? 'light' : 'dark');
        });
    }
}

document.addEventListener('DOMContentLoaded', function () {

    // ─── Auto-mark active nav link from current URL ───────────────────────────
    var path = window.location.pathname;
    // Only manage the 'active' class — never touch text-white (CSS handles colour)
    document.querySelectorAll('#sidebar .nav-link').forEach(function (a) {
        a.classList.remove('active');
    });
    document.querySelectorAll('#sidebar .nav-link[href]').forEach(function (a) {
        var href = a.getAttribute('href').split('?')[0];
        if (href === path) {
            a.classList.add('active');
        }
    });

    // ─── Accordion init: only open section with active link (restore user toggles) ──
    // All sections collapsed by default; user-toggled state persists across pages
    var _savedNav = localStorage.getItem(WC_NAV_STATE_KEY);
    var _navState = _savedNav ? JSON.parse(_savedNav) : {};
    document.querySelectorAll('.nav-section-body').forEach(function (body) {
        var shouldOpen = (body.id && _navState[body.id] === true);
        body.classList.toggle('collapsed', !shouldOpen);
        var hdr = body.previousElementSibling;
        if (hdr) {
            var chev = hdr.querySelector('.section-chev');
            if (chev) chev.classList.toggle('collapsed', !shouldOpen);
        }
    });

    // ─── Profile dropdown + availability ─────────────────────────────────────
    injectProfileDropdown();

    // ─── Availability selector ────────────────────────────────────────────────
    const AV_KEY = 'wizzardchat_availability';
    const sel = document.getElementById('availabilitySelect');
    if (sel) {
        const stored = localStorage.getItem(AV_KEY) || 'offline';
        sel.value = stored;
        sel.className = 'form-select form-select-sm av-' + stored;
        // On non-agent pages: persist to localStorage; agent.js handles WS sync
        sel.addEventListener('change', function () {
            const status = sel.value;
            sel.className = 'form-select form-select-sm av-' + status;
            localStorage.setItem(AV_KEY, status);
        });
    }

    // ─── Display logged-in agent name ─────────────────────────────────────────
    const nameEl = document.getElementById('agentName');
    if (nameEl) {
        const token = localStorage.getItem('wizzardchat_token');
        if (!token) return;
        fetch('/api/v1/auth/me', {
            headers: { 'Authorization': 'Bearer ' + token }
        }).then(function (r) {
            if (!r.ok) return null;
            return r.json();
        }).then(function (user) {
            if (user) {
                const displayName = user.full_name || user.username;
                nameEl.textContent = displayName;
                // Also update the dropdown header
                const profileName = document.getElementById('profileName');
                if (profileName) profileName.textContent = displayName;
            }
        }).catch(function () { /* ignore – page JS will handle 401 redirect */ });
    }
});
