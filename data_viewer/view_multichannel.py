"""Open the offline RX viewer, or embed recordings from a file/session/data folder.

Standard library only. Input CSVs are never changed; generated HTML goes to exports.
"""
import argparse
from datetime import datetime
import json
from pathlib import Path
import sys
import webbrowser

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = Path(__file__).with_name('multichannel_viewer.html')
PLACEHOLDER = '<script id="embedded-data" type="application/json">[]</script>'
MAX_EMBED_BYTES = 200 * 1024 * 1024


def project_path(value):
    p = Path(value).expanduser()
    return p.resolve() if p.is_absolute() else (ROOT / p).resolve()


def find_recordings(source):
    source = Path(source)
    if source.is_file():
        if source.suffix.lower() != '.csv':
            raise ValueError('请选择 CSV 文件或包含 grip_multichannel.csv 的文件夹。')
        return [source]
    if not source.is_dir():
        raise ValueError('数据路径不存在：'+str(source))
    direct = source/'grip_multichannel.csv'
    files = [direct] if direct.is_file() else sorted(source.rglob('grip_multichannel.csv'))
    if not files:
        raise ValueError('没有找到 grip_multichannel.csv；请确认实验已经结束并导出数据。')
    return files


def build_html(source):
    source = Path(source)
    files = find_recordings(source)
    if sum(f.stat().st_size for f in files) > MAX_EMBED_BYTES:
        raise ValueError('所选 CSV 合计超过 200 MB，请指定单次会话，或在查看器里选择文件夹后逐次读取。')
    entries = []
    for f in files:
        setup_file = f.parent/'experiment_setup.json'
        setup = {}
        if setup_file.is_file():
            try:
                full = json.loads(setup_file.read_text(encoding='utf-8-sig'))
                setup = dict(hand_assignment=full.get('hand_assignment', {}),
                             effective_config={'multichannel': full.get('effective_config', {}).get('multichannel', {})})
            except (ValueError, OSError):
                pass  # CSV remains viewable; UI uses explicitly labelled defaults.
        name = f.parent.name if len(files) == 1 else str(f.parent.relative_to(source))
        entries.append(dict(name=name or f.name, csv=f.read_text(encoding='utf-8-sig'), setup=setup))
    # Script-type JSON must still escape '<': a filename/CSV cell can contain </script>.
    payload = json.dumps(entries, ensure_ascii=False).replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')
    template = TEMPLATE.read_text(encoding='utf-8')
    if template.count(PLACEHOLDER) != 1:
        raise ValueError('查看器模板缺少唯一的数据占位符。')
    return template.replace(PLACEHOLDER, '<script id="embedded-data" type="application/json">'+payload+'</script>')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-root', help='CSV 文件、单次会话文件夹或包含多次会话的父文件夹')
    parser.add_argument('--output', help='导出的 HTML 文件，默认在 data_viewer/exports；不覆盖已有文件')
    parser.add_argument('--no-open', action='store_true', help='只生成文件，不自动打开浏览器')
    args = parser.parse_args(argv)
    if args.output and not args.data_root:
        parser.error('--output 需要配合 --data-root')
    try:
        if args.data_root:
            content = build_html(project_path(args.data_root))
            target = project_path(args.output) if args.output else ROOT/'data_viewer/exports'/f'multichannel_{datetime.now():%Y%m%d_%H%M%S_%f}.html'
            if target.suffix.lower() != '.html':
                raise ValueError('输出文件扩展名应为 .html')
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('x', encoding='utf-8') as f:
                f.write(content)
        else:
            target = TEMPLATE
        print('查看器：', target)
        if not args.no_open:
            webbrowser.open(target.as_uri(), new=1)
    except (OSError, ValueError) as exc:
        print('无法打开：'+str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
