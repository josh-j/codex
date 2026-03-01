(function () {
  'use strict';

  // Signal to CSS that JS is active; scopes all collapsible affordances
  document.documentElement.classList.add('js');

  // ---- widget toggle (titlebar button) ----

  function initWidgetToggles() {
    var titlebars = document.querySelectorAll('.widget-titlebar');
    for (var i = 0; i < titlebars.length; i++) {
      (function (bar) {
        var btn = bar.querySelector('.widget-toggle');
        if (!btn) return;

        bar.addEventListener('click', function (e) {
          // If the user clicked a link inside the titlebar, don't toggle
          if (e.target.closest('a')) return;

          var widget = bar.closest('.widget');
          if (!widget) return;
          var body = widget.querySelector('.widget-body');
          if (!body) return;

          var expanded = btn.getAttribute('aria-expanded') !== 'false';
          body.style.display = expanded ? 'none' : '';
          btn.setAttribute('aria-expanded', expanded ? 'false' : 'true');
        });
      })(titlebars[i]);
    }
  }

  // ---- .group-hdr / .group-row (site report alert groups) ----

  function initGroupToggles() {
    var headers = document.querySelectorAll('tr.group-hdr');
    for (var i = 0; i < headers.length; i++) {
      (function (hdr) {
        hdr.addEventListener('click', function () {
          var gid = hdr.getAttribute('data-group');
          if (!gid) return;
          var rows = document.querySelectorAll('tr.group-row[data-group="' + gid + '"]');
          var anyVisible = false;
          for (var j = 0; j < rows.length; j++) {
            if (rows[j].style.display !== 'none') { anyVisible = true; break; }
          }
          for (var k = 0; k < rows.length; k++) {
            rows[k].style.display = anyVisible ? 'none' : '';
          }
          hdr.classList.toggle('group-hdr-collapsed', anyVisible);
        });
      })(headers[i]);
    }
  }

  // ---- expand / collapse all ----

  function expandAll() {
    document.querySelectorAll('.widget-body').forEach(function (el) { el.style.display = ''; });
    document.querySelectorAll('.widget-toggle').forEach(function (btn) { btn.setAttribute('aria-expanded', 'true'); });
    document.querySelectorAll('tr.group-row').forEach(function (el) { el.style.display = ''; });
    document.querySelectorAll('tr.group-hdr.group-hdr-collapsed').forEach(function (el) { el.classList.remove('group-hdr-collapsed'); });
  }

  function collapseAll() {
    document.querySelectorAll('.widget-body').forEach(function (el) { el.style.display = 'none'; });
    document.querySelectorAll('.widget-toggle').forEach(function (btn) { btn.setAttribute('aria-expanded', 'false'); });
    document.querySelectorAll('tr.group-row').forEach(function (el) { el.style.display = 'none'; });
    document.querySelectorAll('tr.group-hdr').forEach(function (el) { el.classList.add('group-hdr-collapsed'); });
  }

  // ---- TOC actions (expand / collapse all) ----
 
  function injectTOCActions() {
    var toc = document.querySelector('.toc');
    if (!toc) return;
 
    var actions = document.createElement('div');
    actions.className = 'toc-right';
 
    var lkExpand = document.createElement('a');
    lkExpand.href = '#';
    lkExpand.textContent = 'Expand all';
    lkExpand.addEventListener('click', function(e) { e.preventDefault(); expandAll(); });
 
    var lkCollapse = document.createElement('a');
    lkCollapse.href = '#';
    lkCollapse.textContent = 'Collapse all';
    lkCollapse.addEventListener('click', function(e) { e.preventDefault(); collapseAll(); });
 
    actions.appendChild(lkExpand);
    actions.appendChild(lkCollapse);
    toc.appendChild(actions);
  }
 
  // ---- init ----
 
  document.addEventListener('DOMContentLoaded', function () {
    initWidgetToggles();
    initGroupToggles();
    injectTOCActions();
  });
}());
