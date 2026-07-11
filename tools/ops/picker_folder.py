#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
picker_folder.py - 文件夹勾选工具

子命令:
  scan     扫描父文件夹，生成 HTML 勾选页面
  to-list  把导出的 JSON 转成 list.txt

工作流:
  1. python picker_folder.py scan --parent <dir> [--precheck <json>] [-o picker_folder.html]
  2. 浏览器打开 picker_folder.html，勾选/调整后点"导出 JSON"得到 selected.json
  3. (可选) 把 selected.json 发给 AI 修改，再点"导入 JSON"继续调整
  4. python picker_folder.py to-list selected.json [-o list.txt]

JSON 格式 (selected.json):
  {
    "parent_dir": "E:\\Code\\loveMentor",
    "selected_at": "2026-07-02T10:30:00",
    "selected": [
      {"path": "E:\\Code\\loveMentor\\sub1", "size_mb": 12.3, "files": 45}
    ]
  }

  - 最小表示：勾父就不列子孙
  - 导入时只读 path，元数据以扫描数据为准
  - 预勾选 JSON 可省略 size_mb/files 字段
"""

import argparse
import json
import os
import sys
from pathlib import Path


def scan_folder(parent_dir):
    """递归扫描 parent_dir 下所有子文件夹（含 parent_dir 本身）。

    返回 dict: path_str -> {path, name, size_bytes, files, children, is_root}
    """
    parent = Path(parent_dir)
    dir_info = {}

    for root, dirs, files in os.walk(parent, topdown=False):
        root_path = Path(root)
        root_str = str(root_path)

        size_bytes = 0
        file_count = 0
        for fname in files:
            fpath = root_path / fname
            try:
                size_bytes += fpath.stat().st_size
                file_count += 1
            except (OSError, PermissionError):
                pass

        children_paths = []
        for d in dirs:
            child_str = str(root_path / d)
            children_paths.append(child_str)
            if child_str in dir_info:
                size_bytes += dir_info[child_str]['size_bytes']
                file_count += dir_info[child_str]['files']

        is_root = (root_path == parent)
        dir_info[root_str] = {
            'path': root_str,
            'name': parent.name if is_root else root_path.name,
            'size_bytes': size_bytes,
            'files': file_count,
            'children': children_paths,
            'is_root': is_root,
        }

    return dir_info


def normalize_precheck(paths, dir_info):
    """规范化预勾选路径列表：只保留存在的路径，去掉被祖先包含的子路径。

    返回 (minimal_set, ignored_count)
    """
    valid_set = set()
    ignored_count = 0
    for p in paths:
        if p in dir_info:
            valid_set.add(p)
        else:
            ignored_count += 1

    parent_map = {}
    for path, info in dir_info.items():
        for child in info['children']:
            parent_map[child] = path

    minimal = set()
    for p in valid_set:
        dominated = False
        cur = parent_map.get(p)
        while cur is not None:
            if cur in valid_set:
                dominated = True
                break
            cur = parent_map.get(cur)
        if not dominated:
            minimal.add(p)

    return minimal, ignored_count


def build_tree_data(parent_dir, dir_info, precheck_paths):
    """构建要嵌入 HTML 的 JSON 数据。按前序 DFS 排序，确保父在子前、同级按名字排序。"""
    parent_path = Path(parent_dir)
    root_str = str(parent_path)

    def make_node(path):
        info = dir_info[path]
        p = Path(path)
        try:
            rel = p.relative_to(parent_path)
            rel_str = '.' if str(rel) == '.' else str(rel)
        except ValueError:
            rel_str = path
        return {
            'path': info['path'],
            'name': info['name'],
            'rel_path': rel_str,
            'size_bytes': info['size_bytes'],
            'size_mb': round(info['size_bytes'] / (1024 * 1024), 1),
            'files': info['files'],
            'children': info['children'],
            'is_root': info['is_root'],
        }

    nodes = []
    if root_str in dir_info:
        def dfs(path):
            nodes.append(make_node(path))
            children_sorted = sorted(
                dir_info[path]['children'],
                key=lambda cp: dir_info[cp]['name'].lower()
            )
            for cp in children_sorted:
                dfs(cp)
        dfs(root_str)
    else:
        for path in dir_info:
            nodes.append(make_node(path))

    return {
        'parent_dir': str(parent_path),
        'nodes': nodes,
        'precheck': sorted(precheck_paths),
    }


HTML_TEMPLATE = r'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>文件夹勾选 - __TITLE__</title>
<style>
  * { box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", sans-serif; margin: 0; padding: 0; font-size: 14px; color: #222; background: #fafafa; }
  .toolbar { position: sticky; top: 0; background: #fff; padding: 10px 14px; border-bottom: 1px solid #ddd; display: flex; gap: 8px; align-items: center; flex-wrap: wrap; z-index: 10; box-shadow: 0 1px 3px rgba(0,0,0,0.05); }
  .toolbar input[type="text"] { padding: 5px 10px; border: 1px solid #ccc; border-radius: 4px; min-width: 220px; font-size: 13px; }
  .toolbar input[type="text"]:focus { outline: none; border-color: #4a90d9; }
  .toolbar input[type="number"] { padding: 5px 8px; border: 1px solid #ccc; border-radius: 4px; width: 90px; font-size: 13px; }
  .toolbar input[type="number"]:focus { outline: none; border-color: #4a90d9; }
  .toolbar .priority-label { font-size: 12px; color: #555; margin-right: -4px; }
  .toolbar button { padding: 5px 12px; border: 1px solid #ccc; background: #fff; border-radius: 4px; cursor: pointer; font-size: 13px; }
  .toolbar button:hover { background: #f0f0f0; border-color: #aaa; }
  .toolbar button.primary { background: #4a90d9; color: #fff; border-color: #3a7bc8; }
  .toolbar button.primary:hover { background: #3a7bc8; }
  .status { margin-left: auto; color: #555; font-size: 12px; padding: 4px 10px; background: #f5f5f5; border-radius: 4px; }
  #tree { padding: 8px 14px; max-width: 1200px; margin: 0 auto; }
  .row { display: flex; align-items: stretch; padding: 0 6px 0 0; border-radius: 3px; cursor: default; min-height: 26px; }
  .row:hover { background: #eef5ff; }
  .row-content { display: flex; align-items: center; gap: 6px; flex: 1; padding: 3px 0; }
  .indent-line { width: 18px; flex-shrink: 0; border-left: 1px solid #e8e8e8; align-self: stretch; }
  .indent-line.last { border-left: 1px solid transparent; }
  .toggle { width: 16px; cursor: pointer; user-select: none; color: #888; text-align: center; flex-shrink: 0; font-size: 11px; }
  .toggle.leaf { color: transparent; cursor: default; }
  .toggle:hover { color: #333; }
  .row input[type="checkbox"] { margin: 0; flex-shrink: 0; cursor: pointer; width: 14px; height: 14px; }
  .name { font-weight: 500; }
  .name.root { font-weight: 700; color: #333; }
  .meta { color: #888; font-size: 12px; }
  .relpath { color: #b0b0b0; font-size: 12px; margin-left: 4px; font-family: Consolas, "Courier New", monospace; }
  .priority-tag { color: #4a90d9; font-size: 11px; background: #e8f2fd; padding: 1px 5px; border-radius: 3px; font-weight: 600; }
  .empty { padding: 40px; text-align: center; color: #999; }
  .toast { position: fixed; bottom: 20px; left: 50%; transform: translateX(-50%); background: #333; color: #fff; padding: 10px 20px; border-radius: 4px; opacity: 0; transition: opacity 0.3s; pointer-events: none; font-size: 13px; z-index: 100; }
  .toast.show { opacity: 1; }
</style>
</head>
<body>
<div class="toolbar">
  <input type="text" id="search" placeholder="按文件夹名搜索...">
  <button onclick="selectAll(true)">全选</button>
  <button onclick="selectAll(false)">全不选</button>
  <button onclick="expandAll(true)">展开全部</button>
  <button onclick="expandAll(false)">折叠全部</button>
  <button onclick="expandChecked()">展开已勾</button>
  <button onclick="document.getElementById('fileInput').click()">导入 JSON</button>
  <span class="priority-label">优先级:</span>
  <input type="number" id="batchPriority" placeholder="批次" title="导出时赋予新勾选文件夹的优先级（整数）">
  <button class="primary" onclick="exportJson('minimal')">导出 JSON</button>
  <button onclick="exportJson('full')">导出全量</button>
  <input type="file" id="fileInput" accept=".json" style="display:none">
  <span class="status" id="status"></span>
</div>
<div id="tree"></div>
<div class="toast" id="toast"></div>

<script>
const DATA = __DATA_JSON__;
const nodes = DATA.nodes;
const nodeByPath = new Map(nodes.map(n => [n.path, n]));
const parentDir = DATA.parent_dir;
const parentMap = new Map();
nodes.forEach(n => { n.children.forEach(cp => parentMap.set(cp, n.path)); });

const checkState = new Map();
const expanded = new Map();
const priorityMap = new Map();
nodes.forEach(n => {
  checkState.set(n.path, 'unchecked');
  expanded.set(n.path, n.is_root);
});

function parentOf(path) { return parentMap.get(path) || null; }

function setChecked(path, checked) {
  const node = nodeByPath.get(path);
  if (!node) return;
  checkState.set(path, checked ? 'checked' : 'unchecked');
  if (!checked) {
    clearPriorityRecursive(path);
  }
  node.children.forEach(cp => setChecked(cp, checked));
  updateAncestors(path);
}

function clearPriorityRecursive(path) {
  priorityMap.delete(path);
  const node = nodeByPath.get(path);
  if (node) {
    node.children.forEach(cp => clearPriorityRecursive(cp));
  }
}

function updateAncestors(path) {
  let parent = parentOf(path);
  while (parent !== null) {
    const pNode = nodeByPath.get(parent);
    const childStates = pNode.children.map(cp => checkState.get(cp));
    const allChecked = childStates.every(s => s === 'checked');
    const noneChecked = childStates.every(s => s === 'unchecked');
    let newState;
    if (allChecked) newState = 'checked';
    else if (noneChecked) newState = 'unchecked';
    else newState = 'indeterminate';
    checkState.set(parent, newState);
    parent = parentOf(parent);
  }
}

function toggleCheck(path) {
  const state = checkState.get(path);
  setChecked(path, state !== 'checked');
}

function toggleExpand(path) {
  expanded.set(path, !expanded.get(path));
  render();
}

function selectAll(checked) {
  const searchTerm = document.getElementById('search').value.trim().toLowerCase();
  if (searchTerm) {
    nodes.forEach(n => {
      if (n.name.toLowerCase().includes(searchTerm)) {
        setChecked(n.path, checked);
      }
    });
  } else {
    const root = nodes.find(n => n.is_root);
    if (root) setChecked(root.path, checked);
  }
  render();
}

function expandAll(doExpand) {
  nodes.forEach(n => expanded.set(n.path, doExpand));
  render();
}

function expandChecked() {
  nodes.forEach(n => {
    if (hasCheckedOrIndeterminate(n.path)) {
      expanded.set(n.path, true);
    }
  });
  render();
}

function hasCheckedOrIndeterminate(path) {
  const s = checkState.get(path);
  if (s === 'checked' || s === 'indeterminate') return true;
  const node = nodeByPath.get(path);
  for (const cp of node.children) {
    if (hasCheckedOrIndeterminate(cp)) return true;
  }
  return false;
}

function formatSize(mb) {
  if (mb < 0.1) return '< 0.1 MB';
  if (mb < 1024) return mb.toFixed(1) + ' MB';
  return (mb / 1024).toFixed(2) + ' GB';
}

function getDepth(path) {
  let d = 0;
  let cur = parentOf(path);
  while (cur !== null) { d++; cur = parentOf(cur); }
  return d;
}

function getMinimalSelected() {
  const result = [];
  nodes.forEach(n => {
    if (checkState.get(n.path) !== 'checked') return;
    const parent = parentOf(n.path);
    if (parent === null || checkState.get(parent) !== 'checked') {
      result.push(n.path);
    }
  });
  return result;
}

function applyPrecheck(items) {
  // items: [{path, priority?}, ...]
  const validSet = new Set();
  let ignored = 0;
  items.forEach(item => {
    if (nodeByPath.has(item.path)) validSet.add(item.path);
    else ignored++;
  });
  const minimal = new Set();
  validSet.forEach(p => {
    let dominated = false;
    let cur = parentOf(p);
    while (cur !== null) {
      if (validSet.has(cur)) { dominated = true; break; }
      cur = parentOf(cur);
    }
    if (!dominated) minimal.add(p);
  });
  priorityMap.clear();
  nodes.forEach(n => checkState.set(n.path, 'unchecked'));
  minimal.forEach(p => setChecked(p, true));
  items.forEach(item => {
    if (item.priority !== undefined && item.priority !== null && validSet.has(item.path)) {
      priorityMap.set(item.path, item.priority);
    }
  });
  return { applied: minimal.size, ignored };
}

function render() {
  const tree = document.getElementById('tree');
  const searchTerm = document.getElementById('search').value.trim().toLowerCase();

  let searchVisible = null;
  if (searchTerm) {
    searchVisible = new Set();
    nodes.forEach(n => {
      if (n.name.toLowerCase().includes(searchTerm)) {
        let cur = n.path;
        while (cur !== null) {
          searchVisible.add(cur);
          cur = parentOf(cur);
        }
      }
    });
  }

  let html = '';
  let visibleCount = 0;
  nodes.forEach(n => {
    if (searchVisible) {
      if (!searchVisible.has(n.path)) return;
    } else {
      let cur = parentOf(n.path);
      let visible = true;
      while (cur !== null) {
        if (!expanded.get(cur)) { visible = false; break; }
        cur = parentOf(cur);
      }
      if (!visible) return;
    }
    visibleCount++;

    const depth = getDepth(n.path);
    const state = checkState.get(n.path);
    const isLeaf = n.children.length === 0;
    const toggleChar = isLeaf ? '' : (expanded.get(n.path) ? '\u25BC' : '\u25B6');

    html += '<div class="row" data-path="' + escapeAttr(n.path) + '">';
    for (let i = 0; i < depth; i++) {
      html += '<span class="indent-line"></span>';
    }
    html += '<div class="row-content">';
    html += '<span class="toggle ' + (isLeaf ? 'leaf' : '') + '" data-action="toggle">' + toggleChar + '</span>';
    html += '<input type="checkbox" data-action="check">';
    html += '<span class="name ' + (n.is_root ? 'root' : '') + '">' + escapeHtml(n.name) + '</span>';
    html += '<span class="meta">(' + formatSize(n.size_mb) + ' \u00b7 ' + n.files + ' \u6587\u4ef6)</span>';
    const pri = priorityMap.get(n.path);
    if (pri !== undefined) {
      html += '<span class="priority-tag">[P:' + pri + ']</span>';
    }
    if (!n.is_root) {
      html += '<span class="relpath">' + escapeHtml(n.rel_path) + '</span>';
    }
    html += '</div>';
    html += '</div>';
  });

  if (visibleCount === 0) {
    html = '<div class="empty">\u65e0\u5339\u914d\u7ed3\u679c</div>';
  }

  tree.innerHTML = html;

  tree.querySelectorAll('input[data-action="check"]').forEach(cb => {
    const row = cb.closest('.row');
    const path = row.dataset.path;
    const state = checkState.get(path);
    cb.checked = (state === 'checked');
    cb.indeterminate = (state === 'indeterminate');
  });

  updateStatus();
}

function updateStatus() {
  let allChecked = 0;
  nodes.forEach(n => {
    if (checkState.get(n.path) === 'checked') allChecked++;
  });
  const minimal = getMinimalSelected();
  let totalBytes = 0, totalFiles = 0;
  minimal.forEach(p => {
    const n = nodeByPath.get(p);
    totalBytes += n.size_bytes;
    totalFiles += n.files;
  });
  document.getElementById('status').textContent =
    '\u5df2\u52fe ' + allChecked + ' \u4e2a \u00b7 \u6700\u5c0f\u8868\u793a ' + minimal.length +
    ' \u4e2a \u00b7 \u5171 ' + formatSize(totalBytes / (1024*1024)) +
    ' \u00b7 ' + totalFiles + ' \u6587\u4ef6';
}

function exportJson(mode) {
  // mode: 'minimal' (默认) 只导出最小表示的勾选项
  //       'full'      导出所有节点，带 selected 字段
  mode = mode || 'minimal';
  const batchInput = document.getElementById('batchPriority').value;
  const batchP = parseInt(batchInput);
  if (isNaN(batchP)) {
    showToast('\u8bf7\u8f93\u5165\u6279\u6b21\u4f18\u5148\u7ea7\uff08\u6574\u6570\uff09');
    return;
  }

  // 粘性赋值：所有 checked 且无 priority 的节点赋值为 batchP，有值的保留
  nodes.forEach(n => {
    if (checkState.get(n.path) === 'checked' && !priorityMap.has(n.path)) {
      priorityMap.set(n.path, batchP);
    }
  });

  const now = new Date();
  const pad = (x) => String(x).padStart(2, '0');
  const ts = now.getFullYear() + '-' + pad(now.getMonth()+1) + '-' + pad(now.getDate()) +
             'T' + pad(now.getHours()) + ':' + pad(now.getMinutes()) + ':' + pad(now.getSeconds());

  let selected;
  if (mode === 'full') {
    selected = nodes.map(n => ({
      path: n.path,
      size_mb: n.size_mb,
      files: n.files,
      selected: checkState.get(n.path) === 'checked',
      priority: priorityMap.has(n.path) ? priorityMap.get(n.path) : null
    }));
  } else {
    const minimal = getMinimalSelected();
    if (minimal.length === 0) {
      showToast('\u672a\u52fe\u9009\u4efb\u4f55\u6587\u4ef6\u5939');
      return;
    }
    selected = minimal.map(p => {
      const n = nodeByPath.get(p);
      return {
        path: n.path,
        size_mb: n.size_mb,
        files: n.files,
        priority: priorityMap.has(p) ? priorityMap.get(p) : null
      };
    });
  }

  const output = {
    parent_dir: parentDir,
    selected_at: ts,
    export_mode: mode,
    batch_priority: batchP,
    selected: selected,
  };

  const blob = new Blob([JSON.stringify(output, null, 2)], { type: 'application/json;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = mode === 'full' ? 'selected_full.json' : 'selected.json';
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
  if (mode === 'full') {
    const checkedCount = selected.filter(s => s.selected).length;
    showToast('\u5df2\u5bfc\u51fa\u5168\u91cf ' + selected.length + ' \u4e2a\u8282\u70b9\uff0c\u5176\u4e2d ' + checkedCount + ' \u4e2a\u52fe\u9009');
  } else {
    showToast('\u5df2\u5bfc\u51fa ' + selected.length + ' \u4e2a\u6587\u4ef6\u5939\uff08\u6700\u5c0f\u8868\u793a\uff09');
  }
  render();
}

function importJson(file) {
  const reader = new FileReader();
  reader.onload = (ev) => {
    try {
      const data = JSON.parse(ev.target.result);
      // 兼容两种格式：minimal（无 selected 字段，全算选中）和 full（有 selected 字段，只取 true）
      const items = (data.selected || [])
        .filter(item => item && typeof item.path === 'string' && item.selected !== false)
        .map(item => ({ path: item.path, priority: item.priority }));
      const result = applyPrecheck(items);
      render();
      showToast('\u5df2\u5bfc\u5165\uff1a\u5e94\u7528 ' + result.applied + ' \u4e2a\uff0c\u5ffd\u7565 ' + result.ignored + ' \u4e2a');
    } catch (err) {
      showToast('JSON \u89e3\u6790\u5931\u8d25: ' + err.message);
    }
  };
  reader.readAsText(file, 'utf-8');
}

function showToast(msg) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), 2200);
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}
function escapeAttr(s) { return escapeHtml(s); }

document.getElementById('search').addEventListener('input', () => render());

document.getElementById('tree').addEventListener('click', (e) => {
  const row = e.target.closest('.row');
  if (!row) return;
  if (e.target.dataset.action === 'toggle') {
    toggleExpand(row.dataset.path);
  }
});

document.getElementById('tree').addEventListener('change', (e) => {
  if (e.target.dataset.action === 'check') {
    const row = e.target.closest('.row');
    toggleCheck(row.dataset.path);
    render();
  }
});

document.getElementById('fileInput').addEventListener('change', (e) => {
  const file = e.target.files[0];
  if (file) importJson(file);
  e.target.value = '';
});

applyPrecheck((DATA.precheck || []).map(p => ({ path: p })));
render();
</script>
</body>
</html>
'''


def generate_html(tree_data, output_path):
    json_str = json.dumps(tree_data, ensure_ascii=False)
    # 防止 JSON 中出现 </script> 提前结束脚本
    json_str = json_str.replace('</', '<\\/')
    parent_name = Path(tree_data['parent_dir']).name or tree_data['parent_dir']
    html = HTML_TEMPLATE.replace('__DATA_JSON__', json_str)
    html = html.replace('__TITLE__', parent_name)
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)


def cmd_scan(args):
    parent = Path(args.parent).resolve()
    if not parent.is_dir():
        print('错误: ' + str(parent) + ' 不是有效目录', file=sys.stderr)
        sys.exit(1)

    print('扫描 ' + str(parent) + ' ...')
    dir_info = scan_folder(parent)
    print('共扫描到 ' + str(len(dir_info)) + ' 个文件夹')

    precheck_paths = set()
    ignored = 0
    if args.precheck:
        precheck_path = Path(args.precheck)
        if not precheck_path.is_file():
            print('错误: 预勾选文件不存在: ' + args.precheck, file=sys.stderr)
            sys.exit(1)
        try:
            with open(precheck_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            raw_paths = [item['path'] for item in data.get('selected', [])]
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            print('错误: 预勾选 JSON 格式无效: ' + str(e), file=sys.stderr)
            sys.exit(1)
        precheck_paths, ignored = normalize_precheck(raw_paths, dir_info)
        if ignored > 0:
            print('警告: ' + str(ignored) + ' 条预勾选路径不存在或冗余，已忽略')

    tree_data = build_tree_data(str(parent), dir_info, precheck_paths)

    output = args.output or 'picker_folder.html'
    generate_html(tree_data, output)
    print('已生成 ' + output)
    if precheck_paths:
        print('默认勾选 ' + str(len(precheck_paths)) + ' 个文件夹')
    print('双击 ' + output + ' 在浏览器中打开进行勾选')


def cmd_to_list(args):
    input_path = Path(args.input)
    if not input_path.is_file():
        print('错误: 输入文件不存在: ' + args.input, file=sys.stderr)
        sys.exit(1)

    try:
        with open(input_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        print('错误: JSON 解析失败: ' + str(e), file=sys.stderr)
        sys.exit(1)

    # 兼容两种导出格式：
    #   minimal: selected 数组只含勾选项，无 selected 字段（默认视为选中）
    #   full:    selected 数组含全部节点，每项有 selected 字段（true/false）
    paths = []
    for item in data.get('selected', []):
        if item.get('selected', True):
            paths.append(item['path'])

    seen = set()
    unique = []
    for p in paths:
        if p not in seen:
            seen.add(p)
            unique.append(p)
    unique.sort()

    output = args.output or 'list.txt'
    with open(output, 'w', encoding='utf-8') as f:
        for p in unique:
            f.write(p + '\n')
    print('已写入 ' + str(len(unique)) + ' 个路径到 ' + output)


def main():
    parser = argparse.ArgumentParser(
        description='文件夹勾选工具',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
示例:
  python picker_folder.py scan --parent E:\\Code\\loveMentor --precheck precheck.json -o picker_folder.html
  python picker_folder.py to-list selected.json -o list.txt
        '''
    )
    sub = parser.add_subparsers(dest='command', required=True)

    p_scan = sub.add_parser('scan', help='扫描父文件夹生成 HTML 勾选页面')
    p_scan.add_argument('--parent', required=True, help='父文件夹路径')
    p_scan.add_argument('--precheck', help='预勾选 JSON 文件路径（可选）')
    p_scan.add_argument('-o', '--output', help='输出 HTML 文件路径，默认 picker_folder.html')
    p_scan.set_defaults(func=cmd_scan)

    p_list = sub.add_parser('to-list', help='把 selected.json 转成 list.txt')
    p_list.add_argument('input', help='selected.json 路径')
    p_list.add_argument('-o', '--output', help='输出 list.txt 路径，默认 list.txt')
    p_list.set_defaults(func=cmd_to_list)

    args = parser.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
