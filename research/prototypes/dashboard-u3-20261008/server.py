"""仅在回环地址提供隔离原型与有界合成数据。"""
from http.server import ThreadingHTTPServer,SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlsplit,parse_qs
import json
ROOT=Path(__file__).resolve().parent
VUE=ROOT.parents[2]/'web/node_modules/vue/dist/vue.runtime.esm-browser.prod.js'
DATA={
 'alpha':{'name':'采购协同','amount':348000,'change':8.2,'missing':0,'rows':[['07',286000],['08',321000],['09',348000]],'as_of':'2026-09-30 23:59 +08:00','fetched_at':'2026-10-08 10:30 +08:00','unit':'元 · 含税','status':'stale','source':'合成采购月表 A'},
 'beta':{'name':'展陈筹备','amount':186000,'change':None,'missing':1,'rows':[['07',None],['08',142000],['09',186000]],'as_of':'2026-09-30 23:59 +08:00','fetched_at':'2026-10-08 10:30 +08:00','unit':'元 · 含税','status':'missing','source':'合成采购月表 B'}}
OBJECTS={'alpha':{'work':{'t1','t2','t3'},'result':{'r2','r3','r4'}},'beta':{'work':{'b1'},'result':{'b-r1'}}}
class Handler(SimpleHTTPRequestHandler):
 def __init__(self,*args,**kw):super().__init__(*args,directory=str(ROOT),**kw)
 def log_message(self,*args):pass
 def json(self,status,data):
  raw=json.dumps(data,ensure_ascii=False,allow_nan=False).encode();self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(raw)
 def do_GET(self):
  """校验有限绑定与对象归属，所有响应均为合成演示。"""
  u=urlsplit(self.path);q=parse_qs(u.query)
  if u.path=='/spatial-scene':
   if set(q)-{'project','state'} or any(len(v)!=1 for v in q.values()):return self.json(422,{'error':'unsupported_input'})
   if q.get('project',[''])[0]!='alpha':return self.json(404,{'error':'demo_project_not_visible'})
   state=q.get('state',['normal'])[0]
   if state not in {'normal','empty','error','malformed'}:return self.json(422,{'error':'unsupported_state'})
   if state=='error':return self.json(503,{'error':'synthetic_scene_timeout'})
   scene=json.loads((ROOT/'spatial/scene.json').read_text())
   if state=='empty':scene.update(zones=[],route=[])
   if state=='malformed':scene['zones'][0]['rect'][0]=99
   return self.json(200,scene)
  if u.path=='/r2-bundle':
   if set(q)-{'variant'} or any(len(v)!=1 for v in q.values()):return self.json(422,{'error':'unsupported_input'})
   variant=q.get('variant',['normal'])[0]
   if variant not in {'normal','crash','probe','missing','bad-digest'}:return self.json(422,{'error':'unsupported_variant'})
   file=ROOT/'.build'/('r2-'+('normal' if variant=='bad-digest' else variant)+'.json')
   if not file.is_file():return self.json(503,{'error':'synthetic_bundle_missing'})
   data=json.loads(file.read_text())
   if variant=='bad-digest':data['sha256']='0'*64
   return self.json(200,data)
  if u.path=='/runtime/vue.js':
   if not VUE.is_file():return self.json(503,{'error':'local_vue_runtime_missing'})
   self.send_response(200);self.send_header('Content-Type','text/javascript');self.end_headers();self.wfile.write(VUE.read_bytes());return
  if u.path in {'/sample-data','/resolve-navigation'}:
   allowed={'project','binding','state'} if u.path=='/sample-data' else {'project','kind','id','work'}
   if set(q)-allowed or any(len(v)!=1 for v in q.values()):return self.json(422,{'error':'unsupported_input'})
   p=q.get('project',[''])[0]
   if p not in DATA:return self.json(404,{'error':'demo_project_not_visible'})
   if u.path=='/sample-data':
    binding=q.get('binding',[''])[0];state=q.get('state',['normal'])[0]
    if binding not in {'monthly-'+p,'spatial-'+p}:return self.json(404,{'error':'binding_not_in_current_project'})
    if state not in {'normal','error','empty'}:return self.json(422,{'error':'unsupported_state'})
    if state=='error':return self.json(503,{'error':'synthetic_source_timeout','retryable':True})
    d=DATA[p].copy()
    if binding.startswith('spatial-'):
     d.update(source='合成展陈区域表 '+p.upper(),as_of='2026-10-08 09:00 +08:00',status='normal',amount=None,change=None,rows=[],zones=[['A区入口',0,0,'开放'],['B区展台',2,1,'布置中'],['C区仓储',1,2,'物料阻挡'],['D区出口',3,2,'开放']] if p=='alpha' else [['B项目入口',0,1,'开放'],['B项目展台',1,2,'布置中'],['B项目出口',2,3,'开放']])
    d.update(project=p,binding=binding,synthetic=True)
    if state=='empty':d.update(amount=None,change=None,rows=[],zones=[],status='empty')
    return self.json(200,d)
   kind=q.get('kind',[''])[0];oid=q.get('id',[''])[0];work=q.get('work',[''])[0]
   if kind not in {'work','result'}:return self.json(422,{'error':'unsupported_navigation_kind'})
   if oid not in OBJECTS[p][kind]:return self.json(404,{'error':'object_not_in_current_project'})
   expected={'r2':'t1','r3':'t1','r4':'t2','b-r1':'b1'}
   if kind=='result' and work!=expected[oid]:return self.json(404,{'error':'result_work_mismatch'})
   return self.json(200,{'project':p,'kind':kind,'id':oid,'work':work or oid,'target':f'../index.html#a/{p}/detail/{work or oid}/{oid if kind=="result" else ""}','synthetic':True})
  # 无文件写入；目录列举不作为原型入口。
  return super().do_GET()
 def list_directory(self,path):return self.json(404,{'error':'directory_listing_disabled'})
if __name__=='__main__':
 print('U3 prototype: http://127.0.0.1:8767',flush=True)
 ThreadingHTTPServer(('127.0.0.1',8767),Handler).serve_forever()
