"""Local JSON-lines transport for the native SwiftUI workbench. No web server."""
import base64
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import traceback
from html.parser import HTMLParser

ROOT = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(ROOT))
DATA_ROOT = Path(os.environ.get('NM_DATA_ROOT', ROOT))
os.environ.setdefault('NEGATIVEMASTER_ARCHIVE_DIR', str(DATA_ROOT / 'archive_data'))
with contextlib.redirect_stdout(sys.stderr):
    import gui
    import decast
    import numpy as np

gui.SETTINGS_DIR = str(DATA_ROOT / 'settings')
decast.PRESET_DIR = str(DATA_ROOT / 'presets')
_decode_params = {}
_shared_load = gui.load_full

def native_load(path, raw_denoise=False, decode_params=None):
    # Share cache invalidation and decode semantics with the web workbench.
    return _shared_load(path, raw_denoise,
                        _decode_params if decode_params is None else decode_params)

gui.load_full = native_load
client = gui.app.test_client()

class Controls(HTMLParser):
    """Keep native controls aligned with the shipped sheet editor's options."""
    def __init__(self):
        super().__init__()
        self.pane = ""
        self.label = None
        self.control = None
        self.option = None
        self.fields = []
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "section" and a.get("id", "").startswith("pane-"):
            self.pane = a["id"][5:]
        if tag == "label":
            self.label = []
            self.control = None
        if tag in ("input", "select", "textarea") and a.get("data-config"):
            self.control = dict(key=a["data-config"], pane=self.pane,
                kind="color" if "data-color" in a else ("select" if tag == "select" else a.get("type", "text")),
                min=float(a.get("min", 0)), max=float(a.get("max", 100)), step=float(a.get("step", 1)),
                options=[], boolean=a.get("data-kind") == "boolean")
        if tag == "option" and self.control is not None:
            self.option = dict(value=a.get("value", ""), label="")
    def handle_data(self, data):
        if self.option is not None:
            self.option["label"] += data
        elif self.label is not None:
            self.label.append(data)
    def handle_endtag(self, tag):
        if tag == "option" and self.option is not None:
            self.control["options"].append(self.option)
            self.option = None
        if tag == "label":
            if self.control is not None:
                self.control["title"] = " ".join("".join(self.label or []).split()).replace("自定义", "").strip()
                self.fields.append(self.control)
            self.label = None
            self.control = None

# Cache controls once; no HTML is shown by the native app.
parser = Controls()
parser.feed(client.get('/sheet').get_data(as_text=True))
for f in parser.fields:
    if f['kind'] == 'color':
        f['title'] = {'strip.edgeColor':'边字颜色','strip.color':'片条颜色','background.color':'背景颜色',
                      'background.color2':'第二种颜色','header.color':'横幅底色','header.textColor':'文字颜色'}.get(f['key'],f['key'])


def response_data(response, output=None):
    try:
        if response.is_json:
            data = response.get_json()
            if response.status_code >= 400 or data.get('ok') is False:
                raise ValueError(data.get('error') or data.get('err') or str(data))
            return data
        if response.status_code >= 400:
            raise ValueError('处理失败：' + str(response.status_code))
        if output:
            with open(output, 'wb') as handle:
                for chunk in response.response:
                    handle.write(chunk)
            return {'ok':True,'out':output}
        return {'ok':True,'bytes':base64.b64encode(response.get_data()).decode(),
                'width':response.headers.get('X-Sheet-Width',''),
                'height':response.headers.get('X-Sheet-Height','')}
    finally:
        response.close()


def request(path, body=None, method='POST'):
    return response_data(client.open(path, method=method, json=body))


def adjustments(path):
    for file, xml in ((gui.sidecar_path(path),True),(gui.settings_file(path),False)):
        if os.path.isfile(file):
            text = Path(file).read_text()
            data = gui._xml_to_data(text) if xml else json.loads(text)
            p = dict(gui.DEFAULTS)
            p.update(data.get('P',{}))
            if data.get('cropN'):
                p['crop_rect'] = [data['cropN'][k] for k in ('x0','y0','x1','y1')]
            return dict(params=p, data=data)
    return dict(params=dict(gui.DEFAULTS), data={})


def save_adjustments(path, p, sidecar=False):
    cr = p.get('crop_rect')
    data = dict(P=p, cropN=dict(zip(('x0','y0','x1','y1'),cr)) if cr else {},curFmt='free',orient='land')
    target = Path(gui.settings_file(path))
    target.parent.mkdir(parents=True,exist_ok=True)
    tmp = target.with_suffix('.tmp')
    tmp.write_text(json.dumps(data,ensure_ascii=False))
    tmp.replace(target)
    if sidecar:
        target = Path(gui.sidecar_path(path))
        tmp = target.with_suffix('.tmp')
        tmp.write_text(gui._data_to_xml(data,path))
        tmp.replace(target)
    return dict(ok=True)


def restore_reference(params):
    path = params.get('reference_path')
    if params.get('use_match') and path and gui.REF['path'] != path:
        request('/api/loadref',dict(path=path))
    if params.get('use_match') and gui.REF['cdfs'] is None:
        raise ValueError('此照片启用了参照匹配，请先选择原来的参照成片。')


