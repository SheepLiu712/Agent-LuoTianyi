"""Isolated dynamics fixture, no requests to the public server."""
import argparse,json,os,subprocess,threading,time
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.parse import urlparse,parse_qs
from pathlib import Path
PROJECT=Path(__file__).resolve().parents[1]
def run(godot,script,gpu=False):
    errors=[]; reads={}; writes=[]; unread_calls={}; comment_calls={}
    def post(i):
        return dict(id=f'd{i}',author_type='agent',author_name='洛天依',content='合成动态\n第二行\n第三行\n第四行\n第五行\n第六行\n第七行',created_at='2026-09-19 10:00:00',allow_comment=i!=1,comment_count=22,visibility='private')
    def comment(i):
        return dict(id=f'c{i}',dynamic_id='d0',author_type='user',author_name='测试用户',content='合成评论',created_at=f'2026-09-19 10:{i:02}:00',parent_comment_id='c0' if i else None)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args): pass
        def reply(self,status,data):
            body=json.dumps(data).encode(); self.send_response(status); self.send_header('Content-Type','application/json'); self.send_header('Content-Length',str(len(body))); self.end_headers()
            try: self.wfile.write(body)
            except (OSError,ConnectionError): pass
        def do_GET(self):
            path=urlparse(self.path); query=parse_qs(path.query); user=query.get('username',[''])[0]
            if path.path=='/stats': self.reply(200,{'writes':writes}); return
            if self.headers.get('Authorization')!='Bearer fixture-token': errors.append('invalid bearer')
            if user=='slow': time.sleep(.5)
            if path.path=='/dynamics/unread':
                unread_calls[user]=unread_calls.get(user,0)+1
                if user=='fail-unread' and unread_calls[user]>1: self.reply(503,{}); return
                self.reply(200,{'unread_count':0 if user in reads else 123,'has_unread':user not in reads}); return
            cursor=query.get('cursor',[''])[0]
            if path.path=='/dynamics':
                if query.get('limit')!=['10']: errors.append('post page limit')
                if cursor and cursor!='older | page': errors.append('cursor not preserved')
                items=[post(i) for i in (range(10) if not cursor else range(9,12))]
                if user in ('private-a','private-b'):
                    for item in items: item.update(visibility='public',comment_count=2 if user=='private-a' else 1)
                self.reply(200,{'items':items,'has_more':not cursor,'next_cursor':'older | page' if not cursor else None}); return
            if path.path=='/dynamics/d0/comments':
                if query.get('limit')!=['20']: errors.append('comment page limit')
                comment_calls[user]=comment_calls.get(user,0)+1
                if user=='fail-refresh' and cursor: self.reply(503,{}); return
                if user=='slow-comments': time.sleep(.3)
                if user in ('private-a','private-b'):
                    self.reply(200,{'items':[{**comment(i),'content':user+' private content','owner_user_id':user} for i in range(2 if user=='private-a' else 1)],'has_more':False,'next_cursor':None}); return
                self.reply(200,{'items':[comment(i) for i in (range(20) if not cursor else range(19,22))],'has_more':not cursor,'next_cursor':'next | comments' if not cursor else None}); return
            if path.path.startswith('/dynamics/') and path.path.endswith('/comments'):
                self.reply(200,{'items':[],'has_more':False,'next_cursor':None}); return
            self.reply(404,{})
        def do_POST(self):
            data=json.loads(self.rfile.read(int(self.headers['Content-Length']))); user=data.get('username')
            if data.get('token')!='fixture-token': errors.append('invalid write token')
            writes.append({'path':self.path,**data})
            if user=='fail-write': self.reply(503,{}); return
            if user=='uncertain-write': self.connection.shutdown(2); self.connection.close(); return
            if self.path=='/dynamics/read': reads[user]=True; self.reply(200,{'ok':True}); return
            if self.path=='/dynamics': self.reply(200,{'item':{**post(99),'content':data['content']}}); return
            if self.path=='/dynamics/d0/comments': self.reply(200,{'item':{**comment(99),'content':data['content'],'parent_comment_id':data.get('parent_comment_id')}}); return
            self.reply(400,{})
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler); thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
    try:
        import sys
        result=subprocess.run([godot,*([] if gpu else ['--headless']),'--path',str(PROJECT),'--script',script],env={**os.environ,'GODOT_TEST_SERVER':f'http://127.0.0.1:{server.server_port}','GODOT_TEST_PYTHON':sys.executable},capture_output=True,text=True,encoding='utf8',errors='replace',timeout=60)
        print(result.stdout); print(result.stderr)
        if result.returncode or 'ERROR:' in result.stdout+result.stderr or 'FAIL:' in result.stdout or ': PASS' not in result.stdout or errors: raise RuntimeError(errors or 'dynamics test failed')
    finally: server.shutdown(); server.server_close(); thread.join(2)
    print('Offline dynamics API: PASS')
if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--godot',required=True); parser.add_argument('--script',default='res://tests/test_dynamics.gd'); parser.add_argument('--gpu',action='store_true'); args=parser.parse_args(); run(args.godot,args.script,args.gpu)
