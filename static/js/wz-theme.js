/**
 * wz-theme.js — WizzardChat badge / status colour theme loader.
 *
 * Runs immediately (before DOMContentLoaded) so there is no colour flash.
 * Reads overrides stored by the Badge Colors settings panel and writes
 * them onto :root as CSS custom properties.
 *
 * Storage key: 'wz_badge_theme'  (JSON object: { "--wz-var-name": "#hex" })
 */
(function () {
    var STORAGE_KEY = 'wz_badge_theme';
    try {
        var raw = localStorage.getItem(STORAGE_KEY);
        if (!raw) return;
        var vars = JSON.parse(raw);
        var root = document.documentElement;
        Object.keys(vars).forEach(function (k) {
            if (vars[k]) root.style.setProperty(k, vars[k]);
        });
    } catch (e) { /* silent — never block page render */ }

    /* Expose helpers so the settings page can call them */
    window.wzTheme = {
        STORAGE_KEY: STORAGE_KEY,

        /** Apply a full theme object to :root and save to localStorage */
        apply: function (vars) {
            var root = document.documentElement;
            Object.keys(vars).forEach(function (k) {
                if (vars[k]) root.style.setProperty(k, vars[k]);
            });
            localStorage.setItem(STORAGE_KEY, JSON.stringify(vars));
        },

        /** Read the currently stored theme (or empty object) */
        load: function () {
            try { return JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}'); }
            catch (e) { return {}; }
        },

        /** Remove all overrides and reload so CSS defaults take over */
        reset: function () {
            localStorage.removeItem(STORAGE_KEY);
            location.reload();
        },
    };
}());