def handle(message):
    global _decode_params
    action = message.get('action','api')
    body = message.get('body',{})
    if action == 'bootstrap':
        return dict(ok=True, defaults=gui.DEFAULTS, fields=parser.fields,
                    sheetDefaults=json.loads((Path(__file__).parent/'sheet-defaults.json').read_text()),
                    presets=decast.list_presets(), stocks=request('/api/sheet/catalog',method='GET')['stocks'])
    if action == 'adjustments':
        return adjustments(body['path'])
    if action == 'save':
        return save_adjustments(body['path'],body['params'],body.get('sidecar',False))
    if action == 'render':
        p = body['params']
        _decode_params = p
        restore_reference(p)
        gui.load_full(body['path'],p.get('raw_denoise',False))
        result = request('/api/render',p)
        result['histogram'] = request('/api/hist',method='GET')
        result['fullWidth'] = int(gui.CACHE['full'].shape[1])
        result['fullHeight'] = int(gui.CACHE['full'].shape[0])
        if body.get('include_negative', True):
            result['negative'] = request('/api/render',dict(p,negative_preview=True))['bytes']
        return result
    if action == 'negative':
        p = body['params']
        _decode_params = p
        gui.load_full(body['path'], p.get('raw_denoise', False))
        return request('/api/render', dict(p, negative_preview=True))
    if action == 'thumbnail':
        from PIL import Image
        with client.get('/api/sheet/thumb/'+body['job']+'/'+str(body['id'])) as response:
            if response.status_code != 200:
                raise ValueError('排版缩略图已失效，请重新载入项目。')
            with Image.open(io.BytesIO(response.get_data())) as image:
                image.thumbnail((160,160),Image.Resampling.LANCZOS)
                buf=io.BytesIO();image.convert('RGB').save(buf,'JPEG',quality=85)
        return dict(bytes=base64.b64encode(buf.getvalue()).decode())
    if action == 'autocrop':
        _decode_params = body
        gui.load_full(body['path'],body.get('raw_denoise',False))
        return request('/api/autocrop',body)
    if action == 'wbtemp':
        _decode_params = body
        gui.load_full(body['path'],body.get('raw_denoise',False))
        return request('/api/wbtemp',body)
    if action == 'frame':
        from PIL import Image
        from contact_sheet import _cover
        image = Image.open(io.BytesIO(client.get('/api/sheet/thumb/'+body['job']+'/'+str(body['id'])).get_data()))
        ratio = {'3:2':1.5,'4:3':4/3,'1:1':1,'original':1.5}.get(body.get('ratio'),1.5)
        result = _cover(image,(1200,round(1200/ratio)),body.get('override'),body.get('fit','contain'))
        buf=io.BytesIO();result.save(buf,'PNG')
        return dict(ok=True,bytes=base64.b64encode(buf.getvalue()).decode())
    if action == 'export':
        p = body['params']
        restore_reference(p)
        out = Path(body['out'])
        if out.resolve() == Path(body['path']).resolve():
            raise ValueError('导出位置不能覆盖原始照片。')
        opts = gui.make_opts(p)
        image,_ = decast.load_image(body['path'],opts)
        opts.stats_rect = None
        result = decast.convert_negative(image,opts)
        decast.save_image(result,str(out),int(body.get('bits',16)),quality=int(body.get('quality',92)),resize=int(body.get('resize',0)))
        if out.suffix.lower() in ('.jpg','.jpeg'):
            decast.copy_exif_best_effort(body['path'],str(out))
        return dict(ok=True,out=str(out))
    if action == 'api':
        path = message['path']
        if not path.startswith('/api/'):
            raise ValueError('不支持的处理操作')
        with contextlib.ExitStack() as stack:
            headers = {'X-NegativeMaster-Archive':'1'} if path.startswith('/api/archive/') else {}
            files = message.get('files')
            if files:
                data = dict(body)
                for key,path_on_disk in files.items():
                    data[key] = (stack.enter_context(open(path_on_disk,'rb')),Path(path_on_disk).name)
                response = client.open(path,method=message.get('method','POST'),data=data,headers=headers)
            else:
                response = client.open(path,method=message.get('method','POST'),json=body if message.get('method','POST')!='GET' else None,headers=headers)
            result = response_data(response,message.get('output'))
            if path.startswith('/api/sheet/job/'):
                job = gui.app.blueprints['sheet'].sheet_jobs.get(path.rsplit('/',1)[-1],{})
                result['backgroundFile'] = job.get('background') or ''
            return result
    raise ValueError('未知操作：'+action)

if __name__ == '__main__':
    for line in sys.stdin:
        try:
            with contextlib.redirect_stdout(sys.stderr):
                result = handle(json.loads(line))
            reply = dict(ok=True,result=result)
        except Exception as exc:
            traceback.print_exc(file=sys.stderr)
            reply = dict(ok=False,error=str(exc))
        try:
            sys.stdout.write(json.dumps(reply,ensure_ascii=False,allow_nan=False)+'\n')
            sys.stdout.flush()
        except BrokenPipeError:
            # The native window closed while a preview was finishing.
            sys.stdout = open(os.devnull, 'w')
            break
