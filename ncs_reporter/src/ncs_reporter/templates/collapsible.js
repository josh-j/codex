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
    document.querySelectorAll('details').forEach(function (el) { el.open = true; });
  }

  function collapseAll() {
    document.querySelectorAll('.widget-body').forEach(function (el) { el.style.display = 'none'; });
    document.querySelectorAll('.widget-toggle').forEach(function (btn) { btn.setAttribute('aria-expanded', 'false'); });
    document.querySelectorAll('tr.group-row').forEach(function (el) { el.style.display = 'none'; });
    document.querySelectorAll('tr.group-hdr').forEach(function (el) { el.classList.add('group-hdr-collapsed'); });
    document.querySelectorAll('details').forEach(function (el) { el.open = false; });
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
 
    var lkPrint = document.createElement('a');
    lkPrint.href = '#';
    lkPrint.textContent = 'Print report';
    lkPrint.addEventListener('click', function(e) { e.preventDefault(); window.print(); });

    actions.appendChild(lkExpand);
    actions.appendChild(lkCollapse);
    actions.appendChild(lkPrint);
    toc.appendChild(actions);
  }

  // ---- nav dropdown accessibility (keyboard + touch) ----

  function initNavDropdowns() {
    var trees = document.querySelectorAll('.nav-tree');
    for (var i = 0; i < trees.length; i++) {
      (function (tree, idx) {
        var trigger = tree.querySelector('.tree-trigger');
        var dropdown = tree.querySelector('.nav-dropdown');
        if (!trigger || !dropdown) return;

        if (!dropdown.id) dropdown.id = 'nav-dropdown-' + idx;
        trigger.setAttribute('role', 'button');
        trigger.setAttribute('tabindex', '0');
        trigger.setAttribute('aria-haspopup', 'menu');
        trigger.setAttribute('aria-controls', dropdown.id);
        trigger.setAttribute('aria-expanded', 'false');

        function setOpen(open) {
          tree.classList.toggle('nav-tree-open', open);
          trigger.setAttribute('aria-expanded', open ? 'true' : 'false');
        }

        function toggleOpen(e) {
          if (e) e.preventDefault();
          var isOpen = tree.classList.contains('nav-tree-open');
          setOpen(!isOpen);
        }

        trigger.addEventListener('click', toggleOpen);
        trigger.addEventListener('keydown', function (e) {
          if (e.key === 'Enter' || e.key === ' ') toggleOpen(e);
          if (e.key === 'Escape') setOpen(false);
        });

        tree.addEventListener('keydown', function (e) {
          if (e.key === 'Escape') setOpen(false);
        });

        document.addEventListener('click', function (e) {
          if (!tree.contains(e.target)) setOpen(false);
        });
      })(trees[i], i);
    }
  }
 
  // ---- table sorting ----

  function _sortCompare(cellA, cellB, isAsc) {
    var numA = parseFloat(cellA.replace(/[^0-9.-]+/g, ""));
    var numB = parseFloat(cellB.replace(/[^0-9.-]+/g, ""));
    if (!isNaN(numA) && !isNaN(numB) && cellA.match(/^[0-9.,\s%MBGBKB]+$/) && cellB.match(/^[0-9.,\s%MBGBKB]+$/)) {
      return isAsc ? numB - numA : numA - numB;
    }
    return isAsc
      ? cellB.localeCompare(cellA, undefined, { numeric: true, sensitivity: 'base' })
      : cellA.localeCompare(cellB, undefined, { numeric: true, sensitivity: 'base' });
  }

  function initTableSorting() {
    var sortableHeaders = document.querySelectorAll('th.sortable');
    for (var i = 0; i < sortableHeaders.length; i++) {
      (function (header) {
        header.addEventListener('click', function () {
          var table = header.closest('table');
          var tbody = table.querySelector('tbody');
          var colIndex = Array.prototype.indexOf.call(header.parentNode.children, header);
          var isAsc = header.classList.contains('sort-asc');

          // Reset other headers in the same table
          var otherHeaders = header.parentNode.querySelectorAll('th.sortable');
          for (var j = 0; j < otherHeaders.length; j++) {
            if (otherHeaders[j] !== header) {
              otherHeaders[j].classList.remove('sort-asc', 'sort-desc');
            }
          }

          var hasGroups = tbody.querySelector('tr.group-hdr') !== null;

          if (hasGroups) {
            // Group-aware sort: sort rows within each group, keep groups in place
            var groupHeaders = Array.prototype.slice.call(tbody.querySelectorAll('tr.group-hdr'));
            for (var g = 0; g < groupHeaders.length; g++) {
              var gid = groupHeaders[g].getAttribute('data-group');
              var groupRows = Array.prototype.slice.call(
                tbody.querySelectorAll('tr.group-row[data-group="' + gid + '"]')
              );
              groupRows.sort(function (a, b) {
                return _sortCompare(
                  a.children[colIndex].textContent.trim(),
                  b.children[colIndex].textContent.trim(),
                  isAsc
                );
              });
              // Re-insert after the group header
              var anchor = groupHeaders[g];
              for (var r = 0; r < groupRows.length; r++) {
                anchor.parentNode.insertBefore(groupRows[r], anchor.nextSibling);
                anchor = groupRows[r];
              }
            }
          } else {
            // Simple flat sort
            var rows = Array.prototype.slice.call(tbody.querySelectorAll('tr'));
            rows.sort(function (a, b) {
              return _sortCompare(
                a.children[colIndex].textContent.trim(),
                b.children[colIndex].textContent.trim(),
                isAsc
              );
            });
            for (var k = 0; k < rows.length; k++) {
              tbody.appendChild(rows[k]);
            }
          }

          header.classList.toggle('sort-asc', !isAsc);
          header.classList.toggle('sort-desc', isAsc);
        });
      })(sortableHeaders[i]);
    }
  }

  // ---- global host search ----

  function initHostSearch() {
    var searchContainer = document.querySelector('.nav-search');
    if (!searchContainer) return;

    var searchInput = searchContainer.querySelector('input');
    var searchResults = searchContainer.querySelector('.search-results');
    if (!searchInput || !searchResults) return;

    var rootPath = searchContainer.getAttribute('data-root') || './';
    var searchIndex = window.NCS_SEARCH_INDEX || null;

    // Load search index script if missing (CORS-friendly for file:// protocol)
    function loadSearchIndexScript() {
      if (window.NCS_SEARCH_INDEX) {
        searchIndex = window.NCS_SEARCH_INDEX;
        return;
      }
      var script = document.createElement('script');
      script.src = rootPath + 'search_index.js';
      script.onload = function() {
        searchIndex = window.NCS_SEARCH_INDEX;
        renderResults(searchInput.value.toLowerCase().trim());
      };
      document.head.appendChild(script);
    }

    // Local filtering (keep for current page)
    function filterLocalTables(query) {
      var tables = document.querySelectorAll('table');
      for (var i = 0; i < tables.length; i++) {
        var table = tables[i];
        var rows = table.querySelectorAll('tbody tr:not(.group-hdr)');
        var groupHeaders = table.querySelectorAll('tr.group-hdr');

        for (var gh = 0; gh < groupHeaders.length; gh++) {
          groupHeaders[gh].style.display = '';
        }

        for (var j = 0; j < rows.length; j++) {
          var row = rows[j];
          if (query === '' || row.textContent.toLowerCase().indexOf(query) !== -1) {
            row.style.display = '';
          } else {
            row.style.display = 'none';
          }
        }

        for (var k = 0; k < groupHeaders.length; k++) {
          var groupHdr = groupHeaders[k];
          var gid = groupHdr.getAttribute('data-group');
          var groupRows = table.querySelectorAll('tr.group-row[data-group="' + gid + '"]');
          var groupMatch = false;
          for (var r = 0; r < groupRows.length; r++) {
            if (groupRows[r].style.display !== 'none') { groupMatch = true; break; }
          }
          if (query !== '' && !groupMatch) groupHdr.style.display = 'none';
        }
      }
    }

    function renderResults(query) {
      if (!searchIndex) return;
      searchResults.innerHTML = '';
      if (!query) {
        searchResults.style.display = 'none';
        return;
      }

      var matches = [];
      for (var i = 0; i < searchIndex.length; i++) {
        if (searchIndex[i].h.toLowerCase().indexOf(query) !== -1) {
          matches.push(searchIndex[i]);
        }
        if (matches.length >= 15) break; // limit results
      }

      if (matches.length === 0) {
        var empty = document.createElement('div');
        empty.className = 'dropdown-group';
        empty.textContent = 'No hosts found';
        searchResults.appendChild(empty);
      } else {
        for (var j = 0; j < matches.length; j++) {
          var match = matches[j];
          var a = document.createElement('a');
          a.href = rootPath + match.u;
          
          var textSpan = document.createElement('span');
          textSpan.textContent = match.h;
          a.appendChild(textSpan);
          
          if (match.p) {
            var badge = document.createElement('span');
            badge.className = 'platform-badge';
            badge.textContent = match.p;
            a.appendChild(badge);
          }
          
          searchResults.appendChild(a);
        }
      }
      searchResults.style.display = 'block';
    }

    searchInput.addEventListener('focus', function() {
      if (!searchIndex) loadSearchIndexScript();
      renderResults(searchInput.value.toLowerCase().trim());
    });

    searchInput.addEventListener('input', function (e) {
      var query = e.target.value.toLowerCase().trim();
      filterLocalTables(query);
      
      if (searchIndex) {
        renderResults(query);
      } else if (query.length > 0) {
        loadSearchIndexScript();
      }
    });

    // Close dropdown on click outside or escape
    document.addEventListener('click', function(e) {
      if (!searchContainer.contains(e.target)) {
        searchResults.style.display = 'none';
      }
    });

    searchInput.addEventListener('keydown', function(e) {
      if (e.key === 'Escape') {
        searchResults.style.display = 'none';
        searchInput.blur();
      }
    });
  }

  // ---- theme toggle (light/dark) ----

  function initThemeToggle() {
    var saved = localStorage.getItem('ncs-theme');
    if (saved === 'light') document.documentElement.classList.add('light');

    var btn = document.createElement('button');
    btn.className = 'theme-toggle';
    btn.title = 'Toggle light/dark mode';
    btn.setAttribute('aria-label', 'Toggle light/dark mode');
    btn.textContent = document.documentElement.classList.contains('light') ? '\u2600' : '\u263E';
    btn.addEventListener('click', function () {
      var isLight = document.documentElement.classList.toggle('light');
      btn.textContent = isLight ? '\u2600' : '\u263E';
      localStorage.setItem('ncs-theme', isLight ? 'light' : 'dark');
    });

    // Insert next to the search bar in the breadcrumb
    var searchBar = document.querySelector('.nav-search');
    if (searchBar) {
      searchBar.parentNode.insertBefore(btn, searchBar.nextSibling);
    } else {
      // Fallback: insert into breadcrumb or toc
      var breadcrumb = document.querySelector('.breadcrumb') || document.querySelector('.toc');
      if (breadcrumb) {
        breadcrumb.appendChild(btn);
      } else {
        document.body.appendChild(btn);
      }
    }
  }

  // ---- init ----

  function init() {
    initWidgetToggles();
    initGroupToggles();
    injectTOCActions();
    initNavDropdowns();
    initTableSorting();
    initHostSearch();
    initThemeToggle();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
}());
