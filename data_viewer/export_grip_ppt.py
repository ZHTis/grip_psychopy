"""Export one full-session raw grip/event plot per PowerPoint slide.

Usage: python data_viewer/export_grip_ppt.py --data-root data --output report.pptx
Input and output paths are relative to the project root, or may be absolute.
The PPTX contains full-slide PNGs; edit the source plot and rerun to change a chart.
Only the existing viewer dependencies and Python's standard library are required.
"""
import argparse
from datetime import datetime
import json
from pathlib import Path
import tempfile
from xml.etree import ElementTree as ET
from zipfile import ZipFile, ZIP_DEFLATED

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from view_data import data_path, load_session, plot_session

P = 'http://schemas.openxmlformats.org/presentationml/2006/main'
A = 'http://schemas.openxmlformats.org/drawingml/2006/main'
R = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
PKG = 'http://schemas.openxmlformats.org/package/2006/relationships'
CT = 'http://schemas.openxmlformats.org/package/2006/content-types'
WIDTH, HEIGHT = 12192000, 6858000  # 13 1/3 x 7 1/2 inches, 16:9
for prefix, uri in [('p', P), ('a', A), ('r', R)]:
    ET.register_namespace(prefix, uri)
ET.register_namespace('', CT)


def element(parent, namespace, tag, **attributes):
    return ET.SubElement(parent, f'{{{namespace}}}{tag}',
                         {key: str(value) for key, value in attributes.items()})


def xml_bytes(root):
    return ET.tostring(root, encoding='utf-8', xml_declaration=True)


def relationships(items):
    root = ET.Element(f'{{{PKG}}}Relationships')
    for rid, kind, target in items:
        element(root, PKG, 'Relationship', Id=rid, Type=f'{R}/{kind}', Target=target)
    return xml_bytes(root)


def shape_tree(parent):
    tree = element(parent, P, 'spTree')
    nv = element(tree, P, 'nvGrpSpPr')
    element(nv, P, 'cNvPr', id=1, name='')
    element(nv, P, 'cNvGrpSpPr')
    element(nv, P, 'nvPr')
    xfrm = element(element(tree, P, 'grpSpPr'), A, 'xfrm')
    for tag, values in [('off', {'x': 0, 'y': 0}), ('ext', {'cx': 0, 'cy': 0}),
                        ('chOff', {'x': 0, 'y': 0}), ('chExt', {'cx': 0, 'cy': 0})]:
        element(xfrm, A, tag, **values)
    return tree


def theme_xml():
    theme = ET.Element(f'{{{A}}}theme', name='Grip report')
    base = element(theme, A, 'themeElements')
    colors = element(base, A, 'clrScheme', name='Grip report')
    for name, value in [('dk1','000000'), ('lt1','FFFFFF'), ('dk2','333333'),
                        ('lt2','EEEEEE'), ('accent1','27649B'), ('accent2','C17525'),
                        ('accent3','777777'), ('accent4','447744'), ('accent5','775577'),
                        ('accent6','337777'), ('hlink','0563C1'), ('folHlink','954F72')]:
        element(element(colors, A, name), A, 'srgbClr', val=value)
    fonts = element(base, A, 'fontScheme', name='Arial')
    for kind in ('majorFont', 'minorFont'):
        font = element(fonts, A, kind)
        for tag, face in [('latin','Arial'), ('ea',''), ('cs','')]:
            element(font, A, tag, typeface=face)
    styles = element(base, A, 'fmtScheme', name='Standard')
    for tag in ('fillStyleLst', 'lnStyleLst', 'effectStyleLst', 'bgFillStyleLst'):
        group = element(styles, A, tag)
        for i in range(3):
            if tag == 'effectStyleLst':
                element(element(group, A, 'effectStyle'), A, 'effectLst')
            else:
                target = element(group, A, 'ln', w=9525*(i+1)) if tag == 'lnStyleLst' else group
                element(element(target, A, 'solidFill'), A, 'schemeClr', val='phClr')
    return xml_bytes(theme)


