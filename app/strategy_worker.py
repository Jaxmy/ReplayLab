"""Trusted local Python only. Process isolation is not a security sandbox."""
import contextlib, json, sys
from pathlib import Path

namespace={}
with contextlib.redirect_stdout(sys.stderr):
    exec(compile(Path(sys.argv[1]).read_text(encoding='utf-8'),sys.argv[1],'exec'),namespace)
state={};initialized=False
for line in sys.stdin:
    try:
        ctx=json.loads(line)
        if ctx.get('_op')=='restore':
            state=ctx['state'];initialized=True
            print(json.dumps({'state':state},allow_nan=False),flush=True);continue
        if ctx.get('_op')=='snapshot':
            print(json.dumps({'state':state},allow_nan=False),flush=True);continue
        with contextlib.redirect_stdout(sys.stderr):
            if not initialized and callable(namespace.get('initialize')):namespace['initialize'](ctx,state)
            initialized=True
            for event in ctx.get('events',[]):
                callback=namespace.get('on_fill' if event.get('type')=='fill' else 'on_order')
                if callable(callback):callback(event,state)
            orders=namespace['on_bar'](ctx,state)
        print(json.dumps({'orders':orders or []},allow_nan=False),flush=True)
    except Exception as exc:
        print(json.dumps({'error':f'{type(exc).__name__}: {exc}'}),flush=True)
