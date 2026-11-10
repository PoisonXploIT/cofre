import json
import http.server
from pathlib import Path

PAGE = r"""<!doctype html>
<html><head><meta charset="utf-8"><title>flujo completo</title></head>
<body><h1>create + get con prf</h1><button id="run">Ejecutar prueba (click, luego toque la llave)</button><pre id="out">pendiente</pre>
<script>
async function main(){
  const out=document.getElementById('out');
  const log={origin:location.origin};
  const s1=new Uint8Array(32); crypto.getRandomValues(s1);
  const s2=new Uint8Array(32); crypto.getRandomValues(s2);
  const s3=new Uint8Array(32); crypto.getRandomValues(s3);
  log.s1=Array.from(s1); log.s2=Array.from(s2); log.s3=Array.from(s3);
  try{
    const c=await navigator.credentials.create({publicKey:{
      rp:{name:'localhost'},
      challenge:s1,
      pubKeyCredParams:[{type:'public-key',alg:-7}],
      user:{id:new TextEncoder().encode('vault-probe'),name:'vault-probe',displayName:'vault-probe'},
      residentKey:'required',
      userVerification:'required',
      attestation:'none',
      extensions:{prf:{enroll:true,salt:s1}}
    }});
    log.create_ok=true;
    log.cid=c.id;
    const ad=new Uint8Array(c.response.getAuthenticatorData());
    log.ad1=Array.from(ad); log.flags1=ad[32];
    try{
      const a=await navigator.credentials.get({publicKey:{
        rp:{name:'localhost'},
        challenge:s2,
        allowCredentials:[{type:'public-key',id:new Uint8Array(atob(c.id.replace(/-/g,'+').replace(/_/g,'/')))}],
        userVerification:'required',
        extensions:{prf:{salt:s3}}
      }});
      log.get_ok=true;
      const ad2=new Uint8Array(a.response.getAuthenticatorData());
      log.ad2=Array.from(ad2); log.flags2=ad2[32];
    }catch(e){ log.get_error=String(e&&e.message?e.message:e); }
  }catch(e){ log.create_error=String(e&&e.message?e.message:e); }
  out.textContent=JSON.stringify(log).slice(0,1500);
  await fetch('/r',{method:'POST',body:JSON.stringify(log)});
}
document.getElementById('run').addEventListener('click', main);
</script></body></html>"""


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(PAGE.encode())

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        Path("probe_full.json").write_bytes(self.rfile.read(n))
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    http.server.ThreadingHTTPServer(("127.0.0.1", 8020), Handler).serve_forever()