def write_pptx(images, output):
    """Write a self-contained OOXML image deck, without office automation."""
    if not images:
        raise ValueError('Cannot create an empty presentation')
    presentation = ET.Element(f'{{{P}}}presentation')
    masters = element(presentation, P, 'sldMasterIdLst')
    master_id = element(masters, P, 'sldMasterId', id=2147483648)
    master_id.set(f'{{{R}}}id', 'rId1')
    slides = element(presentation, P, 'sldIdLst')
    for i in range(len(images)):
        node = element(slides, P, 'sldId', id=256+i)
        node.set(f'{{{R}}}id', f'rId{i+2}')
    element(presentation, P, 'sldSz', cx=WIDTH, cy=HEIGHT, type='screen16x9')
    element(presentation, P, 'notesSz', cx=6858000, cy=9144000)

    master = ET.Element(f'{{{P}}}sldMaster')
    shape_tree(element(master, P, 'cSld'))
    element(master, P, 'clrMap', bg1='lt1', tx1='dk1', bg2='lt2', tx2='dk2',
            **{f'accent{i}': f'accent{i}' for i in range(1,7)}, hlink='hlink', folHlink='folHlink')
    layout_id = element(element(master, P, 'sldLayoutIdLst'), P, 'sldLayoutId', id=2147483649)
    layout_id.set(f'{{{R}}}id', 'rId1')
    layout = ET.Element(f'{{{P}}}sldLayout', type='blank', preserve='1')
    shape_tree(element(layout, P, 'cSld', name='Blank'))
    element(element(layout, P, 'clrMapOvr'), A, 'masterClrMapping')

    types = ET.Element(f'{{{CT}}}Types')
    for ext, mime in [('rels','application/vnd.openxmlformats-package.relationships+xml'),
                      ('xml','application/xml'), ('png','image/png')]:
        element(types, CT, 'Default', Extension=ext, ContentType=mime)
    parts = [('presentation.xml','presentation'), ('slideMasters/slideMaster1.xml','slideMaster'),
             ('slideLayouts/slideLayout1.xml','slideLayout')]
    parts += [(f'slides/slide{i+1}.xml','slide') for i in range(len(images))]
    for filename, kind in parts:
        element(types, CT, 'Override', PartName=f'/ppt/{filename}',
                ContentType=f'application/vnd.openxmlformats-officedocument.presentationml.{kind}+xml')
    element(types, CT, 'Override', PartName='/ppt/theme/theme1.xml',
            ContentType='application/vnd.openxmlformats-officedocument.theme+xml')
    with ZipFile(output, 'w', ZIP_DEFLATED) as archive:
        archive.writestr('[Content_Types].xml', xml_bytes(types))
        archive.writestr('_rels/.rels', relationships([('rId1','officeDocument','ppt/presentation.xml')]))
        archive.writestr('ppt/presentation.xml', xml_bytes(presentation))
        archive.writestr('ppt/_rels/presentation.xml.rels', relationships(
            [('rId1','slideMaster','slideMasters/slideMaster1.xml')] +
            [(f'rId{i+2}','slide',f'slides/slide{i+1}.xml') for i in range(len(images))]))
        archive.writestr('ppt/slideMasters/slideMaster1.xml', xml_bytes(master))
        archive.writestr('ppt/slideMasters/_rels/slideMaster1.xml.rels', relationships([
            ('rId1','slideLayout','../slideLayouts/slideLayout1.xml'),
            ('rId2','theme','../theme/theme1.xml')]))
        archive.writestr('ppt/slideLayouts/slideLayout1.xml', xml_bytes(layout))
        archive.writestr('ppt/slideLayouts/_rels/slideLayout1.xml.rels', relationships([
            ('rId1','slideMaster','../slideMasters/slideMaster1.xml')]))
        archive.writestr('ppt/theme/theme1.xml', theme_xml())
        for i, image in enumerate(images, 1):
            slide = ET.Element(f'{{{P}}}sld')
            tree = shape_tree(element(slide, P, 'cSld', name=image.stem))
            picture = element(tree, P, 'pic')
            nv = element(picture, P, 'nvPicPr')
            element(nv, P, 'cNvPr', id=2, name=image.name, descr='Full-session raw voltage and event request markers')
            element(element(nv, P, 'cNvPicPr'), A, 'picLocks', noChangeAspect=1)
            element(nv, P, 'nvPr')
            fill = element(picture, P, 'blipFill')
            element(fill, A, 'blip').set(f'{{{R}}}embed', 'rId2')
            element(element(fill, A, 'stretch'), A, 'fillRect')
            geometry = element(picture, P, 'spPr')
            transform = element(geometry, A, 'xfrm')
            element(transform, A, 'off', x=0, y=0)
            element(transform, A, 'ext', cx=WIDTH, cy=HEIGHT)
            element(element(geometry, A, 'prstGeom', prst='rect'), A, 'avLst')
            element(element(slide, P, 'clrMapOvr'), A, 'masterClrMapping')
            archive.writestr(f'ppt/slides/slide{i}.xml', xml_bytes(slide))
            archive.writestr(f'ppt/slides/_rels/slide{i}.xml.rels', relationships([
                ('rId1','slideLayout','../slideLayouts/slideLayout1.xml'),
                ('rId2','image',f'../media/image{i}.png')]))
            archive.write(image, f'ppt/media/image{i}.png')


