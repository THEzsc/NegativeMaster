/* Local filesystem paths, independent of the browser's operating system. */
(function (root) {
  'use strict';
  const windowsPath = value => /^[A-Za-z]:[\\/]/.test(value) || value.startsWith('\\\\');
  const separators = value => windowsPath(value) ? /[\\/]/ : /\//;
  const basename = value => String(value).split(separators(String(value))).pop();
  function exportDirectory(file, selected) {
    if (selected) return selected.replace(windowsPath(selected) ? /[\\/]+$/ : /\/+$/, '') + '/';
    const parts = String(file).split(separators(String(file)));
    parts.pop();
    return parts.join('/') + '/去色罩输出/';
  }
  const api = {basename, exportDirectory};
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.LocalPaths = api;
})(typeof globalThis === 'object' ? globalThis : this);
