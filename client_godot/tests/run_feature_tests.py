"""Offline authenticated settings API fixture; never contacts public/paid services."""
import argparse, json, os, subprocess, threading, base64, hashlib, struct, time, sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
PROJECT=Path(__file__).resolve().parents[1]
def run(godot,script,gpu=False):
    reads, writes, errors = {}, {}, []
    provider_calls=[]
    delegated=[]
    from support.interop_crypto import server_crypto
    crypto=server_crypto(); crypto.generate_keys()
    class Handler(BaseHTTPRequestHandler):
        protocol_version='HTTP/1.1'
        def log_message(self,*args): pass
        def reply(self,status,data):
            self.close_connection=True
            body=json.dumps(data).encode(); self.send_response(status); self.send_header('Content-Type','application/json'); self.send_header('Content-Length',str(len(body))); self.end_headers()
            try: self.wfile.write(body)
            except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError): pass
        def do_GET(self):
            if self.path == '/slow/auth/public_key':
                time.sleep(.5)
                self.reply(200,{'public_key':crypto.get_public_key_pem()}); return
            if self.path.startswith('/dynamics/unread?'): self.reply(200,{'unread_count':123}); return
            if self.path.startswith('/dynamics?'):
                self.reply(200,{'items':[{'id':'visual-post','author_type':'agent','author_name':'洛天依','content':'今天也一起慢慢来吧。\n忙完以后，记得留一点时间给自己。','created_at':'2026-09-19 18:30:00','allow_comment':True,'comment_count':1,'visibility':'private'}],'has_more':False,'next_cursor':None}); return
            if self.path.startswith('/dynamics/visual-post/comments?'):
                self.reply(200,{'items':[{'id':'visual-comment','dynamic_id':'visual-post','author_type':'user','author_name':'测试用户','content':'好呀，晚点一起聊聊。','parent_comment_id':None,'created_at':'2026-09-19 18:31:00'}],'has_more':False,'next_cursor':None}); return
            if self.path=='/provider-stats': self.reply(200,{'calls':provider_calls,'delegated':delegated}); return
            if self.path=='/llm/client-model-types':
                self.reply(200,{'types':[{'id':'text-purpose','name':'文本用途','description':'local fixture','model_kind':'llm','requires_json':True,'requires_thinking':False},{'id':'vision-purpose','name':'图像用途','description':'local fixture','model_kind':'vlm','requires_json':False,'requires_thinking':False}]}); return
            if self.path=='/chat_ws':
                self.send_response(101); self.send_header('Upgrade','websocket'); self.send_header('Connection','Upgrade')
                self.send_header('Sec-WebSocket-Accept',base64.b64encode(hashlib.sha1((self.headers['Sec-WebSocket-Key']+'258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode()).digest()).decode()); self.end_headers()
                self.connection.settimeout(3)
                username = None
                try:
                    while True:
                        head=self.rfile.read(2)
                        if len(head)<2 or head[0]&15==8: break
                        size=head[1]&127
                        if size==126: size=struct.unpack('!H',self.rfile.read(2))[0]
                        if size==127: size=struct.unpack('!Q',self.rfile.read(8))[0]
                        assert size<65536
                        mask=self.rfile.read(4); body=self.rfile.read(size)
                        packet=json.loads(bytes(value^mask[i%4] for i,value in enumerate(body)))
                        if packet['type']=='user_auth': username=packet['payload']['username']
                        if packet['type']=='llm_response': delegated.append(packet['payload']); continue
                        if packet['type']=='user_text':
                            if username=='visual':
                                from support.wave_samples import tone
                                messages=[{'type':'server_ack','payload':{'ok':True},'reply_to':packet['client_msg_id']},
                                          {'type':'agent_message','payload':{'uuid':'redesign-voice','text':'辛苦啦，先让自己休息一下吧。\n我在这里陪着你，想说什么都可以。','audio':base64.b64encode(tone(2.4)).decode(),'is_final_package':True,'expression':'微笑脸'}}]
                                for response in messages:
                                    encoded=json.dumps(response).encode()
                                    header=bytes([129,len(encoded)]) if len(encoded)<126 else (bytes([129,126])+struct.pack('!H',len(encoded)) if len(encoded)<65536 else bytes([129,127])+struct.pack('!Q',len(encoded)))
                                    self.wfile.write(header+encoded);self.wfile.flush()
                                continue
                            if 'text-purpose' not in packet['payload'].get('llm_mode',{}).get('types',[]): errors.append('missing model advertisement')
                            response={'type':'llm_request','payload':{'request_id':'ws-delegate','type':'text-purpose','model_kind':'llm','prompt':'offline ws','params':{},'use_json':True,'enable_thinking':False}}
                            encoded=json.dumps(response).encode(); self.wfile.write(bytes([129,126])+struct.pack('!H',len(encoded))+encoded); self.wfile.flush(); continue
                        if packet['type'] not in ('user_auth','hb_ping'): continue
                        response={'type':'auth_ok' if packet['type']=='user_auth' else 'hb_pong','payload':{}}
                        encoded=json.dumps(response).encode(); self.wfile.write(bytes([129,len(encoded)])+encoded); self.wfile.flush()
                except (OSError,ConnectionError): pass
                self.close_connection=True
                return
            if self.path.startswith('/history?'):
                self.reply(200,{'history':[],'start_index':0}); return
            self.reply(200,{'public_key':crypto.get_public_key_pem()}) if self.path=='/auth/public_key' else self.reply(404,{})
        def do_POST(self):
            data=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            if self.path.endswith('/chat/completions'):
                provider_calls.append(data)
                if self.headers.get('Authorization')!='Bearer SYNTHETIC_KEY': errors.append('supplier key mismatch')
                if data.get('stream') is not False: errors.append('supplier must be nonstreaming')
                if data.get('model')=='slow': time.sleep(.8)
                if data.get('model')=='error': self.reply(503,{'error':'PRIVATE_PROVIDER_BODY'}); return
                self.reply(200,{'choices':[{'message':{'content':'bad-json' if data.get('model')=='bad-json' else '{"answer":"ok"}'}}],'usage':{'total_tokens':3,'private':'DO_NOT_RETURN'}}); return
            if self.path=='/auth/login':
                if data.get('username')=='reject': self.reply(401,{}); return
                self.reply(200,{'user_id':'ui-uuid','login_token':'login-test','message_token':'message-test'}); return
            if self.path=='/auth/auto_login':
                if data.get('token') not in ('login-test','login-rotated'):
                    self.reply(401,{}); return
                self.reply(200,{'user_id':'ui-uuid','login_token':'login-rotated','message_token':'message-test'}); return
            user=data.get('username')
            if data.get('token')!='message-test': errors.append('wrong preference token'); self.reply(401,{}); return
            if self.path=='/preference/get':
                reads[user]=reads.get(user,0)+1
                if user=='ui_retry':
                    time.sleep(.8)
                    if reads[user]==1: self.reply(503,{}); return
                if user=='fail_load': self.reply(503,{}); return
                prefs={'relationship':'知己','speaking_style':'' if reads[user]==1 else '文静恬淡','personality_traits':['真诚','安静'],'#sym:personality_text':'old ignored','custom_context':'original','unknown':'old' if reads[user]==1 else 'new'}
                if user=='legacy': prefs.pop('personality_traits'); prefs['#sym:personality_text']='开朗，认真'
                self.reply(200,{'preferences':prefs}); return
            if self.path=='/preference/overwrite':
                if user in ('slow_save','ui_retry'): time.sleep(.4)
                if user=='fail_once' and user not in writes:
                    writes[user] = None
                    self.reply(503,{})
                    return
                if user=='fail_load': errors.append('overwrote despite failed load')
                if user=='fail_save': self.reply(503,{}); return
                prefs=data['preferences']; writes[user]=prefs
                if user=='merge':
                    if prefs.get('unknown')!='new' or prefs.get('speaking_style')!='文静恬淡' or prefs.get('relationship')!='' or prefs.get('personality_traits')!=['温柔','认真','活泼','诚实']:
                        errors.append('preference merge or trait mismatch')
                    if prefs.get('#sym:personality_text')!='温柔，认真，活泼，诚实': errors.append('legacy personality not synchronized')
                self.reply(200,{'status':'success'}); return
            self.reply(404,{})
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler); thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
    try:
        result=subprocess.run([godot,*([] if gpu else ['--headless']),'--path',str(PROJECT),'--script',script],env={**os.environ,'GODOT_TEST_PYTHON':sys.executable,'GODOT_TEST_SERVER':f'http://127.0.0.1:{server.server_port}'},capture_output=True,text=True,encoding='utf8',errors='replace',timeout=90 if gpu else 40)
        print(result.stdout); print(result.stderr)
        if result.returncode or 'ERROR:' in result.stdout+result.stderr or 'FAIL:' in result.stdout or ': PASS' not in result.stdout or errors: raise RuntimeError(str(errors) or 'feature test failed')
        if script.endswith('test_preferences.gd'): assert 'merge' in writes
    finally: server.shutdown(); server.server_close(); thread.join(2)
    print('Offline feature API: PASS')
if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--godot',required=True); parser.add_argument('--script',default='res://tests/test_preferences.gd'); parser.add_argument('--gpu',action='store_true'); args=parser.parse_args(); run(args.godot,args.script,args.gpu)