def export_folder(data_root, output, dpi=180):
    root, output = data_path(data_root), data_path(output)
    if not root.is_dir():
        raise FileNotFoundError(f'Data folder not found: {root}')
    if output.suffix.lower() != '.pptx':
        raise ValueError('Output filename must end in .pptx')
    image_dir = output.with_name(output.stem + '_plots')
    manifest_path = output.with_suffix('.json')
    for target in (output, image_dir, manifest_path):
        if target.exists():
            raise FileExistsError(f'Output already exists; choose a new filename: {target}')
    sources = sorted(root.rglob('metadata.json'), key=lambda p: (p.parent.name, str(p)))
    if not sources:
        raise FileNotFoundError(f'No session metadata.json found in {root}')
    # Validate all input before creating the presentation. Invalid CSV aborts the export.
    included, skipped = [], []
    for source in sources:
        metadata = json.loads(source.read_text(encoding='utf-8-sig'))
        missing = [name for name in ('grip.csv', 'events.csv') if not (source.parent/name).is_file()]
        reason = 'session still recording' if metadata.get('status') == 'recording' else (
            'missing ' + ', '.join(missing) if missing else None)
        if reason:
            skipped.append({'source': str(source.parent), 'reason': reason})
            print(f'SKIP {source.parent}: {reason}')
        else:
            included.append(source.parent)
    if not included:
        raise ValueError('No exported sessions with both grip.csv and events.csv')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.grip-ppt-', dir=output.parent) as temp:
        staging = Path(temp)
        plots = staging/'plots'
        plots.mkdir()
        images, records = [], []
        for i, folder in enumerate(included, 1):
            print(f'PLOT {i}/{len(included)} {folder.name}', flush=True)
            session = load_session(folder.parent, folder.name)
            fig = plot_session(session, start=0, raw_only=True)
            try:
                image = plots/f'{i:03d}_{folder.name}.png'
                fig.savefig(image, dpi=dpi, facecolor='white')
            finally:
                plt.close(fig)
            images.append(image)
            records.append({'slide': i, 'source': str(folder), 'image': image.name,
                            'status': session['metadata'].get('status'),
                            'simulated': session['metadata'].get('parameters', {}).get('runtime', {}).get('simulate', False)})
        draft = staging/'report.pptx'
        write_pptx(images, draft)
        manifest = {'data_root': str(root), 'slides': records, 'skipped': skipped,
                    'plot': 'raw voltage (V); bars are host marker request times, not EEG or TTL onset',
                    'generated_at': datetime.now().astimezone().isoformat()}
        (staging/'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
        plots.rename(image_dir)
        (staging/'manifest.json').rename(manifest_path)
        draft.rename(output)
    print(f'Saved {len(records)} slides: {output}\nPlots: {image_dir}\nManifest: {manifest_path}')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-root', default='data', help='Session folder or parent folder; scans recursively')
    parser.add_argument('--output', default=None, help='New .pptx path relative to project root, or absolute')
    parser.add_argument('--dpi', type=int, default=180, help='Plot resolution; default 180')
    args = parser.parse_args()
    if not 72 <= args.dpi <= 600:
        parser.error('--dpi must be between 72 and 600')
    output = args.output or f'data_viewer/exports/grip_events_{datetime.now():%Y%m%d_%H%M%S_%f}.pptx'
    try:
        export_folder(args.data_root, output, args.dpi)
    except (OSError, ValueError) as exc:
        parser.exit(1, f'Export failed: {exc}\n')


if __name__ == '__main__':
    main()
