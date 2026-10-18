'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const paths = require('../static/local_paths.js');

test('filenames and batch exports support Windows, UNC and POSIX sources', () => {
  for (const [file, expected] of [
    ['D:\\照片 & 底片\\旅行 01\\底片.tif', 'D:/照片 & 底片/旅行 01/去色罩输出/'],
    ['D:/照片/底片.tif', 'D:/照片/去色罩输出/'],
    ['\\\\NAS\\共享文件夹\\底片.tif', '//NAS/共享文件夹/去色罩输出/'],
    ['/Users/me/照片/底片.tif', '/Users/me/照片/去色罩输出/'],
  ]) {
    assert.equal(paths.basename(file), '底片.tif');
    assert.equal(paths.exportDirectory(file, ''), expected);
  }
});

test('selected directories preserve drive/UNC roots and POSIX backslashes', () => {
  assert.equal(paths.exportDirectory('', 'D:\\'), 'D:/');
  assert.equal(paths.exportDirectory('', '\\\\NAS\\Photos\\'), '\\\\NAS\\Photos/');
  assert.equal(paths.exportDirectory('', '/'), '/');
  assert.equal(paths.basename('/tmp/has\\backslash.jpg'), 'has\\backslash.jpg');
});
